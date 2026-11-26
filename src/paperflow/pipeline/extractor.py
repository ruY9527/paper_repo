"""PDF 干净文本提取 + 核心架构图 WebP 压缩（03 文档第 2 节）。"""

from __future__ import annotations

import io
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from ..config import AppConfig
from ..db.models import PaperRecord
from ..utils.logger import get_logger

logger = get_logger()

_REFERENCES_RE = __import__("re").compile(r"^\s*(references|references\s+and\s+notes|bibliography)\s*$", __import__("re").IGNORECASE)


def extract_clean_text(pdf_path: str | Path) -> str:
    """逐页提取文本，标注页码，References 行之后截断。"""
    doc = fitz.open(str(pdf_path))
    chunks: list[str] = []
    try:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text")
            lines = text.splitlines()
            cleaned: list[str] = []
            prev_blank = False
            page_header = f"--- PAGE {i} ---"
            truncated = False
            for line in lines:
                stripped = line.strip()
                if _REFERENCES_RE.match(stripped):
                    truncated = True  # 截断，不含 References 行
                    break
                if stripped == "":
                    if prev_blank:
                        continue
                    prev_blank = True
                else:
                    prev_blank = False
                cleaned.append(stripped)
            # 即使本页中途被截断，也保留本页已有的正文（含页眉）
            chunks.append(page_header + "\n" + "\n".join(cleaned))
            if truncated:
                break
        return "\n\n".join(chunks)
    finally:
        doc.close()


def extract_figures(
    pdf_path: str | Path,
    out_dir: str | Path,
    paper_uid: str,
    config: AppConfig,
) -> list[str]:
    """扫描前 4 页内嵌图片，筛选大图并压缩为 WebP。

    返回生成的文件路径列表；纯矢量 PDF 无内嵌图时返回 []（不报错）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    storage = config.storage
    if not storage.extract_figures:
        return []

    doc = fitz.open(str(pdf_path))
    candidates: list[tuple[int, int, int]] = []  # (area, page_idx, xref)
    seen_xrefs: set[int] = set()
    try:
        for page_idx in range(min(4, len(doc))):
            page = doc[page_idx]
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                w, h = img[2], img[3]
                if w < 400 or h < 200:
                    continue
                ratio = w / h if h else 0
                if not (0.3 <= ratio <= 5.0):
                    continue
                candidates.append((w * h, page_idx, xref))
    finally:
        # 不在 finally 关闭：需要继续提取 pixmap
        pass

    if not candidates:
        doc.close()
        logger.info(f"[extractor] {paper_uid} 未找到符合条件的嵌入图，跳过抽图")
        return []

    candidates.sort(reverse=True)
    chosen = candidates[: storage.max_figures_per_paper]
    outputs: list[str] = []
    try:
        for n, (_, _, xref) in enumerate(chosen, start=1):
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha >= 4:  # CMYK -> RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                if img.width > storage.figure_max_width_px:
                    scale = storage.figure_max_width_px / img.width
                    img = img.resize(
                        (storage.figure_max_width_px, int(img.height * scale)),
                        Image.LANCZOS,
                    )
                out_path = out_dir / f"fig_{n}.webp"
                img.save(out_path, format="WEBP", quality=storage.figure_webp_quality)
                outputs.append(str(out_path))
            except Exception as exc:
                logger.warning(f"[extractor] {paper_uid} 第 {n} 张图提取失败: {exc}")
    finally:
        doc.close()
    logger.info(f"[extractor] {paper_uid} 抽取 {len(outputs)} 张 WebP 架构图")
    return outputs


def extract_for_paper(
    paper: PaperRecord,
    config: AppConfig,
    queue_dir: str | Path,
) -> dict:
    """对单篇论文执行完整抽取：文本写入 queue_dir/extracted_text.md，图写入 staging assets。"""
    result = {"text_path": "", "figures": []}
    if not paper.pdf_local_path or not Path(paper.pdf_local_path).exists():
        # A 级无 PDF：仅 Title + Abstract
        text = f"# {paper.title}\n\n{paper.abstract}"
        text_path = Path(queue_dir) / "extracted_text.md"
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(text, encoding="utf-8")
        result["text_path"] = str(text_path)
        return result

    text = extract_clean_text(paper.pdf_local_path)
    text_path = Path(queue_dir) / "extracted_text.md"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text, encoding="utf-8")
    result["text_path"] = str(text_path)

    assets_dir = config.workspace_path / "staging" / "assets" / paper.paper_uid
    result["figures"] = extract_figures(
        paper.pdf_local_path, assets_dir, paper.paper_uid, config
    )
    return result
