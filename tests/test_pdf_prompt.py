"""Phase 17 验收：用户原文提示词 + PDF 一起送给下游 AI。"""

from __future__ import annotations

import fitz
from pathlib import Path

from paperflow.analyzers.base import ensure_analysis_package, BaseAnalyzer
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.config import load_example_config


def _make_pdf(path: Path) -> None:
    doc = fitz.open(); pg = doc.new_page()
    pg.insert_text((72, 72), "A Test Paper About Agents")
    doc.save(str(path)); doc.close()


def test_user_prompt_and_pdf_in_package(tmp_path):
    """S 级任务包：用户原文提示词 + PDF 文件 + 绝对路径同时到位。"""
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    uid = "arxiv_p17_1"
    repo.upsert_paper(PaperRecord(
        paper_uid=uid, title="PDF Test Paper", normalized_title="pdf test paper",
        authors_json="[]", venue="CVPR", pub_year=2026,
        fetch_date="2026-11-22", source="arxiv", tier="S",
        status=PaperStatus.DOWNLOADED.value, abstract="abstract",
    ))
    pdf_dir = cfg.workspace_path / "tmp" / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    src_pdf = pdf_dir / f"{uid}.pdf"
    _make_pdf(src_pdf)

    d = ensure_analysis_package(cfg, repo, uid)
    prompt = (d / "prompt.md").read_text(encoding="utf-8")
    # 用户原文提示词特征
    assert "你可以借助本地的skills来完成" in prompt
    assert "13. 调研、思考" in prompt
    assert "Andrej Karpathy" in prompt and "Kaiming He" in prompt
    # PDF 文件复制进任务包，且 prompt 含其绝对路径
    assert (d / f"{uid}.pdf").exists()
    assert "本地 PDF 绝对路径" in prompt
    assert str((d / f"{uid}.pdf").resolve()) in prompt
    assert "{{pdf_path}}" not in prompt


def test_s_tier_uses_user_template_not_topic(tmp_path):
    """S 级即使命中方向标签，也用用户指定模板（含 PDF 路径）。"""
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    from paperflow.pipeline.prompt_manager import PromptManager
    pm = PromptManager()
    p = PaperRecord(
        paper_uid="arxiv_p17_2", title="Agent Paper", normalized_title="agent paper",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-22",
        source="arxiv", tier="S", abstract="", topic_tags_json='["Agent"]',
    )
    tid, rendered = pm.render_for_paper(p, {"pdf_path": "/tmp/x.pdf", "title": "Agent Paper",
        "paper_uid": "arxiv_p17_2", "venue": "CVPR", "year": 2026, "code_url": "",
        "paper_url": "", "bibtex": "", "figures_markdown": "", "content": ""})
    assert tid == "tier_s_default"
    assert "你可以借助本地的skills来完成" in rendered
    assert "/tmp/x.pdf" in rendered
