"""OpenReview 采集器：ICLR / NeurIPS 一手源，未放榜时优雅降级。"""

from __future__ import annotations

import re
from datetime import date

from ..config import VENUE_DISPLAY_NAMES
from ..utils.logger import get_logger
from .base import BaseFetcher, RawPaper

logger = get_logger()

_OPENREVIEW_NOTES = "https://api2.openreview.net/notes"

# 录用状态白名单；Rejected / Withdrawn 一律跳过
_ACCEPTED_RE = re.compile(r"accept|poster|oral|spotlight", re.IGNORECASE)
_REJECTED_RE = re.compile(r"reject|withdraw|desk.?reject", re.IGNORECASE)


class OpenReviewFetcher(BaseFetcher):
    source_name = "openreview"

    def __init__(self, config: AppConfig, client=None):
        src = config.sources.openreview
        super().__init__(rate_limit_seconds=src.rate_limit_seconds, client=client)
        self.config = config
        # venue_id -> 标准 venue 名
        self._venue_by_id: dict[str, str] = {}
        for name, vcfg in config.venues.conferences.items():
            if vcfg.openreview_venue_id:
                self._venue_by_id[vcfg.openreview_venue_id] = name

    @staticmethod
    def _content_value(content: dict, key: str) -> str:
        """OpenReview API v2 的 content 字段形如 {'venue': {'value': '...'}}。"""
        val = content.get(key, "")
        if isinstance(val, dict):
            return str(val.get("value", ""))
        return str(val) if val is not None else ""

    def _parse_note(self, note: dict, venue: str) -> RawPaper | None:
        content = note.get("content") or {}
        venue_str = self._content_value(content, "venue")
        venue_id = self._content_value(content, "venueid")
        combined = f"{venue_str} {venue_id}"
        if _REJECTED_RE.search(combined):
            return None
        title = self._content_value(content, "title").strip()
        if not title:
            return None
        if not _ACCEPTED_RE.search(combined):
            # 未明确录用标记时，仅凭 venue_id 命中也算一手源记录
            if not venue_id:
                return None

        authors_raw = content.get("authors", {})
        if isinstance(authors_raw, dict):
            authors_raw = authors_raw.get("value", [])
        authors = [str(a) for a in (authors_raw or []) if a]

        abstract = self._content_value(content, "abstract")
        comment_parts = [venue_str]
        if re.search(r"oral", venue_str, re.IGNORECASE):
            comment_parts.append("Oral")
        if re.search(r"spotlight", venue_str, re.IGNORECASE):
            comment_parts.append("Spotlight")

        forum = note.get("forum") or note.get("id") or ""
        paper_url = f"https://openreview.net/forum?id={forum}" if forum else ""
        return RawPaper(
            title=title,
            authors=authors,
            venue=venue,
            pub_year=self.config.target_year,
            pub_date=date.fromtimestamp(note.get("tcdate", 0) / 1000).isoformat()
            if note.get("tcdate") else None,
            source="openreview",
            openreview_id=forum or None,
            abstract=abstract,
            comment=" | ".join(p for p in comment_parts if p),
            paper_url=paper_url,
        )

    def fetch_by_date_range(
        self, start_date: date, end_date: date, venues: list[str] | None = None
    ) -> list[RawPaper]:
        wanted = {v.upper() for v in venues} if venues else None
        results: list[RawPaper] = []
        for venue_id, venue in self._venue_by_id.items():
            if wanted and venue not in wanted:
                continue
            params = {"content.venueid": venue_id, "limit": 1000}
            try:
                response = self._get(_OPENREVIEW_NOTES, params=params)
            except Exception as exc:  # 优雅降级：任何异常均不阻塞其他源
                logger.info(f"[openreview] {venue_id} 暂不可用，降级跳过: {exc}")
                continue
            if response.status_code in (404, 400):
                logger.info(f"[openreview] {venue_id} 尚未放榜（HTTP {response.status_code}），降级跳过")
                continue
            if response.status_code != 200:
                logger.info(f"[openreview] {venue_id} HTTP {response.status_code}，降级跳过")
                continue
            notes = response.json().get("notes", [])
            for note in notes:
                parsed = self._parse_note(note, venue)
                if parsed:
                    results.append(parsed)
        logger.info(f"[openreview] {start_date}~{end_date} 命中 {len(results)} 篇")
        return results
