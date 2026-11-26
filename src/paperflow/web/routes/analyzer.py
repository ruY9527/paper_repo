"""Phase 11：AI 解析中心 REST API（08 文档第 6.1 节）。

写操作（run）走 TaskManager 互斥锁 + SSE；其余为只读 / 协作桥接接口。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile

from ...analyzers.base import atomic_write_text, sanitize_markdown_output
from ...analyzers.runner import AnalyzerRunner, create_analyzer
from ...config import PROJECT_ROOT
from ...db.models import PENDING_ANALYSIS_STATUSES, PaperStatus
from ...pipeline.md_validator import validate_md_file
from ...pipeline.queue_exporter import export_paper_to_queue
from ...publisher.blog_articles import publish_one
from ...publisher.digest import generate_digest
from ..state import get_manager
from ..task_manager import TaskBusyError, TaskManager
from ...utils.timeutil import today_date

router = APIRouter(prefix="/api/analyzer", tags=["analyzer"])


def _queue_dirs(config) -> list[Path]:
    root = config.workspace_path / "queue"
    if not root.exists():
        return []
    return [d for d in root.iterdir() if d.is_dir()]


def _find_paper_dir(config, paper_uid: str) -> Path | None:
    candidates = sorted(
        (d / paper_uid for d in _queue_dirs(config) if (d / paper_uid).is_dir()),
        reverse=True,
    )
    return candidates[0] if candidates else None


# ---------- 只读 / 协作接口 ----------

def _pending_analysis_papers(repo):
    return [
        paper
        for status in PENDING_ANALYSIS_STATUSES
        for paper in repo.get_papers_by_status(status)
    ]


@router.get("/status")
def analyzer_status(manager: TaskManager = Depends(get_manager)):
    cfg = manager.config
    papers = manager.repo.get_all_papers()
    # 可解析 = 已导出队列(QUEUED) 或 已下载PDF(DOWNLOADED，可即时生成任务包)
    queued = [p for p in papers if p.status in PENDING_ANALYSIS_STATUSES]
    # 各后端配置状态
    backends = {
        "claude_cli": {"enabled": cfg.analyzer.claude_cli.enabled,
                       "executable": cfg.analyzer.claude_cli.executable,
                       "model": cfg.analyzer.claude_cli.model or "default(Kimi K3)"},
        "harness_web": {"enabled": cfg.analyzer.harness_web.enabled,
                        "web_url": cfg.analyzer.harness_web.web_url},
        "openai_api": {"enabled": cfg.analyzer.openai_api.enabled,
                       "model": cfg.analyzer.openai_api.model},
    }
    return {
        "default_backend": cfg.analyzer.default_backend,
        "backends": backends,
        "timeout_seconds": cfg.analyzer.timeout_seconds,
        "max_retries": cfg.analyzer.max_retries,
        "queue_total": len(queued),
        "queue_s": sum(1 for p in queued if p.tier == "S"),
        "queue_a": sum(1 for p in queued if p.tier == "A"),
    }


@router.post("/check")
def analyzer_check(body: dict[str, Any] = Body(default={}),
                   manager: TaskManager = Depends(get_manager)):
    backend = body.get("backend") or manager.config.analyzer.default_backend
    probe = bool(body.get("probe", False))
    model = body.get("model")
    provider = body.get("provider")
    try:
        analyzer = create_analyzer(backend, manager.config, manager.repo, model=model, provider=provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return analyzer.health_check(probe=probe)


@router.get("/queue")
def analyzer_queue(
    q: str | None = None,
    tier: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    manager: TaskManager = Depends(get_manager),
):
    papers = _pending_analysis_papers(manager.repo)
    # 查询条件：标题/UID 关键词、分级、来源状态
    if q:
        needle = q.lower()
        papers = [p for p in papers if needle in (p.title or "").lower()
                  or needle in p.paper_uid.lower()]
    if tier:
        papers = [p for p in papers if p.tier.upper() == tier.upper()]
    if status:
        papers = [p for p in papers if p.status.upper() == status.upper()]
    total = len(papers)
    papers = papers[offset:offset + limit]
    items = []
    for p in papers:
        paper_dir = _find_paper_dir(manager.config, p.paper_uid)
        chars = 0
        has_text = False
        if paper_dir:
            text_file = paper_dir / "extracted_text.md"
            if text_file.exists():
                body = text_file.read_text(encoding="utf-8", errors="replace")
                chars = len(body)
                has_text = True
        # DOWNLOADED 但还没任务包时，估算正文长度用摘要或本地 PDF 大小
        local_pdf = Path(p.pdf_local_path) if getattr(p, "pdf_local_path", "") else None
        if not has_text:
            chars = len(p.abstract or "")
        assets = manager.config.workspace_path / "staging" / "assets" / p.paper_uid
        items.append({
            "paper_uid": p.paper_uid, "title": p.title, "venue": p.venue,
            "tier": p.tier, "fetch_date": p.fetch_date, "status": p.status,
            "chars": chars, "has_text": has_text,
            "has_local_pdf": bool(local_pdf and local_pdf.exists()),
            "has_figures": assets.exists() and any(assets.glob("*.webp")),
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/prompt/{paper_uid}")
def analyzer_prompt(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    paper_dir = _find_paper_dir(manager.config, paper_uid)
    if (paper_dir is None or not (paper_dir / "prompt.md").exists()
            or not (paper_dir / "extracted_text.md").exists()):
        from ...analyzers.base import ensure_analysis_package
        try:
            paper_dir = ensure_analysis_package(manager.config, manager.repo, paper_uid)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    prompt_file = paper_dir / "prompt.md"
    text_file = paper_dir / "extracted_text.md"
    prompt_text = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""
    body = text_file.read_text(encoding="utf-8") if text_file.exists() else ""
    combined = (
        f"{prompt_text}\n\n---\n\n{body}\n\n---\n"
        "【输出约束】请直接输出以 `---` 开头的完整 Markdown 文档，不要代码块包裹与开场白。\n"
    )
    return {"paper_uid": paper_uid, "prompt": combined, "chars": len(combined)}


@router.get("/batch-instruction")
def batch_instruction(date: str | None = None,
                      manager: TaskManager = Depends(get_manager)):
    date = date or today_date().isoformat()
    text = (
        f"请读取 `workspace/queue/{date}/queue_manifest.json`，"
        f"逐篇阅读各子目录下的 `meta.json`、`prompt.md` 和 `extracted_text.md`，"
        f"严格按照输出契约将分析结果写入 `workspace/staging/{date}/<paper_uid>.md`。"
    )
    return {"date": date, "instruction": text}


@router.post("/import-md/{paper_uid}")
def import_md(paper_uid: str, body: dict[str, Any] = Body(...),
              manager: TaskManager = Depends(get_manager)):
    """粘贴回填：Harness Web 复制回的 Markdown -> 清洗 -> 落盘 -> 校验入库。"""
    raw = body.get("markdown", "")
    if not raw or not str(raw).strip():
        raise HTTPException(status_code=422, detail="markdown 不能为空")
    paper = manager.repo.get_paper(paper_uid)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")

    cleaned = sanitize_markdown_output(str(raw))
    target_date = paper.fetch_date or today_date().isoformat()
    staging_path = manager.config.workspace_path / "staging" / target_date / f"{paper_uid}.md"
    from ...pipeline.math_fix import fix_bare_math
    atomic_write_text(staging_path, fix_bare_math(cleaned))

    validation = validate_md_file(staging_path, manager.repo, manager.config, persist=True)
    manager.repo.add_analysis_run(
        paper_uid=paper_uid, backend="harness_web",
        status="SUCCESS" if validation.ok else "VALIDATION_FAILED",
        output_chars=len(cleaned),
        error_message="；".join(validation.errors) if not validation.ok else None,
    )
    if not validation.ok:
        raise HTTPException(status_code=422, detail="校验失败: " + "；".join(validation.errors))
    try:
        generate_digest(manager.config, manager.repo, target_date)
    except Exception:
        pass
    return {"paper_uid": paper_uid, "ok": True, "staging_path": str(staging_path),
            "paper_uid_check": True}


@router.post("/import-local-pdf")
async def import_local_pdf(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    venue: str | None = Form(None),
    tier: str = Form("S"),
    manager: TaskManager = Depends(get_manager),
):
    """导入本地已下载的 PDF 直接用于 AI 解析（无需 fetch/download）。

    流程：校验 %PDF → 从 PDF 首页推断标题 → 建/复用账本记录 →
    即时抽取全文 + 用 PromptManager 生成 13 节 prompt → 状态置 DOWNLOADED，
    立即出现在解析中心队列。
    """
    from ...pipeline.dedup import generate_paper_uid, normalize_title
    from ...analyzers.base import ensure_analysis_package
    from ...db.models import PaperRecord, PaperStatus

    data = await file.read()
    if not data or data[:4] != b"%PDF":
        raise HTTPException(status_code=400, detail="文件头非 %PDF（不是合法 PDF）")
    max_mb = manager.config.storage.max_pdf_size_mb
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件超过大小上限（{max_mb}MB）")

    # 从 PDF 首页推断标题（用户传入优先）
    inferred = title or ""
    if not inferred:
        try:
            import fitz
            doc = fitz.open(stream=data, filetype="pdf")
            first_page = doc[0].get_text("text") if len(doc) else ""
            doc.close()
            for line in first_page.splitlines():
                if line.strip() and len(line.strip()) > 8:
                    inferred = line.strip()[:200]
                    break
        except Exception:
            pass
    if not inferred:
        inferred = (file.filename or "local_pdf").replace(".pdf", "")

    uid = generate_paper_uid(title=inferred)
    today = today_date().isoformat()
    paper = manager.repo.get_paper(uid)
    if paper is None:
        paper = PaperRecord(
            paper_uid=uid, title=inferred, normalized_title=normalize_title(inferred),
            authors_json="[]", venue=venue or "arXiv", pub_year=manager.config.target_year,
            fetch_date=today, source="manual", tier=tier,
            status=PaperStatus.DOWNLOADED.value, abstract="", discovery_mode="manual",
        )
        manager.repo.upsert_paper(paper)
    else:
        # 已存在：确保状态可被解析
        if paper.status not in (PaperStatus.DOWNLOADED.value, PaperStatus.QUEUED.value):
            manager.repo.update_status(uid, PaperStatus.DOWNLOADED)

    # 即时抽取全文 + 生成标准 queue 任务包并置 QUEUED。
    paper_dir = ensure_analysis_package(manager.config, manager.repo, uid, pdf_bytes=data)
    if paper.tier not in ("S", "A"):
        manager.repo.update_paper_fields(uid, tier="S", tier_source="manual")
        paper = manager.repo.get_paper(uid)
    export_paper_to_queue(manager.config, manager.repo, paper, paper.fetch_date)
    chars = len((paper_dir / "extracted_text.md").read_text(encoding="utf-8", errors="replace"))
    return {"paper_uid": uid, "title": inferred,
            "status": manager.repo.get_paper(uid).status,
            "text_chars": chars, "queue_dir": str(paper_dir)}


@router.get("/engines")
def analyzer_engines(manager: TaskManager = Depends(get_manager)):
    """解析引擎能力清单（数据驱动前端下拉，新增引擎前端零改动）。"""
    from ...analyzers.engine_registry import list_engines
    return {"items": list_engines(manager.config), "default": manager.config.analyzer.default_backend}


@router.get("/models")
def analyzer_models():
    """读取本地 DeepSeek Harness Web（DSH）的模型目录，供前端模型下拉框选择。"""
    from ...analyzers.model_catalog import load_harness_models
    return load_harness_models()


def _find_staging_md(config, paper_uid: str) -> Path | None:
    root = config.workspace_path / "staging"
    if not root.exists():
        return None
    candidates = sorted(root.glob(f"*/{paper_uid}.md"), reverse=True)
    return candidates[0] if candidates else None


@router.get("/result/{paper_uid}")
def analyzer_result(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    """本地查看：返回解析后的 staging Markdown 内容与路径。"""
    paper = manager.repo.get_paper(paper_uid)
    md = None
    if paper and paper.md_staging_path:
        candidate = Path(paper.md_staging_path)
        if not candidate.is_absolute():
            candidate = manager.config.workspace_path / candidate
        if candidate.is_file():
            md = candidate
    if md is None:
        md = _find_staging_md(manager.config, paper_uid)
    if md is None:
        raise HTTPException(status_code=404, detail="尚未生成解析结果")
    content = md.read_text(encoding="utf-8", errors="replace")
    return {"paper_uid": paper_uid, "path": str(md), "content": content,
            "chars": len(content)}


@router.post("/sync-to-blog/{paper_uid}")
def analyzer_sync_to_blog(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    """通过统一单篇发布内核同步到公开博客仓库。"""
    md = _find_staging_md(manager.config, paper_uid)
    result = publish_one(manager.config, manager.repo, paper_uid, staging_path=md)
    if not result.get("ok"):
        error = result.get("error", "发布失败")
        raise HTTPException(status_code=404 if error == "论文不存在" else 400, detail=error)
    return result


@router.get("/history")
def analyzer_history(limit: int = 50, offset: int = 0,
                     manager: TaskManager = Depends(get_manager)):
    return {"items": manager.repo.get_analysis_runs(limit=limit, offset=offset)}


@router.get("/progress/{category}")
def analyzer_progress_detail(category: str, manager: TaskManager = Depends(get_manager)):
    """点击统计胶囊展开明细：running/success/failed/interrupted 各自的论文列表。"""
    if category not in ("running", "success", "failed", "interrupted"):
        raise HTTPException(status_code=422, detail="未知分类")
    items = manager.repo.get_analysis_category(category)
    return {"category": category, "count": len(items), "items": items}


@router.get("/progress")
def analyzer_progress(manager: TaskManager = Depends(get_manager)):
    """解析进度视图：解析中/已完成/失败/中断分组 + 每篇最新状态。

    供前端分类显示「正在解析/已解析/失败待续」，并据此判断断点续传候选。
    """
    prog = manager.repo.get_analysis_progress(limit=60)
    # 给队列论文附上最新解析结果，便于前端分类
    latest = prog.pop("latest_by_paper")
    papers = _pending_analysis_papers(manager.repo)
    for p in papers:
        run = latest.get(p.paper_uid)
        p_run = {"last_status": run["status"] if run else None,
                 "last_stage": run["stage"] if run else None,
                 "last_at": run["created_at"] if run else None,
                 "attempt": run["attempt"] if run else 0}
        prog.setdefault("papers", {})[p.paper_uid] = p_run
    return prog


@router.post("/resume-check")
def analyzer_resume_check(body: dict = Body(default={}),
                          manager: TaskManager = Depends(get_manager)):
    """断点续传：返回待解析列表中需要重跑的 UID（排除已成功/仍 RUNNING 的）。"""
    uids = body.get("paper_uids") or []
    if not uids:
        return {"resume": [], "skipped": [], "message": "未指定论文"}
    latest = manager.repo.get_analysis_progress(limit=1)["latest_by_paper"]
    resume, skipped = [], []
    for uid in uids:
        run = latest.get(uid)
        if run and run["status"] in ("SUCCESS", "RUNNING"):
            skipped.append({"paper_uid": uid, "reason": run["status"]})
        else:
            resume.append(uid)
    return {"resume": resume, "skipped": skipped,
            "message": f"续传 {len(resume)} 篇，跳过 {len(skipped)} 篇"}


# ---------- 写操作：批量解析 ----------

def _run_analyze(ctx: dict):
    manager: TaskManager = ctx["manager"]
    params = ctx["params"]
    emit = ctx["emit"]
    backend = params.get("backend") or manager.config.analyzer.default_backend
    model = params.get("model")
    provider = params.get("provider")

    runner = AnalyzerRunner(manager.config, manager.repo, backend=backend, model=model, provider=provider)
    uids = params.get("paper_uids") or []
    if not uids:
        # 同时纳入已导出队列(QUEUED)与已下载PDF(DOWNLOADED)的论文
        candidates = (manager.repo.get_papers_by_status(PaperStatus.QUEUED.value)
                      + manager.repo.get_papers_by_status(PaperStatus.DOWNLOADED.value))
        if params.get("tiers"):
            wanted = {t.strip().upper() for t in params["tiers"].split(",")}
            candidates = [p for p in candidates if p.tier in wanted]
        if params.get("limit"):
            candidates = candidates[: int(params["limit"])]
        uids = [p.paper_uid for p in candidates]

    emit(stage="preparing", message=f"准备解析 {len(uids)} 篇论文（backend={backend}）",
         current=0, total=len(uids))
    results = runner.run_batch(
        uids, task_id=ctx["task_id"], cancel_event=ctx.get("cancel_event"),
        progress_cb=lambda **kw: emit(**kw),
    )
    payload = [
        {"paper_uid": r.paper_uid, "status": r.status, "ok": r.ok,
         "attempt": r.attempt, "duration_ms": r.duration_ms,
         "error_message": r.error_message, "staging_path": r.staging_path}
        for r in results
    ]
    ok_n = sum(1 for r in results if r.ok or r.status == "SUCCESS")
    failed = [r for r in results if not (r.ok or r.status == "SUCCESS")]
    detail = ""
    if failed:
        detail = "；失败：" + "、".join(
            f"{r.paper_uid}({r.status}: {(r.error_message or '未知')[:60]})" for r in failed[:5]
        )
    emit(stage="result", level="INFO" if not failed else "WARNING",
         message=f"解析完成：成功 {ok_n}/{len(results)}{detail}",
         percent=100, results=payload)
    return {"count": len(results), "results": payload}


@router.post("/run")
def analyzer_run(body: dict[str, Any] = Body(default={}),
                 manager: TaskManager = Depends(get_manager)):
    def runner(ctx):
        ctx["manager"] = manager
        return _run_analyze(ctx)

    try:
        task = manager.submit("analyze", runner, body)
    except TaskBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"task_id": task.task_id, "command": "analyze", "status": task.status}
