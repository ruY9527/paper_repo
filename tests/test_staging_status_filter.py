"""待审工作台状态筛选：已发布不再混入待审队列。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.web.app import create_app
from fastapi.testclient import TestClient


def test_staging_status_filter(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    sd = cfg.workspace_path / "staging" / "2026-11-23"
    sd.mkdir(parents=True, exist_ok=True)
    for uid, st in (("wait1", PaperStatus.STAGED.value),
                    ("pub1", PaperStatus.PUBLISHED.value),
                    ("clean1", PaperStatus.CLEANED.value)):
        repo.upsert_paper(PaperRecord(paper_uid=uid, title=uid, normalized_title=uid,
            authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-23",
            source="arxiv", tier="S", status=st))
        (sd / f"{uid}.md").write_text(
            f"---\npaper_uid: {uid}\ntitle: T\nvenue: CVPR\nyear: 2026\ntier: S\ntldr: t\n---\n"
            + "x" * 400, encoding="utf-8")
    c = TestClient(create_app(cfg, repo))
    pending = c.get("/api/staging?status=pending").json()
    assert pending["total"] == 1
    assert pending["items"][0]["paper_uid"] == "wait1"
    pub = c.get("/api/staging?status=published").json()
    assert pub["total"] == 2  # PUBLISHED + CLEANED
    alls = c.get("/api/staging?status=all").json()
    assert alls["total"] == 3
