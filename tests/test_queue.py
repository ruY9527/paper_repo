"""Phase 4 验收：队列导出结构完整（manifest/meta/text/prompt）与状态流转。"""

import json

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus, PaperTier
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.queue_exporter import export_queue


def test_export_queue_structure(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    repo = PaperRepository(tmp_path / "state.db")

    # A 级 SCORED 论文（无 PDF）
    a_paper = PaperRecord(
        paper_uid="arxiv_2603.11111", title="A Tier Paper on Video Understanding",
        normalized_title="a tier paper on video understanding",
        authors_json='["Alice"]', venue="CVPR", pub_year=2026,
        fetch_date="2026-03-16", source="arxiv",
        tier=PaperTier.A.value, status=PaperStatus.SCORED.value,
        abstract="We study video understanding with a new approach.",
        paper_url="https://arxiv.org/abs/2603.11111",
    )
    repo.upsert_paper(a_paper)

    result = export_queue(cfg, repo, target_date="2026-03-16")
    assert result["count"] == 1

    root = cfg.workspace_path / "queue" / "2026-03-16"
    manifest = json.loads((root / "queue_manifest.json").read_text(encoding="utf-8"))
    assert manifest["count"] == 1
    assert manifest["items"][0]["paper_uid"] == "arxiv_2603.11111"

    paper_dir = root / "arxiv_2603.11111"
    meta = json.loads((paper_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["tier"] == "A"
    assert "@inproceedings" in meta["bibtex"]
    assert (paper_dir / "extracted_text.md").exists()
    assert "A Tier Paper" in (paper_dir / "extracted_text.md").read_text(encoding="utf-8")
    assert (paper_dir / "prompt.md").exists()
    assert "速览" in (paper_dir / "prompt.md").read_text(encoding="utf-8")

    updated = repo.get_paper("arxiv_2603.11111")
    assert updated.status == PaperStatus.QUEUED.value


def test_export_queue_idempotent(tmp_path):
    """重复导出不产生重复任务。"""
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    repo = PaperRepository(tmp_path / "state.db")
    p = PaperRecord(
        paper_uid="arxiv_x", title="Paper X", normalized_title="paper x",
        authors_json="[]", venue="ICLR", pub_year=2026,
        fetch_date="2026-03-16", source="arxiv",
        tier="A", status="SCORED", abstract="Some abstract.",
    )
    repo.upsert_paper(p)
    r1 = export_queue(cfg, repo, target_date="2026-03-16")
    r2 = export_queue(cfg, repo, target_date="2026-03-16")
    assert r1["count"] == 1
    assert r2["count"] == 0  # 已 QUEUED，不再导出
