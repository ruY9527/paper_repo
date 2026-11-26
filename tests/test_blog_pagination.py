"""首页分页 + 精读页返回链接验收。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.publisher.aggregator import build_index
from paperflow.publisher.back_link import append_back_link


def test_pager_appears_only_when_many(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    cfg.project.paper_repo_dir = str(tmp_path / "paper_repo")
    (cfg.paper_repo_path / "docs" / "venues").mkdir(parents=True, exist_ok=True)
    repo = PaperRepository(cfg.db_path)
    # 造 10 篇已发布 S 级
    for i in range(10):
        uid = f"p{i}"
        repo.upsert_paper(PaperRecord(paper_uid=uid, title=f"P{i}", normalized_title=uid,
            authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-05-01",
            source="arxiv", tier="S", status=PaperStatus.PUBLISHED.value,
            md_blog_path=f"papers/2026/CVPR/{uid}.md"))
    out = build_index(cfg, repo)
    assert "hv-pager" in out and "hvGo" in out
    assert "每页 8 篇" in out


def test_back_link_injected_idempotent():
    md = '---\npaper_uid: "x"\ntitle: "T"\n---\n# Body\ncontent'
    out = append_back_link(md)
    assert "返回首页" in out
    assert "../../../index.md" in out
    # 固定定位在左侧、不随滚动；自带样式，无旧 div markdown 块
    assert ".pf-back-home{position:fixed;left:18px" in out
    assert "align=\"left\" markdown" not in out
    assert append_back_link(out) == out  # 幂等
