"""harness_web 附件模式验收（纯函数层，不真跑浏览器）。"""
from __future__ import annotations

from pathlib import Path

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.analyzers.harness_web_analyzer import HarnessWebAnalyzer


def _analyzer(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(PaperRecord(paper_uid="p1", title="My Paper", normalized_title="my paper",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-23",
        source="arxiv", tier="S", status=PaperStatus.DOWNLOADED.value))
    return cfg, repo, HarnessWebAnalyzer(cfg, repo)


def test_build_prompt_is_verbatim(tmp_path):
    cfg, repo, a = _analyzer(tmp_path)
    p = a.build_prompt("p1")
    # 用户原文逐字特征全部在，且没有注入 PDF 路径/元数据/输出约束
    assert p.startswith("你的任务是：清晰、易懂、深入、详细的总结这篇论文")
    assert "Andrej Karpathy" in p and "Kaiming He" in p
    assert "13. 调研、思考" in p
    assert "你可以借助本地相关的skills来一起完成" in p
    assert "{{pdf_path}}" not in p and "本地 PDF 绝对路径" not in p
    assert "【系统输出约束】" not in p and "抽取全文" not in p


def test_build_prompt_same_regardless_errors(tmp_path):
    cfg, repo, a = _analyzer(tmp_path)
    assert a.build_prompt("p1") == a.build_prompt("p1", ["上次错误1", "上次错误2"])


def test_wrap_output_adds_frontmatter(tmp_path):
    cfg, repo, a = _analyzer(tmp_path)
    out = a._wrap_output("这是 AI 的总结正文。", "p1")
    assert out.startswith("---") and "paper_uid: \"p1\"" in out
    assert "title: \"My Paper\"" in out
    assert "这是 AI 的总结正文。" in out
    assert a._wrap_output("---\ntitle: x\n---\nbody", "p1") == "---\ntitle: x\n---\nbody"


def test_find_pdf(tmp_path):
    cfg, repo, a = _analyzer(tmp_path)
    pdf = cfg.workspace_path / "tmp" / "pdfs" / "p1.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    assert a._find_pdf("p1") == pdf
    assert a._find_pdf("missing") is None
