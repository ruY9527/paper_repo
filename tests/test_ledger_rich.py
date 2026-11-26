"""论文账本扩展字段验收：时间点、关键词、分页总数。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.web.app import create_app
from fastapi.testclient import TestClient


def test_ledger_rich_fields(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(PaperRecord(paper_uid="p1", title="P1", normalized_title="p1",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-05-01",
        source="arxiv", tier="S", status=PaperStatus.SCORED.value,
        topic_tags_json='["agent","fusion"]', matched_tags_json='["agent","vlm"]'))
    repo.update_status("p1", PaperStatus.DOWNLOADED, pdf_local_path="/tmp/p1.pdf")
    c = TestClient(create_app(cfg, repo))
    d = c.get("/api/papers?limit=20").json()
    p = next(x for x in d["items"] if x["paper_uid"] == "p1")
    assert p["fetch_date"] == "2026-05-01"
    assert p["tags"] == ["agent", "fusion", "vlm"]  # 去重保序
    assert p["downloaded_at"]  # 进入 DOWNLOADED 自动记录
    assert "created_at" in p and "updated_at" in p
    assert "last_analysis_at" in p and p["last_analysis_at"] == ""
    assert d["total"] == 1


def test_downloaded_at_idempotent(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(PaperRecord(paper_uid="p1", title="P1", normalized_title="p1",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-05-01",
        source="arxiv", tier="S", status=PaperStatus.SCORED.value))
    repo.update_status("p1", PaperStatus.DOWNLOADED, pdf_local_path="/tmp/p1.pdf")
    first = repo.get_paper("p1").downloaded_at
    assert first
    repo.update_status("p1", PaperStatus.DOWNLOADED, pdf_local_path="/tmp/p1.pdf")
    assert repo.get_paper("p1").downloaded_at == first  # 不覆盖
