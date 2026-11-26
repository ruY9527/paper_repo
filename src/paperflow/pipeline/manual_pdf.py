"""Phase 13：本地 PDF 手动补传与批量收件箱匹配。

- attach_local_pdf：严格 %PDF 校验 + 抽文本/抽图 + 升级 DOWNLOADED。
- scan_inbox_pdfs：按 UID -> DOI -> 首页标题相似度匹配。
- export_pending_checklist：导出 md/csv 待下载清单。
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
from ..utils.timeutil import now_dt
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..db.models import PaperStatus, PaperTier
from ..db.repository import PaperRepository
from ..utils.logger import get_logger

logger = get_logger()

_PDF_MAGIC = b"%PDF"
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def _validate_pdf_bytes(data: bytes, max_mb: int) -> str | None:
    if not data:
        return "文件为空"
    if data[:4] != _PDF_MAGIC:
        return "文件头非 %PDF（不是合法 PDF）"
    if len(data) > max_mb * 1024 * 1024:
        return f"文件超过大小上限（{max_mb}MB）"
    return None


def attach_local_pdf(config: AppConfig, repo: PaperRepository,
                     paper_uid: str, pdf_bytes: bytes) -> dict[str, Any]:
    """单篇手动补传：校验 -> 原子写 -> 抽文本/抽图 -> 升级账本。"""
    err = _validate_pdf_bytes(pdf_bytes, config.storage.max_pdf_size_mb)
    if err:
        raise ValueError(err)

    paper = repo.get_paper(paper_uid)
    if paper is None:
        raise FileNotFoundError(f"论文不存在: {paper_uid}")

    target = config.workspace_path / "tmp" / "pdfs" / f"{paper_uid}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".pdf.part")
    part.write_bytes(pdf_bytes)
    part.replace(target)

    # 抽文本与架构图
    from .extractor import extract_clean_text, extract_figures
    text = extract_clean_text(target)
    figures = extract_figures(
        target, config.workspace_path / "staging" / "assets" / paper_uid,
        paper_uid, config,
    )

    # 更新 papers
    repo.update_fields(
        paper_uid, tier=PaperTier.S.value, access_type="manual_uploaded",
        pdf_local_path=str(target), pdf_deleted=0,
    )
    repo.update_status(paper_uid, PaperStatus.DOWNLOADED, pdf_local_path=str(target))

    # 更新 paywall_papers
    pw = repo.get_paywall_paper(paper_uid)
    if pw:
        repo.update_paywall_paper(paper_uid, manual_status="PDF_UPLOADED")

    from .queue_exporter import export_paper_to_queue
    paper = repo.get_paper(paper_uid)
    export_paper_to_queue(config, repo, paper, paper.fetch_date or None)
    queue_dir = (config.workspace_path / "queue"
                 / (paper.fetch_date or now_dt().date().isoformat()) / paper_uid)

    logger.info(f"[manual_pdf] 补传成功: {paper_uid}（文本 {len(text)} 字符，图 {len(figures)} 张）")
    return {
        "ok": True, "paper_uid": paper_uid,
        "text_chars": len(text), "figures": len(figures),
        "status": PaperStatus.QUEUED.value, "queue_dir": str(queue_dir),
    }


def _extract_pdf_meta(pdf_path: Path) -> dict[str, str]:
    """用 PyMuPDF 读首页文本，提取 DOI 与前 500 字符。"""
    import fitz
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        text = page.get_text("text") or ""
        doi_match = _DOI_RE.search(text)
        return {"doi": doi_match.group(0) if doi_match else "",
                "head": text[:500]}
    finally:
        doc.close()


def scan_inbox_pdfs(config: AppConfig, repo: PaperRepository) -> dict[str, Any]:
    """扫描 inbox_pdfs 自动匹配 paywall PENDING_MANUAL 论文。"""
    from .dedup import normalize_title

    inbox = config.inbox_pdfs_path
    if not inbox.exists():
        return {"matched": 0, "unmatched": 0, "report": []}

    pending = [p for p in repo.get_paywall_papers(manual_status="PENDING_MANUAL")]
    # 预建查找索引
    by_uid = {p["paper_uid"]: p for p in pending}
    by_doi = {}
    by_title = []
    for p in pending:
        if p.get("doi"):
            by_doi[p["doi"].lower()] = p
        by_title.append(p)

    matched = 0
    report: list[dict] = []
    pdfs = sorted(inbox.glob("*.pdf"))
    for pdf_path in pdfs:
        target_uid = None
        filename = pdf_path.stem
        # 1) 文件名含 paper_uid
        if filename in by_uid:
            target_uid = filename
        else:
            try:
                meta = _extract_pdf_meta(pdf_path)
            except Exception:
                meta = {"doi": "", "head": ""}
            # 2) DOI 匹配
            if meta["doi"] and meta["doi"].lower() in by_doi:
                target_uid = by_doi[meta["doi"].lower()]["paper_uid"]
            # 3) 首页标题相似度
            if target_uid is None and meta["head"]:
                norm_head = normalize_title(meta["head"])
                best = None
                for p in by_title:
                    sim = _similarity(norm_head, normalize_title(p["title"]))
                    if sim >= 0.85 and (best is None or sim > best[0]):
                        best = (sim, p["paper_uid"])
                if best:
                    target_uid = best[1]

        if target_uid:
            try:
                attach_local_pdf(config, repo, target_uid, pdf_path.read_bytes())
                # 移走原文件防止重复扫描
                processed_dir = inbox / "_processed"
                processed_dir.mkdir(exist_ok=True)
                shutil.move(str(pdf_path), str(processed_dir / pdf_path.name))
                matched += 1
                report.append({"file": pdf_path.name, "paper_uid": target_uid, "status": "matched"})
            except Exception as exc:
                report.append({"file": pdf_path.name, "paper_uid": target_uid, "status": f"error: {exc}"})
        else:
            report.append({"file": pdf_path.name, "paper_uid": "", "status": "unmatched"})

    return {"matched": matched, "unmatched": len(pdfs) - matched, "report": report}


def _similarity(a: str, b: str) -> float:
    """简单子串 + 长度比例相似度。"""
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    # 简易 Jaccard on bigrams
    def bigrams(s):
        return {s[i:i+2] for i in range(max(0, len(s)-1))}
    sa, sb = bigrams(a), bigrams(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def export_pending_checklist(config: AppConfig, repo: PaperRepository,
                             fmt: str = "markdown") -> tuple[str, str]:
    """导出待下载清单，返回 (content, suggested_filename)。"""
    pending = repo.get_paywall_papers(manual_status="PENDING_MANUAL")
    date_str = now_dt().strftime("%Y%m%d")
    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["paper_uid", "title", "venue", "pub_year", "publisher", "landing_url", "doi"])
        for p in pending:
            w.writerow([p["paper_uid"], p["title"], p["venue"], p["pub_year"],
                        p["publisher"], p.get("landing_url", ""), p.get("doi", "")])
        return out.getvalue(), f"paywall_checklist_{date_str}.csv"

    lines = [f"# 待下载论文清单（{len(pending)} 篇）", "",
             "| 建议文件名 | 标题 | Venue | 年份 | 出版商 | 官网/DOI 链接 |",
             "| :--- | :--- | :--- | :--- | :--- | :--- |"]
    for p in pending:
        link = p.get("landing_url") or (f"https://doi.org/{p['doi']}" if p.get("doi") else "")
        lines.append(
            f"| `{p['paper_uid']}.pdf` | {p['title']} | {p['venue']} | {p['pub_year']} "
            f"| {p['publisher']} | {('[' + '链接' + '](' + link + ')') if link else '—'} |"
        )
    return "\n".join(lines) + "\n", f"paywall_checklist_{date_str}.md"
