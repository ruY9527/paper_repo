"""论文流水线阶段标记验收。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.web.app import create_app
from fastapi.testclient import TestClient


def test_pipeline_stage_flags(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    cases = [
        ("p0", PaperStatus.SCORED.value, {}, 0),
        ("p1", PaperStatus.DOWNLOADED.value, {"pdf_local_path": "/tmp/a.pdf"}, 1),
        ("p2", PaperStatus.STAGED.value, {"pdf_local_path": "/tmp/b.pdf",
                                          "md_staging_path": "s.md"}, 2),
        ("p3", PaperStatus.PUBLISHED.value, {"pdf_local_path": "/tmp/c.pdf",
                                             "md_staging_path": "s.md",
                                             "md_blog_path": "p.md"}, 3),
    ]
    for uid, status, extra, expect in cases:
        repo.upsert_paper(PaperRecord(paper_uid=uid, title=uid, normalized_title=uid,
            authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-05-01",
            source="arxiv", tier="S", status=status, **extra))
    c = TestClient(create_app(cfg, repo))
    items = {p["paper_uid"]: p for p in c.get("/api/papers?limit=50").json()["items"]}
    for uid, _, _, expect in cases:
        p = items[uid]
        assert p["stage"] == expect
        assert p["stage_flags"]["fetched"] is True
        assert sum(p["stage_flags"].values()) == expect + 1
