"""Phase 10 验收：方向检索、两年时效优先、排除词豁免、SQLite 迁移、Web API。

基于 07_TOPIC_DRIVEN_SEARCH_AND_RECENCY.md 第 7 节全部场景，离线运行。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperflow.config import AppConfig, load_config, load_example_config
from paperflow.db.models import PaperRecord
from paperflow.db.repository import PaperRepository
from paperflow.fetchers.base import RawPaper
from paperflow.fetchers.topic_fetcher import TopicSearchEngine
from paperflow.pipeline.topic_query import (
    compute_topic_relevance,
    parse_topic_query,
)
from paperflow.publisher.aggregator import build_topic_pages, rebuild_all
from paperflow.web.app import create_app


# ---------------- helpers ----------------

def _mk(year: int, n: int, *, keyword: str = "agent and image fusion") -> list[RawPaper]:
    return [
        RawPaper(
            title=f"Topic Paper {year}-{i}",
            authors=["Alice"],
            venue="CVPR" if i % 2 == 0 else "IEEE TGRS",
            pub_year=year,
            pub_date=f"{year}-03-{10 + (i % 18):02d}",
            source="arxiv",
            arxiv_id=f"{year}.{i:05d}",
            abstract=keyword,
        )
        for i in range(n)
    ]


def _make_fns(p2026: int, p2025: int, p2024: int = 0, keyword: str = "agent and image fusion"):
    """模拟两个数据源返回同样论文（验证引擎多源去重）。"""
    def fn(year, parsed_query, limit, **kwargs):
        if year == 2026:
            return _mk(2026, p2026, keyword=keyword)
        if year == 2025:
            return _mk(2025, p2025, keyword=keyword) + _mk(2024, p2024, keyword=keyword)
        return []
    return {"arxiv": fn, "openalex": fn}


@pytest.fixture
def cfg(tmp_path):
    c = load_example_config()
    c.project.workspace_dir = str(tmp_path / "workspace")
    c.project.paper_repo_dir = str(tmp_path / "paper_repo")
    return c


# ---------------- 1. 查询解析与中英扩展 ----------------

def test_query_parse_and_expansion(cfg):
    single = parse_topic_query("agent", cfg)
    assert len(single.groups) == 1
    assert "LLM agent" in single.groups[0].terms
    assert "AND" not in single.arxiv_query()

    combo = parse_topic_query("agent+图像融合", cfg)
    assert [g.raw for g in combo.groups] == ["agent", "图像融合"]
    assert " AND " in combo.arxiv_query()
    assert " AND " in combo.openalex_query()
    assert '"image fusion"' in combo.openalex_query()

    whole = parse_topic_query("HSI-MSI图像融合", cfg)
    assert len(whole.groups) == 1
    assert any("HSI-MSI fusion" in t for t in whole.groups[0].terms)
    assert whole.arxiv_query().startswith("(")


def test_topic_relevance(cfg):
    parsed = parse_topic_query("agent+图像融合", cfg)
    strong = RawPaper(title="Agent for image fusion", authors=[], venue="CVPR",
                      pub_year=2026, source="arxiv", abstract="We study agent and fusion.")
    weak = RawPaper(title="A random note", authors=[], venue="arXiv",
                    pub_year=2026, source="arxiv", abstract="Something else.")
    assert compute_topic_relevance(strong, parsed) > compute_topic_relevance(weak, parsed)


# ---------------- 2. 两年时效优先（核心） ----------------

def test_scenario_a_primary_sufficient(cfg):
    """2026 充足：limit=20，25 篇 2026 + 10 篇 2025 → 全 2026，不兜底。"""
    repo = PaperRepository(cfg.db_path)
    result = TopicSearchEngine(cfg, repo, _make_fns(25, 10)).search(
        "agent+图像融合", limit=20
    )
    assert len(result.papers) == 20
    assert all(p.pub_year == 2026 for p in result.papers)
    assert result.primary_count == 20
    assert result.fallback_count == 0
    assert result.filtered_old_count == 0


def test_scenario_b_fallback_fills_gap(cfg):
    """2026 不足：6 篇 2026 + 20 篇 2025 + 10 篇 2024 → 6+9，0 篇 2024，过滤计数 10。"""
    repo = PaperRepository(cfg.db_path)
    result = TopicSearchEngine(cfg, repo, _make_fns(6, 20, 10)).search(
        "agent+图像融合", limit=15
    )
    assert len(result.papers) == 15
    years = [p.pub_year for p in result.papers]
    assert years.count(2026) == 6
    assert years.count(2025) == 9
    assert years.count(2024) == 0
    assert result.filtered_old_count == 10
    # 2026 必须绝对置顶
    assert years[:6] == [2026] * 6


def test_scenario_c_only_primary(cfg):
    repo = PaperRepository(cfg.db_path)
    result = TopicSearchEngine(cfg, repo, _make_fns(6, 20, 10)).search(
        "agent", limit=15, only_primary_year=True
    )
    assert len(result.papers) == 6
    assert all(p.pub_year == 2026 for p in result.papers)
    assert result.fallback_count == 0


# ---------------- 3. 排除词豁免 ----------------

def test_exclude_keywords_exempt_in_topic_mode(cfg):
    """全局排除 hyperspectral 时，Topic 检索 HSI-MSI图像融合 仍高分入库。"""
    cfg.interest_profile.exclude_keywords = ["hyperspectral"]
    repo = PaperRepository(cfg.db_path)
    papers = _mk(2026, 5, keyword="hyperspectral and multispectral image fusion HSI-MSI")
    def fn(year, parsed_query, limit, **kwargs):
        return papers if year == 2026 else []

    result = TopicSearchEngine(cfg, repo, {"arxiv": fn, "openalex": fn}).search(
        "HSI-MSI图像融合", limit=5
    )
    assert len(result.papers) == 5
    for p in result.papers:
        # Topic 模式不应用 exclude_keywords 的 -50 扣分；分数由相关性 + 时效加分驱动
        assert p.score > 0
        assert p.tier in ("S", "A")
        assert "hyperspectral" not in json.loads(p.matched_tags_json or "[]")  # 不带排除标记
    assert repo.count_papers() == 5
    saved = repo.get_all_papers()[0]
    assert saved.discovery_mode == "topic"
    assert "HSI-MSI图像融合" in json.loads(saved.topic_tags_json)


# ---------------- 4. SQLite 平滑迁移 ----------------

def test_legacy_db_migration_preserves_data(tmp_path):
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE papers (
        paper_uid TEXT PRIMARY KEY, title TEXT NOT NULL, normalized_title TEXT NOT NULL,
        authors_json TEXT NOT NULL, venue TEXT NOT NULL, pub_year INTEGER NOT NULL,
        fetch_date TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'FETCHED',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.execute("INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
        "legacy_1", "Legacy Paper", "legacy paper", "[]", "CVPR", 2024,
        "2024-01-01", "arxiv", "SKIPPED", "2024-01-01", "2024-01-01",
    ))
    conn.commit()
    conn.close()

    repo = PaperRepository(db)  # 触发迁移
    cols = {r["name"] for r in repo._connect().execute("PRAGMA table_info(papers)").fetchall()}
    assert "discovery_mode" in cols
    assert "topic_tags_json" in cols
    old = repo.get_paper("legacy_1")
    assert old is not None
    assert old.title == "Legacy Paper"
    assert old.status == "SKIPPED"           # 状态未被重置
    assert old.discovery_mode == "venue"     # 默认值
    assert old.topic_tags_json == "[]"
    # topic_search_runs 表已建立
    assert repo._connect().execute(
        "SELECT COUNT(*) FROM topic_search_runs"
    ).fetchone()[0] == 0
    # 追加标签不破坏旧记录
    repo.append_topic_tag("legacy_1", "Agent")
    assert json.loads(repo.get_paper("legacy_1").topic_tags_json) == ["Agent"]
    assert repo.get_paper("legacy_1").status == "SKIPPED"


# ---------------- 5. Web API ----------------

@pytest.fixture
def web_ctx(cfg, monkeypatch):
    import paperflow.fetchers.topic_fetcher as tf

    # 让 Web runner 内部实例化的引擎走假数据源
    monkeypatch.setattr(tf, "_default_fetch", lambda config, source: _FakeFetcher(source))
    repo = PaperRepository(cfg.db_path)
    app = create_app(cfg, repo)
    return {"client": TestClient(app), "repo": repo, "cfg": cfg}


class _FakeFetcher:
    def __init__(self, source):
        self.source = source
    def fetch_topic_year(self, *, year, parsed_query, limit, **kwargs):
        if year == 2026:
            return _mk(2026, 3)
        if year == 2025:
            return _mk(2025, 5)
        return []
    def close(self):
        pass


def test_web_preview_and_read_apis(web_ctx):
    c = web_ctx["client"]
    r = c.post("/api/topics/preview-query", json={"query": "agent+图像融合"})
    assert r.status_code == 200
    data = r.json()
    assert len(data["groups"]) == 2
    assert " AND " in data["arxiv_query"]
    assert data["primary_year"] == 2026
    assert data["min_allowed_year"] == 2025

    r = c.get("/api/topics/subscriptions")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3
    assert "hsi-msi图像融合" in r.json()["synonym_dict"]

    r = c.get("/api/topics/history")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_web_search_sse_and_audit(web_ctx):
    c = web_ctx["client"]
    r = c.post("/api/topics/search", json={"query": "agent", "limit": 5})
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    end = time.time() + 10
    while time.time() < end:
        if c.get("/api/tasks/active").json().get("active") is False:
            break
        time.sleep(0.05)

    sse = c.get(f"/api/tasks/{task_id}/stream")
    assert sse.status_code == 200
    assert "SUCCESS" in sse.text
    assert "result" in sse.text  # 终态事件携带分年结果

    history = web_ctx["repo"].get_topic_search_runs()
    assert len(history) == 1
    assert history[0]["status"] == "SUCCESS"
    assert history[0]["primary_count"] >= 1
    assert c.get("/api/topics/history").json()["items"][0]["topic_name"] == "agent"


# ---------------- 6. 聚合专题页 ----------------

def test_aggregator_topic_pages(cfg):
    repo = PaperRepository(cfg.db_path)
    for uid, year in (("t26", 2026), ("t25", 2025)):
        repo.upsert_paper(PaperRecord(
            paper_uid=uid, title=f"Paper {uid}", normalized_title=uid,
            authors_json="[]", venue="CVPR", pub_year=year,
            pub_date=f"{year}-05-01", fetch_date=f"{year}-05-01", source="arxiv",
            tier="S", discovery_mode="topic",
            topic_tags_json=json.dumps(["Agent"], ensure_ascii=False),
        ))
    pages = build_topic_pages(cfg, repo)
    assert "agent" in pages
    content = pages["agent"]
    assert "2026 最新前沿" in content
    assert "2025 精选兜底" in content

    stats = rebuild_all(cfg, repo)
    assert stats["pages"] >= 12
    assert (cfg.paper_repo_path / "docs" / "topics" / "agent.md").exists()


# ---------------- 回归：订阅保存字段隔离 + auto_download 默认下载 ----------------

def test_subscriptions_put_strips_readonly_fields(cfg, monkeypatch):
    """前端回传含 primary_count/fallback_count/expanded_query 的对象时，PUT 不应 422。"""
    import paperflow.web.routes.topics as topics_mod
    from paperflow.config import PROJECT_ROOT
    # 隔离 CONFIG_PATH
    tmp_cfg = cfg.project.workspace_dir + "_topics_config.yaml"
    tmp_cfg_path = Path(tmp_cfg)
    tmp_cfg_path.write_text(
        (PROJECT_ROOT / "config" / "config.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(topics_mod, "CONFIG_PATH", tmp_cfg_path)

    repo = PaperRepository(cfg.db_path)
    app = create_app(cfg, repo)
    c = TestClient(app)
    # 模拟前端把 GET 返回的完整对象（含只读字段）原样 PUT
    subs = c.get("/api/topics/subscriptions").json()["items"]
    r = c.put("/api/topics/subscriptions", json={"subscriptions": subs})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == len(subs)


def test_topic_search_auto_download_defaults(cfg, monkeypatch):
    """方向检索 auto_download=True 时应触发 download_s_papers。"""
    repo = PaperRepository(cfg.db_path)
    def fake_download(config, repo, client=None):
        return {"downloaded": 3, "paywall_blocked": 0, "fallback": 0}
    monkeypatch.setattr(
        "paperflow.pipeline.downloader.download_s_papers", fake_download
    )
    from paperflow.fetchers.topic_fetcher import TopicSearchEngine
    def fn(year, parsed_query, limit, **kwargs):
        if year == 2026:
            return _mk(2026, 5)
        return []
    engine = TopicSearchEngine(cfg, repo, {"arxiv": fn, "openalex": fn})
    # auto_download=True
    result = engine.search("agent", limit=5, auto_download=True)
    assert result.new_inserted_count == 5
