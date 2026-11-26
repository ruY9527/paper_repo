"""网站收录→Git发布闭环验收 + 解析失败日志可见验收。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from paperflow.config import load_example_config
from paperflow.db.repository import PaperRepository
from paperflow.web.app import create_app


def test_site_publish_status(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo_dir = tmp_path / "repo"
    (repo_dir / "docs" / "sites").mkdir(parents=True)
    cfg.project.paper_repo_dir = str(repo_dir)
    c = TestClient(create_app(cfg, PaperRepository(cfg.db_path)))
    d = c.get("/api/sites/publish-status").json()
    assert d["public_count"] == 0
    assert d["nav_exists"] is False
    assert d["needs_publish"] is False  # 无网站无需发布


def test_publish_status_detects_stale(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo_dir = tmp_path / "repo"; (repo_dir / "docs" / "sites").mkdir(parents=True)
    cfg.project.paper_repo_dir = str(repo_dir)
    repo = PaperRepository(cfg.db_path)
    # 造一个公开网站
    from paperflow.utils.timeutil import now_iso
    repo.add_site(url="https://example.com", normalized_url="https://example.com/",
                  domain="example.com", title="Example", description="", personal_note="",
                  category_id=1, tags=[], favicon_url="", rating=0, is_pinned=0, is_public=1)
    c = TestClient(create_app(cfg, repo))
    d = c.get("/api/sites/publish-status").json()
    assert d["public_count"] == 1
    assert d["nav_stale"] is True  # 导航页不存在 → 需同步
    assert d["needs_publish"] is True
