"""Phase 16 验收：博客文章视图（发布记录以博客仓库为准）。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.publisher.blog_articles import list_blog_articles, publish_one, read_blog_article
from paperflow.web.app import create_app


@pytest.fixture
def ctx(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo_dir = tmp_path / "paper_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "docs" / "papers" / "CVPR").mkdir(parents=True, exist_ok=True)
    cfg.project.paper_repo_dir = str(repo_dir)
    repo = PaperRepository(cfg.db_path)
    return {"cfg": cfg, "repo": repo, "client": TestClient(create_app(cfg, repo)), "dir": tmp_path}


def test_publish_one_and_list(ctx):
    """单篇发布写入博客仓库，清单以博客文件为准。"""
    cfg, repo = ctx["cfg"], ctx["repo"]
    uid = "arxiv_blog_1"
    repo.upsert_paper(PaperRecord(
        paper_uid=uid, title="Blog Paper", normalized_title="blog paper",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-22",
        source="arxiv", tier="S", status=PaperStatus.STAGED.value,
    ))
    staging = cfg.workspace_path / "staging" / "2026-11-22"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / f"{uid}.md").write_text(
        '---\npaper_uid: "arxiv_blog_1"\ntitle: "Blog Paper"\n---\n# Blog Paper\ncontent',
        encoding="utf-8",
    )
    r = publish_one(cfg, repo, uid)
    assert r["ok"] is True
    assert (cfg.paper_repo_path / "docs" / r["repo_rel"]).exists()
    assert repo.get_paper(uid).status == PaperStatus.PUBLISHED.value
    assert repo.get_paper(uid).md_blog_path == r["repo_rel"]

    data = list_blog_articles(cfg, repo)
    assert data["total"] >= 1
    hit = next(x for x in data["items"] if x["paper_uid"] == uid)
    assert hit["title"] == "Blog Paper"
    assert hit["git_state"] in ("pushed", "untracked", "modified", "committed")


def test_read_blog_article_path_guard(ctx):
    cfg = ctx["cfg"]
    assert read_blog_article(cfg, "../../mkdocs.yml") is None  # 越界拒绝


def test_blog_apis(ctx):
    c = ctx["client"]
    r = c.get("/api/blog/articles")
    assert r.status_code == 200 and "items" in r.json()
    assert c.get("/api/blog/articles/none/content").status_code == 404


def test_publish_idempotent_and_staging_status(ctx):
    """发布幂等 + 待审列表带发布状态，防止重复点击/误判。"""
    cfg, repo, c = ctx["cfg"], ctx["repo"], ctx["client"]
    uid = "arxiv_pub_idem"
    repo.upsert_paper(PaperRecord(
        paper_uid=uid, title="Idem Paper", normalized_title="idem paper",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-22",
        source="arxiv", tier="S", status=PaperStatus.STAGED.value,
    ))
    sd = cfg.workspace_path / "staging" / "2026-11-22"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / f"{uid}.md").write_text(
        '---\npaper_uid: "arxiv_pub_idem"\ntitle: "Idem Paper"\nvenue: CVPR\nyear: 2026\ntier: S\ntldr: t\n---\n'
        + "# Body\n" + "x" * 400, encoding="utf-8",
    )
    # 首次发布
    r1 = publish_one(cfg, repo, uid)
    assert r1["ok"] and not r1.get("already_published")
    # 再次发布：幂等，标记 already_published，不改内容
    r2 = publish_one(cfg, repo, uid)
    assert r2["ok"] and r2.get("already_published") is True
    # staging API 返回发布状态：默认 pending 视图不含已发布，用 all 查
    items = c.get("/api/staging?status=all").json()["items"]
    hit = next(x for x in items if x["paper_uid"] == uid)
    assert hit["published"] is True
    assert c.get("/api/staging?status=pending").json()["total"] == 0  # 已发布不混入待审
    assert hit["status"] == PaperStatus.PUBLISHED.value
    assert hit["md_blog_path"]
