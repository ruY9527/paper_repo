"""arXiv 每日增量采集器（Atom XML）。

- 分类 + submittedDate 过滤，分页拉取。
- 用 config 中 9 个 venue 的 arxiv_patterns 正则匹配 comment/journal_ref。
- 未命中任何目标 venue 的普通预印本直接丢弃。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from xml.etree import ElementTree as ET

from ..config import AppConfig
from ..utils.logger import get_logger
from ..utils.timeutil import today_date
from .base import BaseFetcher, RawPaper

logger = get_logger()

_ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_PAGE_SIZE = 100


class ArxivFetcher(BaseFetcher):
    source_name = "arxiv"

    def __init__(self, config: AppConfig, client=None):
        src = config.sources.arxiv
        super().__init__(rate_limit_seconds=src.rate_limit_seconds, client=client)
        self.config = config
        self.categories = src.categories
        self.max_results = src.max_results_per_slice
        # 预编译所有 venue 正则（忽略大小写）
        self._venue_patterns: list[tuple[str, list[re.Pattern]]] = []
        for name, vcfg in config.venues.all().items():
            compiled = [re.compile(p, re.IGNORECASE) for p in vcfg.arxiv_patterns]
            if compiled:
                self._venue_patterns.append((name, compiled))

    def _build_query(self, start_date: date, end_date: date, start: int) -> dict:
        cat_clause = " OR ".join(f"cat:{c}" for c in self.categories)
        date_clause = (
            f"submittedDate:[{start_date.strftime('%Y%m%d')}0000 "
            f"TO {end_date.strftime('%Y%m%d')}2359]"
        )
        return {
            "search_query": f"({cat_clause}) AND {date_clause}",
            "start": start,
            "max_results": min(_PAGE_SIZE, self.max_results - start),
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        }

    def _match_venue(self, comment: str, journal_ref: str, pub_year: int) -> str | None:
        """返回命中的 venue 大写名，未命中返回 None。"""
        haystack = f"{comment} {journal_ref}"
        for venue_name, patterns in self._venue_patterns:
            for pat in patterns:
                if pat.search(haystack):
                    if venue_name in {"TPAMI", "TIP", "IJCV"}:
                        # 期刊：发布日期年份须为目标年
                        if pub_year != self.config.target_year:
                            continue
                    return venue_name
        return None

    @staticmethod
    def _parse_entry(entry: ET.Element) -> dict:
        def text(path: str) -> str:
            node = entry.find(path, _ATOM_NS)
            return (node.text or "").strip() if node is not None else ""

        raw_id = text("a:id")
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1] if "/abs/" in raw_id else raw_id
        title = " ".join(text("a:title").split())
        abstract = " ".join(text("a:summary").split())
        authors = [a.findtext("a:name", default="", namespaces=_ATOM_NS).strip()
                   for a in entry.findall("a:author", _ATOM_NS)]
        authors = [a for a in authors if a]

        published = text("a:published")
        pub_date = published[:10] if len(published) >= 10 else None
        pub_year = int(published[:4]) if published[:4].isdigit() else today_date().year

        comment_node = entry.find("arxiv:comment", _ATOM_NS)
        comment = (comment_node.text or "").strip() if comment_node is not None else ""
        journal_node = entry.find("arxiv:journal_ref", _ATOM_NS)
        journal_ref = (journal_node.text or "").strip() if journal_node is not None else ""

        pdf_url = ""
        for link in entry.findall("a:link", _ATOM_NS):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href", "")
                break
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        return {
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "pub_date": pub_date,
            "pub_year": pub_year,
            "comment": comment,
            "journal_ref": journal_ref,
            "paper_url": raw_id or f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_url": pdf_url,
        }

    def fetch_by_date_range(
        self, start_date: date, end_date: date, venues: list[str] | None = None
    ) -> list[RawPaper]:
        wanted = {v.upper() for v in venues} if venues else None
        results: list[RawPaper] = []
        start = 0
        while start < self.max_results:
            params = self._build_query(start_date, end_date, start)
            response = self._get(_ARXIV_API, params=params)
            if response.status_code != 200:
                logger.warning(f"[arxiv] HTTP {response.status_code}, 停止本区间拉取")
                break
            root = ET.fromstring(response.content)
            entries = root.findall("a:entry", _ATOM_NS)
            if not entries:
                break
            for entry in entries:
                parsed = self._parse_entry(entry)
                venue = self._match_venue(
                    parsed["comment"], parsed["journal_ref"], parsed["pub_year"]
                )
                if venue is None:
                    continue  # 普通预印本，丢弃
                if wanted and venue not in wanted:
                    continue
                results.append(RawPaper(
                    title=parsed["title"],
                    authors=parsed["authors"],
                    venue=venue,
                    pub_year=parsed["pub_year"],
                    pub_date=parsed["pub_date"],
                    source="arxiv",
                    arxiv_id=parsed["arxiv_id"],
                    abstract=parsed["abstract"],
                    comment=parsed["comment"],
                    paper_url=parsed["paper_url"],
                    pdf_url=parsed["pdf_url"],
                ))
            start += len(entries)
            if len(entries) < _PAGE_SIZE:
                break
        logger.info(f"[arxiv] {start_date}~{end_date} 命中目标 venue {len(results)} 篇")
        return results

    def fetch_topic_year(self, *, year: int, parsed_query, limit: int = 20,
                         top_venues_only: bool = False, **kwargs) -> list[RawPaper]:
        """Phase 10：按方向检索式 + 年份抓取（不受 9 大 venue 限制）。"""
        query = parsed_query.arxiv_query()
        date_clause = f"submittedDate:[{year}01010000 TO {year}12312359]"
        params = {
            "search_query": f"({query}) AND {date_clause}",
            "start": 0,
            "max_results": min(limit * 2, 200),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        try:
            response = self._get(_ARXIV_API, params=params)
        except Exception as exc:
            logger.warning(f"[arxiv] topic 检索失败: {exc}")
            return []
        if response.status_code != 200:
            return []
        root = ET.fromstring(response.content)
        results: list[RawPaper] = []
        for entry in root.findall("a:entry", _ATOM_NS):
            parsed = self._parse_entry(entry)
            if parsed["pub_year"] != year:
                continue
            # 保留真实 venue：命中 9 大用简称，否则 arXiv
            venue = self._match_venue(parsed["comment"], parsed["journal_ref"], parsed["pub_year"])
            if top_venues_only and not venue:
                continue
            results.append(RawPaper(
                title=parsed["title"], authors=parsed["authors"],
                venue=venue or "arXiv", pub_year=parsed["pub_year"],
                pub_date=parsed["pub_date"], source="arxiv",
                arxiv_id=parsed["arxiv_id"], abstract=parsed["abstract"],
                comment=parsed["comment"], paper_url=parsed["paper_url"],
                pdf_url=parsed["pdf_url"],
            ))
        return results[:limit]
