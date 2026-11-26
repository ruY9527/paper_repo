"""单篇论文从账本到可解析任务包的闭环编排。"""

from __future__ import annotations

from ..config import AppConfig
from ..db.models import PaperRecord, PaperStatus, PaperTier
from ..db.repository import PaperRepository
from .downloader import download_paper
from .queue_exporter import export_paper_to_queue
from .scorer import score_and_persist

_TERMINAL_STATUSES = {
    PaperStatus.QUEUED.value,
    PaperStatus.ANALYZED.value,
    PaperStatus.STAGED.value,
    PaperStatus.PUBLISHED.value,
    PaperStatus.CLEANED.value,
}


def prepare_paper_for_analysis(
    config: AppConfig,
    repository: PaperRepository,
    paper_uid: str,
    *,
    force_tier_s: bool = False,
) -> PaperRecord:
    """按需打分、Paywall 过滤/下载并导出单篇任务包，终态操作幂等。"""
    paper = repository.get_paper(paper_uid)
    if paper is None:
        raise FileNotFoundError(f"论文不存在: {paper_uid}")
    if paper.status in _TERMINAL_STATUSES:
        return paper

    if (force_tier_s or not paper.tier or paper.status in {
        PaperStatus.FETCHED.value, PaperStatus.FAILED.value, PaperStatus.SKIPPED.value,
    }):
        score_and_persist(paper, config, repository, force_tier_s=force_tier_s)
        paper = repository.get_paper(paper_uid)

    if paper.status == PaperStatus.SKIPPED.value or paper.tier == PaperTier.B.value:
        return paper

    if paper.tier == PaperTier.S.value and paper.pdf_url:
        result = download_paper(config, repository, paper)
        if result == "paywall_blocked":
            return repository.get_paper(paper_uid)
        paper = repository.get_paper(paper_uid)
    elif paper.tier == PaperTier.A.value and paper.status != PaperStatus.SCORED.value:
        repository.update_status(paper_uid, PaperStatus.SCORED)
        paper = repository.get_paper(paper_uid)

    if paper.tier in (PaperTier.S.value, PaperTier.A.value):
        export_paper_to_queue(config, repository, paper, paper.fetch_date or None)
    return repository.get_paper(paper_uid)
