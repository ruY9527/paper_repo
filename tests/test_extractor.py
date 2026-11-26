"""Phase 4 验收：动态生成含文字+图片的 PDF，验证文本抽取、References 截断、WebP 压缩。"""

import fitz
from PIL import Image
from pathlib import Path

from paperflow.config import load_example_config
from paperflow.pipeline.extractor import extract_clean_text, extract_figures


def _make_test_pdf(path: Path) -> None:
    """用 PyMuPDF 生成一个含 2 页文字与一张大图的测试 PDF。"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Action Recognition with Vision Language Models", fontsize=16)
    page.insert_text((72, 100), "We propose a novel method for video understanding.", fontsize=12)
    # 插入一张 800x500 的内嵌图片（符合 >=400x200 过滤条件）
    img = Image.new("RGB", (800, 500), color=(120, 80, 200))
    img_bytes = __import__("io").BytesIO()
    img.save(img_bytes, format="PNG")
    page.insert_image(fitz.Rect(72, 120, 500, 380), stream=img_bytes.getvalue())

    page2 = doc.new_page()
    page2.insert_text((72, 72), "Experiments show state-of-the-art results.", fontsize=12)
    page2.insert_text((72, 100), "References", fontsize=14)
    page2.insert_text((72, 120), "This reference line should be truncated away.", fontsize=10)
    doc.save(str(path))
    doc.close()


def test_extract_clean_text(tmp_path):
    pdf = tmp_path / "test.pdf"
    _make_test_pdf(pdf)
    text = extract_clean_text(pdf)
    assert "--- PAGE 1 ---" in text
    assert "Action Recognition" in text
    assert "--- PAGE 2 ---" in text
    assert "Experiments show state-of-the-art" in text
    # References 及之后内容被截断
    assert "References" not in text
    assert "should be truncated away" not in text


def test_extract_figures_to_webp(tmp_path):
    pdf = tmp_path / "test.pdf"
    _make_test_pdf(pdf)
    out_dir = tmp_path / "assets"
    cfg = load_example_config()
    figs = extract_figures(pdf, out_dir, "arxiv_2603.12345", cfg)
    assert len(figs) == 1
    p = Path(figs[0])
    assert p.exists()
    assert p.suffix == ".webp"
    with Image.open(p) as im:
        assert im.format == "WEBP"
        assert im.width <= 1200


def test_extract_figures_no_images_graceful(tmp_path):
    """纯文字 PDF 无内嵌图时返回 []，不报错。"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Pure text paper", fontsize=12)
    pdf = tmp_path / "text_only.pdf"
    doc.save(str(pdf))
    doc.close()

    cfg = load_example_config()
    figs = extract_figures(pdf, tmp_path / "assets", "arxiv_x", cfg)
    assert figs == []
