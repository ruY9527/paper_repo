"""Phase 5 验收：MD 校验、metrics 入库、安全删除、非法 MD 拦截、路径越界。"""

from pathlib import Path

import pytest

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus, PaperTier
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.cleaner import UnsafeDeleteError, clean_papers
from paperflow.pipeline.md_validator import validate_all_staged, validate_md_file
from paperflow.publisher.digest import generate_digest

VALID_MD = (
    "---\n"
    'paper_uid: "arxiv_2603.12345"\n'
    'title: "A Great Paper on Video Understanding"\n'
    'venue: "CVPR"\n'
    "year: 2026\n"
    'tier: "S"\n'
    'tldr: "一句话总结本文核心贡献。"\n'
    "---\n\n"
    "# A Great Paper on Video Understanding\n\n"
    "## 1. 一句话总结\n"
    "本文提出了一种新的视频理解架构，在多个基准上取得了最先进的结果。" * 20
    + "\n\n## 2. 核心方法\n"
    + "详细的方法描述在这里，包含足够的正文内容以满足最小字符数要求。方法细节。" * 30
    + "\n\n<!-- PAPERFLOW_METRICS_JSON\n"
    "{\n"
    '  "task": "Video Action Recognition",\n'
    '  "backbone": "ViT-L",\n'
    '  "datasets": ["Kinetics-400", "THUMOS14"],\n'
    '  "sota_summary": "mAP 72.4%",\n'
    '  "innovation_tags": ["Zero-Shot"]\n'
    "}\n"
    "-->\n"
)


def _paper(uid="arxiv_2603.12345", tier="S", status="QUEUED", with_pdf=False) -> PaperRecord:
    return PaperRecord(
        paper_uid=uid, title="A Great Paper on Video Understanding",
        normalized_title="a great paper on video understanding",
        authors_json="[]", venue="CVPR", pub_year=2026,
        fetch_date="2026-03-16", source="arxiv",
        tier=tier, status=status, abstract="A novel video understanding approach.",
    )


def _setup(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    repo = PaperRepository(tmp_path / "state.db")
    return cfg, repo


def test_valid_md_passes_and_metrics_saved(tmp_path):
    cfg, repo = _setup(tmp_path)
    repo.upsert_paper(_paper())

    staging = cfg.workspace_path / "staging" / "2026-03-16"
    staging.mkdir(parents=True, exist_ok=True)
    md = staging / "arxiv_2603.12345.md"
    md.write_text(VALID_MD, encoding="utf-8")

    result = validate_md_file(md, repo, cfg)
    assert result.ok is True, result.errors
    assert result.metrics["task"] == "Video Action Recognition"
    assert repo.get_paper("arxiv_2603.12345").status == PaperStatus.STAGED.value
    assert repo.get_metrics("arxiv_2603.12345")["backbone"] == "ViT-L"
    assert repo.get_metrics("arxiv_2603.12345")["datasets"] == ["Kinetics-400", "THUMOS14"]


def test_invalid_md_fails(tmp_path):
    cfg, repo = _setup(tmp_path)
    repo.upsert_paper(_paper())

    staging = cfg.workspace_path / "staging" / "2026-03-16"
    staging.mkdir(parents=True, exist_ok=True)

    # 缺字段 + 正文过短
    md = staging / "arxiv_2603.12345.md"
    md.write_text("---\ntitle: X\n---\n太短", encoding="utf-8")
    result = validate_md_file(md, repo, cfg)
    assert result.ok is False
    assert any("paper_uid" in e for e in result.errors)
    assert any("tldr" in e for e in result.errors)
    assert any("正文过短" in e for e in result.errors)
    # 状态保持 QUEUED
    assert repo.get_paper("arxiv_2603.12345").status == PaperStatus.QUEUED.value


def test_uid_mismatch_detected(tmp_path):
    cfg, repo = _setup(tmp_path)
    repo.upsert_paper(_paper())
    staging = cfg.workspace_path / "staging" / "2026-03-16"
    staging.mkdir(parents=True, exist_ok=True)
    mismatch = VALID_MD.replace('paper_uid: "arxiv_2603.12345"', 'paper_uid: "wrong_uid"')
    md = staging / "arxiv_2603.12345.md"
    md.write_text(mismatch, encoding="utf-8")
    result = validate_md_file(md, repo, cfg)
    assert result.ok is False
    assert any("不一致" in e for e in result.errors)


def test_cleaner_deletes_pdf_and_sets_flag(tmp_path):
    cfg, repo = _setup(tmp_path)
    md_path = cfg.workspace_path / "staging" / "2026-03-16" / "arxiv_2603.12345.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(VALID_MD, encoding="utf-8")

    pdf_dir = cfg.workspace_path / "tmp" / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdf_dir / "arxiv_2603.12345.pdf"
    pdf.write_bytes(b"%PDF-1.4 test content" * 10)

    p = _paper(status=PaperStatus.PUBLISHED.value)
    p.pdf_local_path = str(pdf)
    p.md_staging_path = str(md_path)
    repo.upsert_paper(p)

    stats = clean_papers(cfg, repo, include_staged=False)
    assert stats["cleaned"] == 1
    assert not pdf.exists()
    updated = repo.get_paper("arxiv_2603.12345")
    assert updated.pdf_deleted == 1
    assert updated.pdf_local_path is None
    assert updated.status == PaperStatus.CLEANED.value


def test_cleaner_refuses_when_no_valid_md(tmp_path):
    cfg, repo = _setup(tmp_path)
    pdf_dir = cfg.workspace_path / "tmp" / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdf_dir / "arxiv_no_md.pdf"
    pdf.write_bytes(b"%PDF content")

    p = _paper(uid="arxiv_no_md", status=PaperStatus.PUBLISHED.value)
    p.pdf_local_path = str(pdf)
    p.md_staging_path = str(cfg.workspace_path / "staging" / "missing.md")
    repo.upsert_paper(p)

    clean_papers(cfg, repo)
    assert pdf.exists()  # MD 不存在，拒绝删除
    assert repo.get_paper("arxiv_no_md").pdf_deleted == 0


def test_cleaner_path_escape_refused(tmp_path):
    """传入 workspace/state.db 路径时清理器必须抛安全异常。"""
    cfg, repo = _setup(tmp_path)
    # state.db 在 workspace 根，不在 tmp/queue 内
    state_db = cfg.workspace_path / "state.db"
    state_db.parent.mkdir(parents=True, exist_ok=True)
    state_db.write_bytes(b"fake")
    from paperflow.pipeline.cleaner import _assert_safe_delete
    with pytest.raises(UnsafeDeleteError, match="越界"):
        _assert_safe_delete(state_db, cfg.workspace_path)
    # 确保文件未被删
    assert state_db.exists()


def test_digest_generation(tmp_path):
    cfg, repo = _setup(tmp_path)
    repo.upsert_paper(_paper(tier="S"))
    repo.upsert_paper(_paper(uid="arxiv_a", tier="A"))
    repo.upsert_paper(_paper(uid="arxiv_b", tier="B"))
    digest = generate_digest(cfg, repo, target_date="2026-03-16")
    text = digest.read_text(encoding="utf-8")
    assert "S 级精读列表" in text
    assert "arxiv_2603.12345" in text or "Video Understanding" in text
    assert "B 级归档统计" in text
