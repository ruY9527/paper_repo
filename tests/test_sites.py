"""Phase 14 验收：网站收录中心与博客导航页（离线可测）。

覆盖规格第 7 节：URL 标准化去重、HTML 抓取降级、书签导入、
隐私隔离与 mkdocs strict 构建、死链巡检、Web API。
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest
import respx
import httpx
from fastapi.testclient import TestClient

from paperflow.config import load_example_config
from paperflow.db.repository import PaperRepository
from paperflow.sites.blog_renderer import render_sites_index, sync_sites_blog, update_mkdocs_nav
from paperflow.sites.bookmark_importer import parse_bookmarks_html, parse_url_lines
from paperflow.sites.health_checker import check_one
from paperflow.sites.metadata_fetcher import fetch_metadata, normalize_url
from paperflow.web.app import create_app

MKDOCS = Path(__file__).resolve().parents[1] / "paper_repo" / "mkdocs.yml"


@pytest.fixture
def ctx(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo_dir = tmp_path / "paper_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(MKDOCS, repo_dir / "mkdocs.yml")
    # 复制完整 docs 目录，保证 mkdocs strict 构建时 nav 引用的页面都存在
    src_docs = MKDOCS.parent / "docs"
    if src_docs.exists():
        shutil.copytree(src_docs, repo_dir / "docs", dirs_exist_ok=True)
    else:
        (repo_dir / "docs").mkdir(exist_ok=True)
        (repo_dir / "docs" / "index.md").write_text("# 临时首页\n", encoding="utf-8")
    cfg.project.paper_repo_dir = str(repo_dir)
    repo = PaperRepository(cfg.db_path)
    return {"cfg": cfg, "repo": repo, "client": TestClient(create_app(cfg, repo)), "dir": tmp_path}


# ---------------- 1. URL 标准化与去重 ----------------

def test_normalize_and_dedup(ctx):
    a, da = normalize_url("https://HuggingFace.co/?utm_source=twitter")
    b, db = normalize_url("https://huggingface.co")
    assert a == b == "https://huggingface.co"
    assert da == db == "huggingface.co"
    # 非法协议拒绝
    with pytest.raises(ValueError):
        normalize_url("javascript:alert(1)")
    with pytest.raises(ValueError):
        normalize_url("file:///etc/passwd")
    # 重复收录 409
    cat = ctx["repo"].get_site_categories()[0]["id"]
    c = ctx["client"]
    r1 = c.post("/api/sites", json={"url": "https://huggingface.co/?utm_source=x",
                                    "title": "HF", "category_id": cat})
    assert r1.status_code == 200
    r2 = c.post("/api/sites", json={"url": "https://huggingface.co",
                                    "title": "HF dup", "category_id": cat})
    assert r2.status_code == 409


# ---------------- 2. HTML 元信息抓取与降级 ----------------

def test_fetch_metadata_ok():
    html = b"""<html><head><title>Test Site</title>
    <meta name="description" content="A great site">
    <link rel="icon" href="/favicon.ico"></head><body>hi</body></html>"""
    with respx.mock:
        respx.get("https://example.com").mock(return_value=httpx.Response(
            200, headers={"content-type": "text/html"}, content=html))
        d = fetch_metadata("https://example.com", timeout=3)
    assert d["ok"] is True
    assert d["title"] == "Test Site"
    assert d["description"] == "A great site"
    assert d["favicon_url"] == "https://example.com/favicon.ico"


def test_fetch_metadata_degrades():
    with respx.mock:
        respx.get("https://forbidden.com").mock(return_value=httpx.Response(403))
        d = fetch_metadata("https://forbidden.com", timeout=3)
    assert d["ok"] is False and d["title"] == "forbidden.com"
    assert d["warning"]  # 有降级提示，不抛异常
    with respx.mock:
        respx.get("https://timeout.com").mock(side_effect=httpx.TimeoutException("timeout"))
        d2 = fetch_metadata("https://timeout.com", timeout=3)
    assert d2["ok"] is False and d2["warning"]


# ---------------- 3. 书签导入 ----------------

def test_bookmarks_import():
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
    <DL><p>
      <H3>AI 与大模型</H3><DL><p>
        <DT><A HREF="https://a.com/">A</A>
        <DT><A HREF="https://b.com">B</A>
      </DL><p>
      <H3>优质技术博客</H3><DL><p>
        <DT><A HREF="https://c.com">C</A>
        <DT><A HREF="https://a.com/">A dup</A>
      </DL><p>
    </DL><p>"""
    items = parse_bookmarks_html(html)
    assert len(items) == 4
    assert items[0]["folder"] == "AI 与大模型"  # a.com 第一条
    assert items[2]["folder"] == "优质技术博客"  # c.com
    assert items[3]["url"] == "https://a.com/"  # 重复链接（导入时会被去重）
    assert len(parse_url_lines("https://a.com\n\n# comment\nhttps://b.com\nhttps://a.com")) == 2


