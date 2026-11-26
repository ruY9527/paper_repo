"""论文账本 API：分页检索、提权/降权、插队、重试、BibTeX。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from ...db.models import PaperStatus, PaperTier
from ...utils.bibtex import to_bibtex
from ...utils.timeutil import today_date
from ..state import get_manager
from ..task_manager import TaskManager

router = APIRouter(prefix="/api/papers", tags=["papers"])


def _paper_tags(p) -> list[str]:
    """合并方向标签与兴趣标签，去重保序，供账本快速浏览。"""
    import json
    tags: list[str] = []
    for raw in (getattr(p, "topic_tags_json", "[]"), getattr(p, "matched_tags_json", "[]")):
        try:
            vals = json.loads(raw or "[]")
        except (json.JSONDecodeError, TypeError):
            vals = []
        if isinstance(vals, list):
            for v in vals:
                v = str(v).strip()
                if v and v not in tags:
                    tags.append(v)
    return tags[:8]


def _paper_dict(p, analysis_times: dict[str, str] | None = None) -> dict:
    # 流水线阶段标记（从账本字段推导，零额外存储）
    published = (p.status == PaperStatus.PUBLISHED.value or
                 p.status == PaperStatus.CLEANED.value or bool(getattr(p, "md_blog_path", "")))
    analyzed = (p.status in (PaperStatus.STAGED.value, PaperStatus.PUBLISHED.value,
                             PaperStatus.CLEANED.value) or bool(getattr(p, "md_staging_path", "")))
    downloaded = (p.status in (PaperStatus.DOWNLOADED.value, PaperStatus.QUEUED.value,
                               PaperStatus.STAGED.value, PaperStatus.PUBLISHED.value,
                               PaperStatus.CLEANED.value) or bool(p.pdf_local_path))
    fetched = True  # 能在账本里即已采集
    stage = sum((fetched, downloaded, analyzed, published)) - 1  # 0..3
    return {
        "paper_uid": p.paper_uid,
        "title": p.title,
        "authors": json.loads(p.authors_json or "[]"),
        "venue": p.venue,
        "pub_year": p.pub_year,
        "pub_date": p.pub_date,
        "fetch_date": p.fetch_date,
        "source": p.source,
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "abstract": p.abstract,
        "tier": p.tier,
        "score": p.score,
        "is_radar_hit": p.is_radar_hit,
        "code_url": p.code_url,
        "code_stars": p.code_stars,
        "status": p.status,
        "pdf_deleted": p.pdf_deleted,
        "pdf_local_path": p.pdf_local_path,
        "paper_url": p.paper_url,
        "last_error": p.last_error,
        "retry_count": p.retry_count,
        # 流水线视图所需标记
        "stage": stage,
        "stage_flags": {"fetched": fetched, "downloaded": downloaded,
                        "analyzed": analyzed, "published": published},
        "md_staging_path": getattr(p, "md_staging_path", "") or "",
        "md_blog_path": getattr(p, "md_blog_path", "") or "",
        # 账本基本信息：检索/下载/解析/发布各时间点 + 关键词
        "fetch_date": p.fetch_date,
        "created_at": getattr(p, "created_at", "") or "",
        "updated_at": getattr(p, "updated_at", "") or "",
        "downloaded_at": getattr(p, "downloaded_at", "") or "",
        "last_analysis_at": (analysis_times or {}).get(p.paper_uid, ""),
        "tags": _paper_tags(p),
        "discovery_mode": getattr(p, "discovery_mode", "") or "",
    }


@router.get("")
def list_papers(
    q: str | None = None,
    venue: str | None = None,
    tier: str | None = None,
    status: str | None = None,
    has_code: bool = False,
    radar_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    manager: TaskManager = Depends(get_manager),
):
    papers = manager.repo.get_all_papers()

    if q:
        needle = q.lower()
        papers = [p for p in papers if needle in p.title.lower()
                  or needle in (p.abstract or "").lower()
                  or needle in p.paper_uid.lower()
                  or needle in (p.authors_json or "").lower()]
    if venue:
        papers = [p for p in papers if p.venue.upper() == venue.upper()]
    if tier:
        papers = [p for p in papers if p.tier.upper() == tier.upper()]
    if status:
        papers = [p for p in papers if p.status.upper() == status.upper()]
    if has_code:
        papers = [p for p in papers if p.code_url]
    if radar_only:
        papers = [p for p in papers if p.is_radar_hit]

    total = len(papers)
    page = papers[offset:offset + limit]
    # 批量取本页论文最近一次解析时间（一次查询，避免 N+1）
    analysis_times: dict[str, str] = {}
    if page:
        try:
            conn = manager.repo._connect()
            uids = [p.paper_uid for p in page]
            placeholders = ",".join("?" for _ in uids)
            for row in conn.execute(
                f"SELECT paper_uid, created_at FROM analysis_runs WHERE paper_uid IN ({placeholders}) "
                "ORDER BY id DESC", uids
            ).fetchall():
                if row["paper_uid"] not in analysis_times:  # 第一条即最新
                    analysis_times[row["paper_uid"]] = row["created_at"]
            conn.close()
        except Exception:
            pass
    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [_paper_dict(p, analysis_times) for p in page],
    }


@router.post("/add")
def add_paper(body: dict[str, Any] = Body(...), manager: TaskManager = Depends(get_manager)):
    """单篇 URL/DOI 插队，强制 S 级。"""
    url = body.get("url")
    if not url:
        raise HTTPException(status_code=422, detail="缺少 url")
    from ...fetchers.single_adder import SinglePaperAdder
    from ...pipeline.dedup import generate_paper_uid, normalize_title
    from ...pipeline.preparation import prepare_paper_for_analysis

    try:
        raw = SinglePaperAdder(manager.config).add(url, venue=body.get("venue"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"解析失败: {exc}")

    uid = generate_paper_uid(doi=raw.doi, arxiv_id=raw.arxiv_id,
                             openreview_id=raw.openreview_id, title=raw.title)
    record, _ = manager.repo.insert_paper_from_fields(
        paper_uid=uid, title=raw.title, normalized_title=normalize_title(raw.title),
        authors_json=json.dumps(raw.authors, ensure_ascii=False),
        affiliations_json=json.dumps(raw.affiliations, ensure_ascii=False),
        venue=raw.venue.upper(), pub_year=raw.pub_year, pub_date=raw.pub_date,
        fetch_date=today_date().isoformat(), source="manual",
        doi=raw.doi, arxiv_id=raw.arxiv_id, openreview_id=raw.openreview_id,
        abstract=raw.abstract, comment=raw.comment, paper_url=raw.paper_url,
        pdf_url=raw.pdf_url, code_url=raw.code_url, project_url=raw.project_url,
    )
    prepared = prepare_paper_for_analysis(
        manager.config, manager.repo, uid, force_tier_s=True,
    )
    return {"paper_uid": uid, "tier": prepared.tier, "status": prepared.status}


@router.patch("/{paper_uid}/tier")
def set_tier(paper_uid: str, body: dict[str, Any] = Body(...),
             manager: TaskManager = Depends(get_manager)):
    """手动调整分级 S/A/B 或 skip。"""
    p = manager.repo.get_paper(paper_uid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    tier = str(body.get("tier", "")).upper()
    if tier not in ("S", "A", "B", "SKIP"):
        raise HTTPException(status_code=422, detail="tier 必须为 S/A/B/SKIP")

    if tier == "SKIP":
        manager.repo.update_status(paper_uid, PaperStatus.SKIPPED)
        return {"paper_uid": paper_uid, "tier": p.tier, "status": "SKIPPED"}
    # 升为 S 级时若原本是 B/SKIPPED，需回到 SCORED 以进入下载队列
    new_status = p.status
    if tier != "B" and p.status in (PaperStatus.SKIPPED.value, PaperStatus.FETCHED.value):
        new_status = PaperStatus.SCORED.value
    manager.repo.update_fields(paper_uid, tier=tier)
    manager.repo.update_status(paper_uid, new_status)
    if tier in (PaperTier.S.value, PaperTier.A.value):
        from ...pipeline.preparation import prepare_paper_for_analysis
        prepared = prepare_paper_for_analysis(manager.config, manager.repo, paper_uid)
        return {"paper_uid": paper_uid, "tier": prepared.tier, "status": prepared.status}
    return {"paper_uid": paper_uid, "tier": tier, "status": new_status}


@router.post("/{paper_uid}/retry")
def retry(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    p = manager.repo.get_paper(paper_uid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    from ...pipeline.preparation import prepare_paper_for_analysis
    retry_count = p.retry_count + 1
    if p.status not in (PaperStatus.QUEUED.value, PaperStatus.ANALYZED.value,
                        PaperStatus.STAGED.value, PaperStatus.PUBLISHED.value,
                        PaperStatus.CLEANED.value):
        manager.repo.update_status(
            paper_uid, PaperStatus.FETCHED,
            retry_count=retry_count, last_error=None,
        )
    else:
        manager.repo.update_fields(paper_uid, retry_count=retry_count, last_error=None)
    prepared = prepare_paper_for_analysis(manager.config, manager.repo, paper_uid)
    return {"paper_uid": paper_uid, "status": prepared.status, "retry_count": retry_count}


@router.get("/{paper_uid}/bibtex")
def bibtex(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    p = manager.repo.get_paper(paper_uid)
    if p is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return {"paper_uid": paper_uid, "bibtex": to_bibtex(p)}
