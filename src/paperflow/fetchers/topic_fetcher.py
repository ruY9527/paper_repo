"""Phase 10：方向精准检索调度器（07 文档第 3.2 节）。

核心：两年时效优先（2026 填满配额，不足才用 2025 补齐，<=2024 硬过滤），
Topic 模式豁免全局 exclude_keywords，合并追加 topic_tags 而不破坏既有记录。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from ..config import AppConfig
from ..db.models import PaperRecord, PaperStatus, PaperTier
from ..db.repository import PaperRepository
from ..pipeline.dedup import generate_paper_uid, normalize_title
from ..pipeline.scorer import sniff_code_links
from ..pipeline.topic_query import (
    ParsedTopicQuery,
    compute_topic_relevance,
    is_fully_matched,
    parse_topic_query,
)
from ..utils.logger import get_logger
from ..utils.timeutil import today_date
from .base import RawPaper

logger = get_logger()

# 数据源拉取回调：kwargs 含 year, parsed_query, limit, top_venues_only, cancel_event
FetchFn = Callable[..., list[RawPaper]]


@dataclass
class TopicSearchResult:
    topic_name: str
    raw_query: str
    expanded_query: str
    papers: list[PaperRecord] = field(default_factory=list)
    relevance: dict[str, float] = field(default_factory=dict)
    primary_count: int = 0
    fallback_count: int = 0
    filtered_old_count: int = 0
    relaxed_match_count: int = 0
    new_inserted_count: int = 0
    primary_year: int = 2026
    fallback_year: int = 2025
    status: str = "SUCCESS"


def _paper_year(paper: RawPaper | PaperRecord) -> int:
    return int(getattr(paper, "pub_year", 0) or 0)


def _default_fetch(config: AppConfig, source: str):
    """按 source 返回对应采集器实例（复用现有 fetchers）。"""
    if source == "arxiv":
        from .arxiv_fetcher import ArxivFetcher
        return ArxivFetcher(config)
    if source == "openalex":
        from .openalex_fetcher import OpenAlexFetcher
        return OpenAlexFetcher(config)
    from .openreview_fetcher import OpenReviewFetcher
    return OpenReviewFetcher(config)


class TopicSearchEngine:
    """方向检索引擎：解析查询 -> 两阶段拉取 -> 时效排序 -> 入库。"""

    def __init__(
        self,
        config: AppConfig,
        repo: PaperRepository,
        fetch_fns: dict[str, FetchFn] | None = None,
    ):
        self.config = config
        self.repo = repo
        self.primary_year = config.primary_year
        self.fallback_year = config.fallback_year
        self.min_year = config.min_allowed_year
        self._fetch_fns = fetch_fns or {}
        self._owned: list = []  # 默认创建的 fetcher，用后关闭

    # ---- 拉取 ----

    def _fetch_year(
        self,
        sources: list[str],
        year: int,
        parsed: ParsedTopicQuery,
        limit: int,
        top_venues_only: bool,
        cancel_event=None,
    ) -> list[RawPaper]:
        """从各数据源拉取指定年份的候选（不做年份过滤，由调用方统一过滤）。"""
        results: list[RawPaper] = []
        for source in sources:
            if cancel_event is not None and cancel_event.is_set():
                break
            try:
                if source in self._fetch_fns:
                    papers = self._fetch_fns[source](
                        year=year, parsed_query=parsed, limit=limit,
                        top_venues_only=top_venues_only, cancel_event=cancel_event,
                    )
                else:
                    fetcher = _default_fetch(self.config, source)
                    self._owned.append(fetcher)
                    papers = fetcher.fetch_topic_year(
                        year=year, parsed_query=parsed, limit=limit,
                        top_venues_only=top_venues_only,
                    )
                results.extend(papers or [])
            except Exception as exc:
                logger.warning(f"[topic_fetcher] {source} {year} 拉取失败: {exc}")
        # 多源去重：同一论文可能被 arXiv 与 OpenAlex 同时返回
        deduped: list[RawPaper] = []
        seen: set[str] = set()
        for paper in results:
            uid = generate_paper_uid(
                doi=paper.doi, arxiv_id=paper.arxiv_id,
                openreview_id=paper.openreview_id, title=paper.title,
            )
            if uid in seen:
                continue
            seen.add(uid)
            deduped.append(paper)
        return deduped

    # ---- 主流程 ----

    def search(
        self,
        raw_query: str,
        *,
        topic_name: str | None = None,
        limit: int | None = None,
        only_primary_year: bool = False,
        top_venues_only: bool = False,
        sources: list[str] | None = None,
        auto_download: bool = False,
        progress_cb: Callable[..., None] | None = None,
        cancel_event=None,
    ) -> TopicSearchResult:
        limit = limit or self.config.topic_search.default_limit_per_topic
        sources = sources or ["arxiv", "openalex"]
        # 中文方向词翻译：首次走免费 API 并缓存，后续命中缓存零网络
        from ..pipeline.topic_translator import load_cache, save_cache, translate_term
        _zh_cache = load_cache(self.config)
        _cache_before = dict(_zh_cache)
        def _translate(term: str) -> str:
            # translate_term 命中缓存或不需翻译时不改字典；新翻译会写入 _zh_cache
            return translate_term(term, self.config, cache=_zh_cache)
        parsed = parse_topic_query(raw_query, self.config, translate_fn=_translate)
        if _zh_cache != _cache_before:
            save_cache(self.config, _zh_cache)  # 首次翻译结果持久化，第二次直接用

        def emit(stage: str, message: str, **kw):
            if progress_cb:
                progress_cb(stage=stage, message=message, **kw)

        result = TopicSearchResult(
            topic_name=topic_name or raw_query,
            raw_query=raw_query,
            expanded_query=parsed.expanded_text(),
            primary_year=self.primary_year,
            fallback_year=self.fallback_year,
        )

        # Stage A：2026
        emit("fetching_primary", f"正在检索 {self.primary_year} 年论文", current=0, total=limit)
        primary_candidates = self._fetch_year(
            sources, self.primary_year, parsed, limit, top_venues_only, cancel_event
        )
        # 严格过滤：非 primary_year 一律不进入 primary 池
        primary = [p for p in primary_candidates if _paper_year(p) == self.primary_year]
        # <= min_year 的脏数据统计（2024 及更早）
        result.filtered_old_count += sum(
            1 for p in primary_candidates if _paper_year(p) < self.min_year
        )
        primary.sort(key=lambda p: (-compute_topic_relevance(p, parsed), p.pub_date or ""), reverse=False)
        primary = primary[:limit]
        emit(
            "primary_done",
            f"{self.primary_year} 命中 {len(primary)} 篇" + (
                "，不足配额，自动启动兜底补齐…" if len(primary) < limit and not only_primary_year else ""
            ),
            current=len(primary), total=limit,
        )

        selected: list[RawPaper] = list(primary)
        result.primary_count = len(primary)

        # Stage B：仅当 2026 不足且允许兜底
        if len(primary) < limit and not only_primary_year:
            need = limit - len(primary)
            if cancel_event is not None and cancel_event.is_set():
                pass
            else:
                emit("fetching_fallback", f"{self.fallback_year} 兜底检索（计划补齐 {need} 篇）",
                     current=len(primary), total=limit)
                fallback_candidates = self._fetch_year(
                    sources, self.fallback_year, parsed, need, top_venues_only, cancel_event
                )
                # 严格只保留 fallback_year；<=2024 硬性丢弃并计数
                fallback = []
                for p in fallback_candidates:
                    y = _paper_year(p)
                    if y < self.min_year:
                        result.filtered_old_count += 1
                    elif y == self.fallback_year:
                        fallback.append(p)
                fallback.sort(
                    key=lambda p: (-compute_topic_relevance(p, parsed), p.pub_date or ""),
                    reverse=False,
                )
                fallback = fallback[:need]
                selected.extend(fallback)
                result.fallback_count = len(fallback)

        # 综合排序：2026 绝对置顶，其次相关性，其次日期
        selected.sort(
            key=lambda p: (
                _paper_year(p) == self.primary_year,
                compute_topic_relevance(p, parsed),
                p.pub_date or "",
            ),
            reverse=True,
        )
        selected = selected[:limit]
        result.papers = [self._to_record(p, parsed, result) for p in selected]

        # 入库（合并追加 topic_tags，豁免 exclude_keywords）
        emit("ingesting", f"入库 {len(result.papers)} 篇论文", current=len(result.papers), total=len(result.papers))
        result.new_inserted_count = self.ingest(result)
        emit("done", f"检索完成：{self.primary_year} {result.primary_count} 篇 / "
                     f"{self.fallback_year} {result.fallback_count} 篇 / 过滤老论文 {result.filtered_old_count} 篇")

        # 方向检索后自动下载 S 级 PDF（与手动补录流程打通）
        if auto_download:
            self._download_s_papers(emit)

        self.close()
        return result

    def _download_s_papers(self, emit) -> None:
        """下载 S 级 PDF 并自动导出分析队列，打通「检索→下载→AI解析」闭环。"""
        from ..pipeline.downloader import download_s_papers
        from ..pipeline.queue_exporter import export_queue
        emit("downloading_pdf", "下载 S 级 PDF")
        dl = download_s_papers(self.config, self.repo)
        emit("downloaded_pdf", f"PDF 下载 {dl.get('downloaded', 0)} 篇，受限 {dl.get('paywall_blocked', 0)} 篇，降级 {dl.get('fallback', 0)} 篇")
        # 闭环关键：下载后自动导出队列（DOWNLOADED/SCORED → QUEUED），
        # 否则论文停在 DOWNLOADED，AI 解析中心虽能看到但用户常误以为「没下载/没法解析」。
        exp = export_queue(self.config, self.repo)
        emit("exported_queue", f"已导出分析队列 {exp.get('exported', exp.get('count', 0))} 篇，可直接到 AI 解析中心解析")

    # ---- 转换与入库 ----

    def _to_record(self, paper: RawPaper, parsed: ParsedTopicQuery, result: TopicSearchResult) -> PaperRecord:
        """把 RawPaper 转为 PaperRecord，设置 topic 模式与年度时效加分。"""
        relevance = compute_topic_relevance(paper, parsed)
        result.relevance[paper.title] = relevance
        if len(parsed.groups) >= 2 and not is_fully_matched(paper, parsed):
            result.relaxed_match_count += 1

        year = _paper_year(paper)
        recency_bonus = (
            self.config.topic_search.recency_policy.primary_year_bonus
            if year == self.primary_year else 0.0
        )
        # Topic 模式豁免全局 exclude_keywords：不应用 -50 扣分，改由相关性驱动分数
        score = relevance + recency_bonus
        # 命中 9 大 venue 给额外加分（保留真实 venue 名称）
        top_venue = paper.venue.upper() in {
            "TPAMI", "TIP", "IJCV", "CVPR", "ECCV", "ICCV", "NEURIPS", "ICLR", "AAAI"
        }
        if top_venue:
            score += 15.0
        if paper.code_url:
            score += 15.0

        venue = paper.venue if paper.venue else "arXiv"
        return PaperRecord(
            paper_uid=generate_paper_uid(
                doi=paper.doi, arxiv_id=paper.arxiv_id,
                openreview_id=paper.openreview_id, title=paper.title,
            ),
            title=paper.title,
            normalized_title=normalize_title(paper.title),
            authors_json=json.dumps(paper.authors, ensure_ascii=False),
            affiliations_json=json.dumps(paper.affiliations, ensure_ascii=False),
            venue=venue,
            pub_year=year,
            pub_date=paper.pub_date,
            fetch_date=today_date().isoformat(),
            source=paper.source or "arxiv",
            doi=paper.doi, arxiv_id=paper.arxiv_id, openreview_id=paper.openreview_id,
            abstract=paper.abstract, comment=paper.comment,
            paper_url=paper.paper_url, pdf_url=paper.pdf_url,
            code_url=paper.code_url, project_url=paper.project_url,
            score=round(score, 2),
            tier=PaperTier.S.value if score >= self.config.interest_profile.thresholds.tier_s else PaperTier.A.value,
            matched_tags_json=json.dumps([g.raw for g in parsed.groups], ensure_ascii=False),
            status=PaperStatus.SCORED.value,
            discovery_mode="topic",
            topic_tags_json=json.dumps([result.topic_name], ensure_ascii=False),
        )

    def ingest(self, result: TopicSearchResult) -> int:
        """入库并合并 topic_tags；已存在论文只追加标签，不覆盖状态/分析记录。"""
        inserted = 0
        promoted = 0
        auto_n = self.config.topic_search.auto_promote_top_n_to_s
        primary_seen = 0

        for record in result.papers:
            existing = (
                self.repo.get_paper(record.paper_uid)
                or self._find_existing_legacy(record)
            )
            if existing is not None:
                # 合并追加方向标签，不触碰生命周期字段
                tags = []
                try:
                    tags = json.loads(existing.topic_tags_json or "[]")
                except json.JSONDecodeError:
                    tags = []
                if result.topic_name not in tags:
                    tags.append(result.topic_name)
                    self.repo.update_fields(
                        existing.paper_uid,
                        topic_tags_json=json.dumps(tags, ensure_ascii=False),
                        discovery_mode="topic" if existing.discovery_mode == "venue" else existing.discovery_mode,
                    )
                continue

            # 自动提升前 N 篇 2026 论文为 S 级
            if auto_n > 0 and record.pub_year == self.primary_year and primary_seen < auto_n:
                record.tier = PaperTier.S.value
                record.score = max(record.score, self.config.interest_profile.thresholds.tier_s)
                promoted += 1
            if record.pub_year == self.primary_year:
                primary_seen += 1

            _, is_new = self.repo.upsert_paper(record)
            if is_new:
                inserted += 1

        logger.info(
            f"[topic_fetcher] {result.topic_name} 入库 {inserted} 篇，"
            f"自动提升 S 级 {promoted} 篇，过滤老论文 {result.filtered_old_count} 篇"
        )
        return inserted

    def _find_existing_legacy(self, record: PaperRecord) -> PaperRecord | None:
        """按 DOI / arxiv / 标题查已存在记录（兼容 upsert 的匹配逻辑）。"""
        if record.doi:
            row = self.repo._connect().execute(
                "SELECT paper_uid FROM papers WHERE doi = ?", (record.doi,)
            ).fetchone()
            if row:
                return self.repo.get_paper(row["paper_uid"])
        if record.arxiv_id:
            row = self.repo._connect().execute(
                "SELECT paper_uid FROM papers WHERE arxiv_id = ?", (record.arxiv_id,)
            ).fetchone()
            if row:
                return self.repo.get_paper(row["paper_uid"])
        row = self.repo._connect().execute(
            "SELECT paper_uid FROM papers WHERE normalized_title = ?",
            (record.normalized_title,),
        ).fetchone()
        return self.repo.get_paper(row["paper_uid"]) if row else None

    def close(self) -> None:
        for fetcher in self._owned:
            try:
                fetcher.close()
            except Exception:
                pass
        self._owned.clear()
