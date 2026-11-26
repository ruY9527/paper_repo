"""单篇论文临时插队：paperflow add --url ... --venue ...。

- arXiv URL -> arXiv API；doi.org / 纯 DOI -> OpenAlex。
- --venue 手动覆盖，且强制标为 S 级（由调用方在入库后设置 tier='S'）。
"""

from __future__ import annotations

import re

from ..config import AppConfig
from ..pipeline.dedup import normalize_title
from ..utils.logger import get_logger
from .arxiv_fetcher import ArxivFetcher
from .base import RawPaper
from .openalex_fetcher import OpenAlexFetcher

logger = get_logger()

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s/?]+?)(?:\.pdf)?$", re.IGNORECASE)


class SinglePaperAdder:
    """把单篇 URL / DOI 解析为 RawPaper。tier 强制 S 由上层流水线处理。"""

    def __init__(self, config: AppConfig, arxiv_fetcher=None, openalex_fetcher=None):
        self.config = config
        self.arxiv = arxiv_fetcher or ArxivFetcher(config)
        self.openalex = openalex_fetcher or OpenAlexFetcher(config)

    @staticmethod
    def extract_arxiv_id(url: str) -> str | None:
        match = _ARXIV_RE.search(url.strip())
        return match.group(1) if match else None

    @staticmethod
    def extract_doi(url: str) -> str | None:
        text = url.strip()
        if text.startswith("10."):
            return text
        match = re.search(r"doi\.org/(10\.\S+)", text, re.IGNORECASE)
        return match.group(1) if match else None

    def add(self, url: str, venue: str | None = None) -> RawPaper:
        venue = venue.upper() if venue else None
        arxiv_id = self.extract_arxiv_id(url)
        if arxiv_id:
            logger.info(f"[add] 识别为 arXiv ID: {arxiv_id}")
            # 直接走 arXiv API 按 id_list 查询
            from datetime import date
            from xml.etree import ElementTree as ET

            from .arxiv_fetcher import _ARXIV_API, _ATOM_NS

            response = self.arxiv.client.get(_ARXIV_API, params={"id_list": arxiv_id})
            response.raise_for_status()
            root = ET.fromstring(response.content)
            entries = root.findall("a:entry", _ATOM_NS)
            if not entries:
                raise ValueError(f"arXiv 未找到论文: {arxiv_id}")
            parsed = self.arxiv._parse_entry(entries[0])
            # arXiv ID 查询没有日期区间，交由 venue 正则匹配 comment/journal_ref
            matched = self.arxiv._match_venue(
                parsed["comment"], parsed["journal_ref"], parsed["pub_year"]
            )
            final_venue = venue or matched or "CVPR"
            return RawPaper(
                title=parsed["title"],
                authors=parsed["authors"],
                venue=final_venue,
                pub_year=parsed["pub_year"],
                pub_date=parsed["pub_date"],
                source="manual",
                arxiv_id=parsed["arxiv_id"],
                abstract=parsed["abstract"],
                comment=parsed["comment"],
                paper_url=parsed["paper_url"],
                pdf_url=parsed["pdf_url"],
            )

        doi = self.extract_doi(url)
        if doi:
            logger.info(f"[add] 识别为 DOI: {doi}")
            response = self.openalex.client.get(
                f"https://api.openalex.org/works/https://doi.org/{doi}"
            )
            response.raise_for_status()
            work = response.json()
            parsed = self.openalex._parse_work(work)
            if parsed is None:
                # 该 DOI 非目标 venue，手动覆盖时也接受
                parsed = RawPaper(
                    title=(work.get("title") or work.get("display_name") or "").strip(),
                    authors=[a.get("author", {}).get("display_name", "")
                             for a in work.get("authorships", [])],
                    venue=venue or "CVPR",
                    pub_year=int(work.get("publication_year") or self.config.target_year),
                    pub_date=work.get("publication_date"),
                    source="manual",
                    doi=doi,
                    abstract=self.openalex.reconstruct_abstract(
                        work.get("abstract_inverted_index")
                    ),
                    paper_url=f"https://doi.org/{doi}",
                )
            if venue:
                parsed.venue = venue
                parsed.source = "manual"
            return parsed

        raise ValueError(f"无法识别的 URL / DOI: {url}")
