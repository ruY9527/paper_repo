"""S 级论文 PDF 原子下载器（03 文档第 1 节）。"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from ..config import AppConfig
from ..db.models import PaperRecord, PaperStatus, PaperTier
from ..db.repository import PaperRepository
from ..utils.logger import get_logger

logger = get_logger()

_PDF_MAGIC = b"%PDF"


def _download_one(
    paper: PaperRecord,
    target: Path,
    max_mb: int,
    client: httpx.Client | None = None,
) -> str:
    """流式下载到 .part，校验大小与文件头后 os.replace 到正式路径。

    返回状态：'ok' | 'http_error' | 'non_pdf' | 'too_large' | 'error'
    """
    if not paper.pdf_url:
        return "error"
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".pdf.part")
    own_client = client is None
    client = client or httpx.Client(
        timeout=60.0, follow_redirects=True, trust_env=False,
        headers={"User-Agent": "PaperFlow2026/1.0 (PDF download)"},
    )
    try:
        with client.stream("GET", paper.pdf_url) as resp:
            if resp.status_code != 200:
                logger.warning(f"[download] {paper.paper_uid} HTTP {resp.status_code}")
                return "http_error"
            length = resp.headers.get("Content-Length")
            if length and int(length) > max_mb * 1024 * 1024:
                logger.warning(f"[download] {paper.paper_uid} 文件过大 ({length} bytes)，跳过")
                return "too_large"
            checksum = 0
            with part.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
                    checksum += len(chunk)
                    if checksum > max_mb * 1024 * 1024:
                        f.close()
                        part.unlink(missing_ok=True)
                        logger.warning(f"[download] {paper.paper_uid} 超过大小上限，中止")
                        return "too_large"
        # 校验 PDF 文件头
        with part.open("rb") as f:
            header = f.read(4)
        if header != _PDF_MAGIC:
            part.unlink(missing_ok=True)
            logger.warning(f"[download] {paper.paper_uid} 文件头非 %PDF，疑似 HTML 页面，丢弃")
            return "non_pdf"
        os.replace(part, target)
        return "ok"
    except Exception as exc:
        part.unlink(missing_ok=True)
        logger.warning(f"[download] {paper.paper_uid} 下载失败: {exc}")
        return "error"
    finally:
        if own_client:
            client.close()


def _is_open_url(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).netloc or "").lower()
    open_domains = {"arxiv.org", "openaccess.thecvf.com", "openreview.net", "hal.science"}
    return any(host == d or host.endswith("." + d) for d in open_domains)


def download_paper(
    config: AppConfig,
    repo: PaperRepository,
    paper: PaperRecord,
    client: httpx.Client | None = None,
) -> str:
    """下载单篇 S 级论文，返回 downloaded/fallback/skipped/paywall_blocked。"""
    from urllib.parse import urlparse

    from .paywall_filter import PaywallFilter

    if paper.tier != PaperTier.S.value:
        return "skipped"
    paywall = PaywallFilter(config, repo)
    if config.download_policy.enable_paywall_filter:
        pre = paywall.filter_and_rescue(paper)
        if pre["action"] == "blocked":
            return "paywall_blocked"
        if pre["action"] == "rescued":
            paper = repo.get_paper(paper.paper_uid) or paper

    target = config.workspace_path / "tmp" / "pdfs" / f"{paper.paper_uid}.pdf"
    result = _download_one(paper, target, config.storage.max_pdf_size_mb, client)
    if result == "ok":
        repo.update_status(
            paper.paper_uid, PaperStatus.DOWNLOADED, pdf_local_path=str(target),
        )
        return "downloaded"

    if (config.download_policy.auto_classify_html_403_as_paywall
            and paper.pdf_url and not _is_open_url(paper.pdf_url)
            and result in ("http_error", "non_pdf")):
        host = (urlparse(paper.pdf_url).netloc or "").lower()
        rule = paywall.match_paywall(paper.pdf_url)
        paywall.record_blocked(
            paper, publisher=(rule.publisher if rule else "Unknown"),
            domain=(rule.domain if rule else host),
            block_reason="http_403_login_wall", blocked_pdf_url=paper.pdf_url,
            landing_url=paper.paper_url or paper.pdf_url,
        )
        return "paywall_blocked"

    logger.info(f"[download] {paper.paper_uid} Fallback to abstract-only (降为 A 级)")
    repo.update_fields(paper.paper_uid, tier=PaperTier.A.value)
    repo.update_status(paper.paper_uid, PaperStatus.SCORED)
    return "fallback"


def download_s_papers(
    config: AppConfig,
    repo: PaperRepository,
    client: httpx.Client | None = None,
) -> dict[str, int]:
    """批量复用单篇下载内核；受限命中不下载，失败降级为 A 级速览。"""
    stats = {"downloaded": 0, "fallback": 0, "skipped": 0, "paywall_blocked": 0}
    candidates = repo.get_papers_by_status(
        PaperStatus.SCORED.value, "RESCUED_ARXIV",
    )
    for paper in candidates:
        result = download_paper(config, repo, paper, client=client)
        stats[result] = stats.get(result, 0) + 1
    return stats
