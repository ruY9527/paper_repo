"""各页面列表分页与查询条件验收。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.publisher.blog_articles import list_blog_articles
from paperflow.web.app import create_app
from fastapi.testclient import TestClient


def test_queue_pagination_and_filter(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    for i in range(5):
        repo.upsert_paper(PaperRecord(paper_uid=f"q{i}", title=f"Agent Paper {i}" if i < 3 else f"Other {i}",
            normalized_title=f"q{i}", authors_json="[]", venue="CVPR", pub_year=2026,
            fetch_date="2026-05-01", source="arxiv", tier="S",
            status=PaperStatus.QUEUED.value))
    c = TestClient(create_app(cfg, repo))
    d = c.get("/api/analyzer/queue?limit=2&offset=0").json()
    assert d["total"] == 5 and len(d["items"]) == 2
    assert d["limit"] == 2
    f = c.get("/api/analyzer/queue?q=Agent&limit=20").json()
    assert f["total"] == 3
    t = c.get("/api/analyzer/queue?tier=A&limit=20").json()
    assert t["total"] == 0


def test_blog_articles_pagination(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    cfg.project.paper_repo_dir = str(tmp_path / "repo")  # 隔离，避免扫到真实博客
    docs = cfg.paper_repo_path / "docs" / "papers" / "2026" / "CVPR"
    docs.mkdir(parents=True, exist_ok=True)
    for i in range(4):
        (docs / f"p{i}.md").write_text(f"---\ntitle: Paper {i}\n---\nbody", encoding="utf-8")
    d = list_blog_articles(cfg, PaperRepository(cfg.db_path), limit=2, offset=0)
    assert d["total"] == 4 and len(d["items"]) == 2
    f = list_blog_articles(cfg, PaperRepository(cfg.db_path), q="Paper 1", limit=20)
    assert f["total"] == 1
