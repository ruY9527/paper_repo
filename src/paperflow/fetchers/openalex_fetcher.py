"""OpenAlex 采集器：顶刊 TPAMI/TIP/IJCV 与正式发表权威源。"""

from __future__ import annotations

from datetime import date

from ..config import AppConfig, VENUE_DISPLAY_NAMES
from ..utils.logger import get_logger
from .base import BaseFetcher, RawPaper

logger = get_logger()

_OPENALEX_WORKS = "https://api.openalex.org/works"


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """把 OpenAlex 倒排索引还原为完整英文摘要。"""
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda x: x[0])
    return " ".join(word for _, word in positions)


class OpenAlexFetcher(BaseFetcher):
    source_name = "openalex"

    def __init__(self, config: AppConfig, client=None):
        src = config.sources.openalex
        ua = f"PaperFlow2026/1.0 (mailto:{src.mailto})"
        super().__init__(rate_limit_seconds=src.rate_limit_seconds, user_agent=ua, client=client)
        self.config = config
        self.mailto = src.mailto
        # 期刊 ISSN -> venue 映射
        self._issn_to_venue: dict[str, str] = {}
        for name, vcfg in config.venues.journals.items():
            for issn in vcfg.issns:
                self._issn_to_venue[issn.lower()] = name

    def _venue_from_work(self, work: dict) -> str | None:
        loc = work.get("primary_location") or {}
        source = loc.get("source") or {}
        for issn in source.get("issn") or []:
            hit = self._issn_to_venue.get(str(issn).lower())
            if hit:
                return hit
        # 按来源显示名 + 目标年兜底匹配会议
        display = source.get("display_name", "")
        year = work.get("publication_year")
        if year != self.config.target_year:
            return None
        for name, vcfg in self.config.venues.conferences.items():
            full = vcfg.full_name.lower()
            if display and (display.lower() in full or full in display.lower()):
                return name
        return None

    @staticmethod
    def _extract_code_url(work: dict) -> str:
        locations = work.get("locations") or []
        for loc in locations:
            landing = loc.get("landing_page_url") or ""
            if "github.com" in landing.lower():
                return landing
        return ""

    def _parse_work(self, work: dict) -> RawPaper | None:
        venue = self._venue_from_work(work)
        if venue is None:
            return None
        title = (work.get("title") or work.get("display_name") or "").strip()
        if not title:
            return None
        authorships = work.get("authorships") or []
        authors = [
            a.get("author", {}).get("display_name", "") for a in authorships
        ]
        authors = [a for a in authors if a]
        affiliations: list[str] = []
        for a in authorships:
            for inst in a.get("institutions") or []:
                name = inst.get("display_name", "")
                if name and name not in affiliations:
                    affiliations.append(name)

        doi = (work.get("doi") or "").strip() or None
        if doi and doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/"):]

        oa = work.get("open_access") or {}
        best = work.get("best_oa_location") or {}
        pdf_url = best.get("pdf_url") or oa.get("oa_url") or ""
        pub_date = work.get("publication_date")
        ids = work.get("ids") or {}
        arxiv_id = None
        arxiv_doi = ids.get("doi") or ""

        return RawPaper(
            title=title,
            authors=authors,
            affiliations=affiliations,
            venue=venue,
            pub_year=int(work.get("publication_year") or self.config.target_year),
            pub_date=pub_date,
            source="openalex",
            doi=doi,
            arxiv_id=arxiv_id,
            abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
            paper_url=work.get("primary_location", {}).get("landing_page_url", "")
            or (f"https://doi.org/{doi}" if doi else ""),
            pdf_url=pdf_url,
            code_url=self._extract_code_url(work),
        )

    def fetch_by_date_range(
        self, start_date: date, end_date: date, venues: list[str] | None = None
    ) -> list[RawPaper]:
        wanted = {v.upper() for v in venues} if venues else None
        all_issns = "|".join(self._issn_to_venue.keys())
        filter_parts = [
            f"primary_location.source.issn:{all_issns}",
            f"from_publication_date:{start_date.isoformat()}",
            f"to_publication_date:{end_date.isoformat()}",
        ]
        cursor = "*"
        results: list[RawPaper] = []
        while cursor:
            params = {
                "filter": ",".join(filter_parts),
                "cursor": cursor,
                "per-page": 200,
                "mailto": self.mailto,
            }
            response = self._get(_OPENALEX_WORKS, params=params)
            if response.status_code != 200:
                logger.warning(f"[openalex] HTTP {response.status_code}, 停止")
                break
            payload = response.json()
            works = payload.get("results", [])
            if not works:
                break
            for work in works:
                parsed = self._parse_work(work)
                if parsed is None:
                    continue
                if wanted and parsed.venue not in wanted:
                    continue
                results.append(parsed)
            next_cursor = (payload.get("meta") or {}).get("next_cursor")
            cursor = next_cursor if next_cursor else ""
        logger.info(f"[openalex] {start_date}~{end_date} 命中 {len(results)} 篇")
        return results

    def fetch_topic_year(self, *, year: int, parsed_query, limit: int = 20,
                         top_venues_only: bool = False, **kwargs) -> list[RawPaper]:
        """Phase 10：按方向检索式 + 年份抓取（跨全部来源，含专业期刊）。"""
        query = parsed_query.openalex_query()
        params = {
            "filter": f"publication_year:{year}",
            "search": query,
            "sort": "publication_date:desc",
            "per-page": min(limit * 2, 200),
            "mailto": self.mailto,
        }
        try:
            response = self._get(_OPENALEX_WORKS, params=params)
        except Exception as exc:
            logger.warning(f"[openalex] topic 检索失败: {exc}")
            return []
        if response.status_code != 200:
            return []
        works = response.json().get("results", [])
        results: list[RawPaper] = []
        for work in works:
            if int(work.get("publication_year") or 0) != year:
                continue
            # 复用 _parse_work，但它对非目标 venue 返回 None；这里改为手工解析基础字段
            title = (work.get("title") or work.get("display_name") or "").strip()
            if not title:
                continue
            authorships = work.get("authorships") or []
            oa = work.get("open_access") or {}
            best = work.get("best_oa_location") or {}
            doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
            venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name", "") or "OpenAlex"
            results.append(RawPaper(
                title=title,
                authors=[a.get("author", {}).get("display_name", "") for a in authorships],
                affiliations=[i.get("display_name", "") for a in authorships
                              for i in (a.get("institutions") or []) if i.get("display_name")],
                venue=venue, pub_year=year, pub_date=work.get("publication_date"),
                source="openalex", doi=doi,
                abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
                paper_url=(work.get("primary_location") or {}).get("landing_page_url", ""),
                pdf_url=best.get("pdf_url") or oa.get("oa_url") or "",
            ))
        return results[:limit]
