"""Phase 13：受限论文清单（Paywall Hub）REST API。"""

from __future__ import annotations

import os
from typing import Any

import yaml
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile

from ...config import AppConfig, PROJECT_ROOT
from ...pipeline.manual_pdf import attach_local_pdf, export_pending_checklist, scan_inbox_pdfs
from ...pipeline.paywall_filter import PaywallFilter
from ..state import get_manager
from ..task_manager import TaskManager, reload_config

router = APIRouter(prefix="/api/paywall", tags=["paywall"])

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


@router.get("/papers")
def list_papers(publisher: str | None = None, venue: str | None = None,
                manual_status: str | None = None, q: str | None = None,
                limit: int = 200, offset: int = 0,
                manager: TaskManager = Depends(get_manager)):
    papers = manager.repo.get_paywall_papers(
        publisher=publisher, venue=venue, manual_status=manual_status,
        q=q, limit=limit, offset=offset,
    )
    stats = manager.repo.count_paywall_by_status()
    return {"items": papers, "total": len(papers), "stats": stats}


@router.post("/papers/{paper_uid}/rescue")
def rescue(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    paper = manager.repo.get_paper(paper_uid)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    pf = PaywallFilter(manager.config, manager.repo)
    result = pf.filter_and_rescue(paper)
    if result.get("action") == "rescued":
        from ...utils.timeutil import now_iso
        manager.repo.update_paywall_paper(
            paper_uid, oa_rescue_status="RESCUED_ARXIV",
            manual_status="RESCUED", resolved_at=now_iso(),
        )
        result["oa_rescue_status"] = "RESCUED_ARXIV"
    elif (result.get("action") == "blocked"
          and manager.config.download_policy.auto_try_arxiv_rescue):
        manager.repo.update_paywall_paper(paper_uid, oa_rescue_status="NOT_FOUND")
        result["oa_rescue_status"] = "NOT_FOUND"
    if result.get("action") != "blocked":
        from ...pipeline.preparation import prepare_paper_for_analysis
        prepared = prepare_paper_for_analysis(manager.config, manager.repo, paper_uid)
        result.update({"status": prepared.status, "tier": prepared.tier})
    return result


@router.post("/papers/{paper_uid}/upload-pdf")
async def upload_pdf(paper_uid: str, file: UploadFile = File(...),
                     manager: TaskManager = Depends(get_manager)):
    data = await file.read()
    try:
        result = attach_local_pdf(manager.config, manager.repo, paper_uid, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result


@router.post("/papers/{paper_uid}/fallback-abstract")
def fallback_abstract(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    paper = manager.repo.get_paper(paper_uid)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    manager.repo.update_paywall_paper(paper_uid, manual_status="ABSTRACT_ONLY")
    # 转为 A 级摘要速览（不下载 PDF）
    from ...db.models import PaperStatus, PaperTier
    from ...pipeline.queue_exporter import export_paper_to_queue
    manager.repo.update_fields(paper_uid, tier=PaperTier.A.value)
    manager.repo.update_status(paper_uid, PaperStatus.SCORED)
    paper = manager.repo.get_paper(paper_uid)
    export_paper_to_queue(manager.config, manager.repo, paper, paper.fetch_date or None)
    return {"ok": True, "paper_uid": paper_uid, "manual_status": "ABSTRACT_ONLY",
            "status": PaperStatus.QUEUED.value}


@router.patch("/papers/{paper_uid}")
def update_paper(paper_uid: str, body: dict[str, Any] = Body(...),
                 manager: TaskManager = Depends(get_manager)):
    fields = {}
    if "manual_status" in body:
        fields["manual_status"] = body["manual_status"]
    if "note" in body:
        fields["note"] = body["note"]
    manager.repo.update_paywall_paper(paper_uid, **fields)
    return {"ok": True, "paper_uid": paper_uid}


@router.post("/scan-inbox")
def scan_inbox(manager: TaskManager = Depends(get_manager)):
    return scan_inbox_pdfs(manager.config, manager.repo)


@router.get("/export")
def export_checklist(fmt: str = "markdown",
                     manager: TaskManager = Depends(get_manager)):
    content, filename = export_pending_checklist(manager.config, manager.repo, fmt=fmt)
    from fastapi.responses import Response
    media = "text/markdown" if fmt in ("markdown", "md") else "text/csv"
    return Response(content=content, media_type=media,
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/domains")
def get_domains(manager: TaskManager = Depends(get_manager)):
    return {"domains": [d.model_dump() for d in manager.config.download_policy.paywall_domains]}


@router.put("/domains")
def put_domains(body: dict[str, Any] = Body(...),
                manager: TaskManager = Depends(get_manager)):
    """动态维护 paywall_domains，写回 config.yaml（备份 + 校验）。"""
    domains = body.get("domains", [])
    if not isinstance(domains, list):
        raise HTTPException(status_code=422, detail="domains 必须是数组")
    import shutil
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    data.setdefault("download_policy", {})
    data["download_policy"]["paywall_domains"] = domains
    try:
        AppConfig.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"配置校验失败: {exc}")
    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, CONFIG_PATH.with_suffix(".yaml.bak"))
    tmp = CONFIG_PATH.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)
    reload_config(manager, CONFIG_PATH)
    return {"saved": True, "count": len(domains)}
