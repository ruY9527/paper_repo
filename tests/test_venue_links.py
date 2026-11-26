"""Venue 总表链接与空页说明验收 + 其它页面同类检查。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.publisher.aggregator import (
    build_venue_tables, build_weeklies, build_open_source,
)


def _paper(uid, venue, title, **kw):
    return PaperRecord(paper_uid=uid, title=title, normalized_title=uid,
        authors_json="[]", venue=venue, pub_year=2026, pub_date="2026-05-01",
        fetch_date="2026-05-01", source="arxiv", tier="S",
        status=PaperStatus.PUBLISHED.value, **kw)


def test_empty_venue_page_has_hint(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    cfg.project.paper_repo_dir = str(tmp_path / "paper_repo")
    (cfg.paper_repo_path / "docs" / "venues").mkdir(parents=True, exist_ok=True)
    repo = PaperRepository(cfg.db_path)
    tables = build_venue_tables(cfg, repo)
    assert "暂无收录" in tables["TPAMI"]
    assert "其它来源" in tables["TPAMI"]


def test_venue_title_link_fallback(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    cfg.project.paper_repo_dir = str(tmp_path / "paper_repo")
    (cfg.paper_repo_path / "docs" / "venues").mkdir(parents=True, exist_ok=True)
    repo = PaperRepository(cfg.db_path)
    # 无 md_blog_path、无 paper_url、有 arxiv_id → 应链接 arXiv
    repo.upsert_paper(_paper("a1", "CVPR", "Title A", arxiv_id="2601.1"))
    tables = build_venue_tables(cfg, repo)
    assert "](https://arxiv.org/abs/2601.1)" in tables["CVPR"]


def test_weekly_and_opensource_titles_linked(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    cfg.project.paper_repo_dir = str(tmp_path / "paper_repo")
    (cfg.paper_repo_path / "docs" / "matrix").mkdir(parents=True, exist_ok=True)
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(_paper("a1", "CVPR", "Title A",
        arxiv_id="2601.1", paper_url="https://arxiv.org/abs/2601.1",
        code_url="https://github.com/a/b"))
    weekly = build_weeklies(cfg, repo)
    assert any("](https://arxiv.org/abs/2601.1)" in v for v in weekly.values())
    opensource = build_open_source(cfg, repo)
    assert "](https://arxiv.org/abs/2601.1)" in opensource
