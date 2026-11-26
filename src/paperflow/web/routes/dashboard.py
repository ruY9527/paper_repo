"""Dashboard API：KPI、Venue 分布、30 天趋势、水位线健康度。"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, Depends

from ...config import ALL_VENUES, VENUE_DISPLAY_NAMES
from ...db.models import PENDING_ANALYSIS_STATUSES, PaperStatus, PaperTier
from ...db.repository import PaperRepository
from ..state import get_manager
from ..task_manager import TaskManager, now_iso
from ...utils.timeutil import today_date

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _dir_size_mb(path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 3)


@router.get("/summary")
def summary(manager: TaskManager = Depends(get_manager)):
    repo: PaperRepository = manager.repo
    cfg = manager.config
    papers = repo.get_all_papers()
    today = today_date().isoformat()

    # KPI
    s_count = sum(1 for p in papers if p.tier == PaperTier.S.value)
    a_count = sum(1 for p in papers if p.tier == PaperTier.A.value)
    queued = sum(
        1 for p in papers
        if p.status in PENDING_ANALYSIS_STATUSES
    )
    staged = sum(1 for p in papers if p.status == PaperStatus.STAGED.value)
    published = sum(1 for p in papers if p.status in (PaperStatus.PUBLISHED.value, PaperStatus.CLEANED.value))
    today_new = sum(1 for p in papers if p.fetch_date == today)

    pdf_mb = _dir_size_mb(cfg.workspace_path / "tmp" / "pdfs")
    db_mb = round(cfg.db_path.stat().st_size / (1024 * 1024), 3) if cfg.db_path.exists() else 0.0
    # 累计释放空间：从 run_logs message 粗略汇总不可靠，改用已清理篇数 * 估算；这里返回已清理计数
    cleaned_count = sum(1 for p in papers if p.pdf_deleted == 1)

    # Venue 分布（按 S/A/B 堆叠）
    venue_dist = []
    for v in ALL_VENUES:
        subset = [p for p in papers if p.venue.upper() == v]
        venue_dist.append({
            "venue": VENUE_DISPLAY_NAMES.get(v, v),
            "S": sum(1 for p in subset if p.tier == "S"),
            "A": sum(1 for p in subset if p.tier == "A"),
            "B": sum(1 for p in subset if p.tier == "B"),
            "total": len(subset),
        })

    # 近 30 天每日入库趋势
    trend: list[dict] = []
    counts = Counter(p.fetch_date for p in papers)
    for i in range(29, -1, -1):
        d = (today_date() - timedelta(days=i)).isoformat()
        trend.append({"date": d, "count": counts.get(d, 0)})

    # 水位线健康度
    watermarks = []
    for wm in repo.get_all_watermarks():
        try:
            lag = (today_date() - date.fromisoformat(wm.last_success_date)).days
        except Exception:
            lag = -1
        watermarks.append({
            "source": wm.source_name,
            "venue": wm.venue,
            "last_success_date": wm.last_success_date,
            "last_status": wm.last_status,
            "last_error": wm.last_error,
            "lag_days": lag,
            "healthy": 0 <= lag <= 1,
        })

    needs_catchup = any(not w["healthy"] for w in watermarks) or not watermarks

    return {
        "kpi": {
            "total": len(papers),
            "today_new": today_new,
            "tier_s": s_count,
            "tier_a": a_count,
            "queued": queued,
            "staged": staged,
            "published": published,
            "pdf_size_mb": pdf_mb,
            "db_size_mb": db_mb,
            "cleaned_count": cleaned_count,
        },
        "venue_distribution": venue_dist,
        "daily_trend": trend,
        "watermarks": watermarks,
        "needs_catchup": needs_catchup,
        "updated_at": now_iso(),
    }
