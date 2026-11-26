"""Phase 13：受限出版商域名过滤与 OA 抢救服务。

- match_paywall：urlparse 提取 netloc，精确 + 后缀子域名匹配。
- filter_and_rescue：下载前拦截 + arXiv 精确同名抢救 + 幂等登记 paywall_papers。
- record_blocked：动态兜底（403/HTML 登录墙）登记。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ..config import AppConfig
from ..db.repository import PaperRepository
from ..pipeline.dedup import normalize_title
from ..utils.logger import get_logger

logger = get_logger()

_ARXIV_API = "https://export.arxiv.org/api/query"
_ARXIV_NS = {"a": "http://www.w3.org/2005/Atom"}

# 开放获取白名单域（命中即放行，绝不拦截）
_OPEN_DOMAINS = {
    "arxiv.org", "openaccess.thecvf.com", "openreview.net", "hal.science",
    "openaccess.thecvf.com", "proceedings.mlr.press", "papers.nips.cc",
    "biorxiv.org", "medrxiv.org", "arxiv.org",
}


@dataclass
class PaywallRule:
    domain: str
    publisher: str
    note: str = ""


class PaywallFilter:
    def __init__(self, config: AppConfig, repo: PaperRepository):
        self.config = config
        self.repo = repo
        self._last_arxiv_call = 0.0

    # ---- 域名匹配 ----

    def match_paywall(self, url: str) -> PaywallRule | None:
        if not url:
            return None
        host = (urlparse(url).netloc or "").lower().strip()
        if not host:
            return None
        for rule in self.config.download_policy.paywall_domains:
            domain = rule.domain.lower().strip().lstrip("*.")
            if host == domain or host.endswith("." + domain):
                return PaywallRule(domain=domain, publisher=rule.publisher, note=rule.note)
        return None

    def _is_open_domain(self, url: str) -> bool:
        host = (urlparse(url).netloc or "").lower().strip()
        return any(host == d or host.endswith("." + d) for d in _OPEN_DOMAINS)

    # ---- OA 抢救（arXiv 精确同名）----

    def _arxiv_rescue(self, paper) -> tuple[str, str] | None:
        """按标题精确匹配 arXiv 开放预印本，返回 (arxiv_id, pdf_url) 或 None。"""
        from xml.etree import ElementTree as ET

        import httpx
        now = time.monotonic()
        wait = 3.0 - (now - self._last_arxiv_call)
        if wait > 0:
            time.sleep(wait)
        self._last_arxiv_call = time.monotonic()

        query = f'ti:"{paper.title.strip()}"'
        try:
            resp = httpx.get(
                _ARXIV_API,
                params={"search_query": query, "max_results": 5},
                timeout=20, trust_env=False,
                headers={"User-Agent": "PaperFlow2026/1.0"},
            )
        except Exception as exc:
            logger.warning(f"[paywall] arXiv 抢救查询失败: {exc}")
            return None
        if resp.status_code != 200:
            return None
        root = ET.fromstring(resp.content)
        target = normalize_title(paper.title)
        for entry in root.findall("a:entry", _ARXIV_NS):
            id_node = entry.find("a:id", _ARXIV_NS)
            title_node = entry.find("a:title", _ARXIV_NS)
            if id_node is None or title_node is None:
                continue
            raw_id = (id_node.text or "").strip()
            arxiv_id = raw_id.rsplit("/abs/", 1)[-1]
            candidate_title = " ".join((title_node.text or "").split())
            if normalize_title(candidate_title) == target:
                # 精确同名，认领
                return arxiv_id, f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        return None

    # ---- 主入口：下载前过滤 + 抢救 ----

    def filter_and_rescue(self, paper) -> dict[str, Any]:
        """返回 action 结果：
        {"action": "allow" | "blocked" | "rescued", ...}
        blocked/rescued 会登记或回填。
        """
        policy = self.config.download_policy
        if not policy.enable_paywall_filter:
            return {"action": "allow"}

        pdf_url = getattr(paper, "pdf_url", "") or ""
        paper_url = getattr(paper, "paper_url", "") or ""

        # 1) 自带 arxiv_id -> 直接放行（抢救已完成）
        if getattr(paper, "arxiv_id", ""):
            return {"action": "allow"}

        # 2) pdf_url 指向开放域 -> 放行
        if pdf_url and self._is_open_domain(pdf_url):
            return {"action": "allow"}

        # 3) 命中受限域名（pdf_url 或 paper_url）
        rule = self.match_paywall(pdf_url) or self.match_paywall(paper_url)
        if rule is None:
            return {"action": "allow"}  # 未命中名单，交给 downloader 动态兜底

        # 命中受限：先尝试 arXiv 抢救
        if policy.auto_try_arxiv_rescue:
            rescued = self._arxiv_rescue(paper)
            if rescued:
                arxiv_id, new_pdf = rescued
                self.repo.update_status(
                    paper.paper_uid, "RESCUED_ARXIV", arxiv_id=arxiv_id,
                    pdf_url=new_pdf, access_type="open",
                )
                logger.info(f"[Paywall] OA Rescue succeeded via arXiv: {paper.title} -> {arxiv_id}")
                return {"action": "rescued", "arxiv_id": arxiv_id, "pdf_url": new_pdf}

        # 无开放镜像 -> 拦截登记
        self.record_blocked(
            paper, publisher=rule.publisher, domain=rule.domain,
            block_reason="domain_blacklist", blocked_pdf_url=pdf_url,
            landing_url=paper_url or pdf_url,
        )
        return {"action": "blocked", "publisher": rule.publisher, "domain": rule.domain}

    # ---- 登记（幂等）----

    def record_blocked(self, paper, *, publisher: str, domain: str,
                       block_reason: str, blocked_pdf_url: str = "",
                       landing_url: str = "") -> None:
        """更新 papers.access_type + 幂等写入 paywall_papers，绝不标 FAILED。"""
        self.repo.update_fields(paper.paper_uid, access_type="paywall_blocked")
        self.repo.add_paywall_paper(
            paper_uid=paper.paper_uid,
            title=paper.title,
            venue=paper.venue,
            pub_year=paper.pub_year,
            tier=paper.tier,
            publisher=publisher or "Unknown",
            domain=domain,
            landing_url=landing_url,
            blocked_pdf_url=blocked_pdf_url,
            doi=paper.doi or "",
            block_reason=block_reason,
        )
        logger.info(
            f"[Paywall Filter] 跳过需登录下载 ({publisher}): {paper.title} -> 已登记至受限论文清单"
        )