# ---------------- 4. 隐私隔离 + mkdocs strict ----------------

def test_privacy_and_strict_build(ctx):
    repo, cfg = ctx["repo"], ctx["cfg"]
    cat = repo.get_site_categories()[0]["id"]
    repo.add_site(url="https://pub1.com", normalized_url="https://pub1.com", domain="pub1.com",
                  title="Public One", description="公开站点", category_id=cat, is_public=1, is_pinned=1)
    repo.add_site(url="https://pub2.com", normalized_url="https://pub2.com", domain="pub2.com",
                  title="Public Two", category_id=cat, is_public=1)
    repo.add_site(url="https://secret.com", normalized_url="https://secret.com", domain="secret.com",
                  title="SECRET_INTERNAL_PORTAL", personal_note="绝密", category_id=cat, is_public=0, is_pinned=1)

    r = sync_sites_blog(cfg, repo)
    assert r["public_count"] == 2
    index = Path(r["index_path"]).read_text(encoding="utf-8")
    assert "Public One" in index and "Public Two" in index
    assert "⭐ 精选置顶" in index
    # 精选置顶区在分类区之前
    assert index.index("## ⭐ 精选置顶") < index.index("## 🤖 AI 与大模型")
    assert "SECRET_INTERNAL_PORTAL" not in index
    assert "绝密" not in index

    mk = (cfg.paper_repo_path / "mkdocs.yml").read_text(encoding="utf-8")
    assert "attr_list" in mk and "md_in_html" in mk and "网站导航" in mk

    # mkdocs strict 构建（网站导航页存在）
    from paperflow.publisher.mkdocs_service import MkDocsService
    svc = MkDocsService(cfg.paper_repo_path, cfg.workspace_path, 8001)
    result = svc.build_strict()
    assert result.ok is True, result.raw_output[-500:]


# ---------------- 5. 死链巡检与 Web API ----------------

def test_health_check_statuses():
    with respx.mock:
        respx.head("https://ok.com").mock(return_value=httpx.Response(200))
        assert check_one("https://ok.com", timeout=3)["status"] == "OK"
        respx.head("https://dead.com").mock(return_value=httpx.Response(404))
        assert check_one("https://dead.com", timeout=3)["status"] == "DEAD"


def test_web_api_crud_and_sync(ctx):
    c, repo = ctx["client"], ctx["repo"]
    cat = repo.get_site_categories()[0]["id"]
    r = c.post("/api/sites", json={"url": "https://x.com", "title": "X", "category_id": cat})
    assert r.status_code == 200
    sid = r.json()["id"]
    assert c.put(f"/api/sites/{sid}", json={"title": "X2", "is_public": 0}).status_code == 200
    assert c.get("/api/sites?is_public=0").json()["items"][0]["title"] == "X2"
    assert c.post("/api/sites/sync-blog", json={}).status_code == 200
    assert c.get("/api/sites/blog-content").status_code == 200
    assert c.delete(f"/api/sites/{sid}").status_code == 200


def test_bookmark_visit_and_sort(ctx):
    """书签核心：记录打开次数、按使用频率/星级排序、改网址重算。"""
    c, repo = ctx["client"], ctx["repo"]
    cat = repo.get_site_categories()[0]["id"]
    a = c.post("/api/sites", json={"url": "https://a.com", "title": "A", "category_id": cat,
                                   "rating": 5}).json()["id"]
    b = c.post("/api/sites", json={"url": "https://b.com", "title": "B", "category_id": cat}).json()["id"]
    # 打开 B 两次
    c.post(f"/api/sites/{b}/visit"); c.post(f"/api/sites/{b}/visit")
    bs = repo.get_site(b)
    assert bs["visit_count"] == 2 and bs["last_visited_at"]
    # 按常用排序：B 在前
    items = c.get("/api/sites?sort=visited").json()["items"]
    assert items[0]["title"] == "B"
    # 按星级排序：A 在前
    items2 = c.get("/api/sites?sort=rating").json()["items"]
    assert items2[0]["title"] == "A"
    # 改网址重算 normalized_url
    r = c.put(f"/api/sites/{a}", json={"url": "https://new-a.com/?utm_source=x", "title": "A2"})
    assert r.status_code == 200
    assert repo.get_site(a)["normalized_url"] == "https://new-a.com"
