"""自动/手动补录调度器（02 文档第 3 节）。

核心原则：按天切片；只有整个子区间无异常完成才推进水位线到该切片末尾。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..config import AppConfig
from ..db.repository import PaperRepository
from ..fetchers.base import BaseFetcher, RawPaper
from ..fetchers.arxiv_fetcher import ArxivFetcher
from ..fetchers.openalex_fetcher import OpenAlexFetcher
from ..fetchers.openreview_fetcher import OpenReviewFetcher
from ..fetchers.base import RawPaper as RawPaperType
from ..utils.logger import get_logger
from ..utils.timeutil import today_date
from .dedup import generate_paper_uid, normalize_title
from .scorer import score_and_persist

logger = get_logger()


@dataclass
class BackfillResult:
    fetched: int = 0
    new_papers: int = 0
    tier_s: int = 0
    tier_a: int = 0
    failed: int = 0
    slices: list[tuple[date, date]] = field(default_factory=list)
    last_success_date: str | None = None
    message: str = ""


def slice_range(start: date, end: date, max_slice_days: int) -> list[tuple[date, date]]:
    """把 [start, end] 切成若干连续子区间（含首尾）。"""
    slices: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        slice_end = min(cur + timedelta(days=max_slice_days - 1), end)
        slices.append((cur, slice_end))
        cur = slice_end + timedelta(days=1)
    return slices


def determine_start_date(
    repo: PaperRepository, source_name: str, venue: str, config: AppConfig, today: date
) -> date:
    """根据水位线决定自动补录起始日。"""
    wm = repo.get_watermark(source_name, venue)
    if wm is None:
        return today - timedelta(days=config.backfill.default_lookback_days)
    return date.fromisoformat(wm.last_success_date) + timedelta(days=1)


def clamp_start_date(start: date, today: date, config: AppConfig) -> tuple[date, bool]:
    """安全保护：超过 max_auto_catchup_days 则截断到最近 N 天。返回 (新起始日, 是否被截断)。"""
    max_days = config.backfill.max_auto_catchup_days
    if (today - start).days > max_days:
        return today - timedelta(days=max_days), True
    return start, False


def ingest_papers(
    papers: list[RawPaperType],
    repo: PaperRepository,
    config: AppConfig,
    *,
    source_override: str | None = None,
    query_stars: bool = False,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """去重入库 + 打分；dry_run 只读判重并在内存打分。"""
    from ..db.models import PaperRecord
    from .scorer import score_paper

    new_count = s_count = a_count = 0
    for p in papers:
        fields = dict(
            paper_uid=generate_paper_uid(
                doi=p.doi, arxiv_id=p.arxiv_id,
                openreview_id=p.openreview_id, title=p.title,
            ),
            title=p.title,
            normalized_title=normalize_title(p.title),
            authors_json=__import__("json").dumps(p.authors, ensure_ascii=False),
            affiliations_json=__import__("json").dumps(p.affiliations, ensure_ascii=False),
            venue=p.venue.upper(), pub_year=p.pub_year, pub_date=p.pub_date,
            fetch_date=today_date().isoformat(), source=source_override or p.source,
            doi=p.doi, arxiv_id=p.arxiv_id, openreview_id=p.openreview_id,
            abstract=p.abstract, comment=p.comment,
            paper_url=p.paper_url, pdf_url=p.pdf_url,
            code_url=p.code_url, project_url=p.project_url,
        )
        if dry_run:
            candidate = PaperRecord(**fields)
            conn = repo._connect()
            try:
                is_new = repo._find_existing(conn, candidate) is None
            finally:
                conn.close()
            record = candidate
        else:
            record, is_new = repo.insert_paper_from_fields(**fields)
        if is_new:
            new_count += 1
            if dry_run:
                result = score_paper(record, config, query_stars=query_stars)
            else:
                result = score_and_persist(record, config, repo, query_stars=query_stars)
            if result.tier == "S":
                s_count += 1
            elif result.tier == "A":
                a_count += 1
    return new_count, s_count, a_count


class BackfillEngine:
    """补录调度器：编排数据源、切片、水位线与打分。"""

    def __init__(
        self,
        config: AppConfig,
        repo: PaperRepository,
        fetchers: dict[str, BaseFetcher] | None = None,
        today: date | None = None,
    ):
        self.config = config
        self.repo = repo
        self.today = today or today_date()
        self.fetchers = fetchers or self._default_fetchers()

    def _default_fetchers(self) -> dict[str, BaseFetcher]:
        fetchers: dict[str, BaseFetcher] = {}
        if self.config.sources.arxiv.enabled:
            fetchers["arxiv"] = ArxivFetcher(self.config)
        if self.config.sources.openalex.enabled:
            fetchers["openalex"] = OpenAlexFetcher(self.config)
        if self.config.sources.openreview.enabled:
            fetchers["openreview"] = OpenReviewFetcher(self.config)
        return fetchers

    def _process_slice(
        self,
        source_name: str,
        venue: str | None,
        s: date,
        e: date,
        venue_filter: list[str] | None = None,
        dry_run: bool = False,
    ) -> tuple[int, int, int]:
        fetcher = self.fetchers.get(source_name)
        if fetcher is None:
            logger.info(f"数据源 {source_name} 未启用，跳过")
            return 0, 0, 0
        papers = fetcher.fetch_by_date_range(s, e, venues=venue_filter)
        return ingest_papers(
            papers, self.repo, self.config, source_override=source_name, dry_run=dry_run,
        )

    def run_auto(self, force: bool = False, dry_run: bool = False) -> BackfillResult:
        """自动补录；dry_run 不写论文、不推进水位线。"""
        result = BackfillResult()
        # 对每个 source 使用 ALL 作为统一水位线 key（arxiv/openalex 全量扫描）
        for source_name in self.fetchers:
            start = determine_start_date(self.repo, source_name, "ALL", self.config, self.today)
            if start > self.today:
                logger.info(f"[{source_name}] 已是最新，跳过")
                continue
            start, truncated = clamp_start_date(start, self.today, self.config)
            if truncated:
                result.message += f"[{source_name}] 超过最大补录天数，已截断至 {start}; "
                logger.warning(result.message)

            slices = slice_range(start, self.today, self.config.backfill.max_slice_days)
            last_ok: date | None = None
            for s, e in slices:
                result.slices.append((s, e))
                try:
                    n, ns, na = self._process_slice(source_name, None, s, e, dry_run=dry_run)
                    result.fetched += n
                    result.new_papers += n
                    result.tier_s += ns
                    result.tier_a += na
                    last_ok = e
                    # 关键事务原则：仅整个切片成功后推进水位线
                    if not dry_run:
                        self.repo.set_watermark(source_name, "ALL", e.isoformat())
                except Exception as exc:
                    result.failed += 1
                    if not dry_run:
                        self.repo.set_watermark(
                            source_name, "ALL",
                            last_ok.isoformat() if last_ok else (start - timedelta(days=1)).isoformat(),
                            last_status="FAILED", last_error=str(exc),
                        )
                    logger.error(f"[{source_name}] 切片 {s}~{e} 失败: {exc}")
                    break  # 后续切片不跳过，留给下次续传
            if last_ok:
                result.last_success_date = last_ok.isoformat()
        return result

    def run_manual(
        self,
        start: date,
        end: date,
        venues: list[str] | None = None,
        sources: list[str] | None = None,
        dry_run: bool = False,
    ) -> BackfillResult:
        """手动补录指定区间；dry_run 不写论文、不推进水位线。"""
        result = BackfillResult()
        active_sources = [s for s in (sources or list(self.fetchers)) if s in self.fetchers]
        venue_upper = [v.upper() for v in venues] if venues else None
        slices = slice_range(start, end, self.config.backfill.max_slice_days)
        for source_name in active_sources:
            last_ok: date | None = None
            for s, e in slices:
                result.slices.append((s, e))
                try:
                    n, ns, na = self._process_slice(
                        source_name, None, s, e, venue_upper, dry_run=dry_run,
                    )
                    result.fetched += n
                    result.new_papers += n
                    result.tier_s += ns
                    result.tier_a += na
                    last_ok = e
                except Exception as exc:
                    result.failed += 1
                    logger.error(f"[{source_name}] 手动切片 {s}~{e} 失败: {exc}")
                    break
            # 仅向前推进水位线，绝不回退
            if last_ok and not dry_run:
                wm = self.repo.get_watermark(source_name, "ALL")
                if wm is None or last_ok > date.fromisoformat(wm.last_success_date):
                    self.repo.set_watermark(source_name, "ALL", last_ok.isoformat())
                    result.last_success_date = last_ok.isoformat()
        return result
