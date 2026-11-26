"""Phase 8 验收：FastAPI TestClient 覆盖 05 文档第 6 节 6 项测试。"""

from __future__ import annotations

import json
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.web.app import create_app
from paperflow.web.routes import settings as settings_module
from paperflow.web.routes import tasks as tasks_module


VALID_MD = (
    "---\npaper_uid: \"arxiv_2603.12345\"\ntitle: \"Test Paper\"\n"
    "venue: \"CVPR\"\nyear: 2026\ntier: \"S\"\ntldr: \"一句话总结。\"\n---\n\n"
    + "正文内容与方法细节描述。" * 60 + "\n"
)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """隔离的 app + 临时配置 + 临时 repo。"""
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    cfg.project.paper_repo_dir = str(tmp_path / "paper_repo")
    cfg.publish.auto_git_commit = False
    repo = PaperRepository(cfg.db_path)

    # settings 路由使用临时 config 文件，避免污染真实配置
    from paperflow.config import PROJECT_ROOT
    tmp_cfg = tmp_path / "config.yaml"
    example = PROJECT_ROOT / "config" / "config.example.yaml"
    tmp_cfg.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(settings_module, "CONFIG_PATH", tmp_cfg)

    app = create_app(cfg, repo)
    client = TestClient(app)
    return {"client": client, "cfg": cfg, "repo": repo, "app": app, "tmp_cfg": tmp_cfg}


def _seed_paper(repo, uid="arxiv_2603.12345", tier="B", status="FETCHED",
                title="Video Action Recognition Paper"):
    from paperflow.pipeline.dedup import normalize_title
    p = PaperRecord(
        paper_uid=uid, title=title,
        normalized_title=normalize_title(title),
        authors_json='["Alice"]', venue="CVPR", pub_year=2026,
        pub_date="2026-03-16", fetch_date="2026-03-16", source="arxiv",
        tier=tier, status=status, abstract="A video understanding study.",
    )
    repo.upsert_paper(p)
    return p


# ---- 1. 首页 + dashboard summary ----
def test_index_and_dashboard(ctx):
    r = ctx["client"].get("/")
    assert r.status_code == 200
    assert "PaperFlow" in r.text

    r = ctx["client"].get("/api/dashboard/summary")
    assert r.status_code == 200
    data = r.json()
    assert "kpi" in data and "venue_distribution" in data
    assert "daily_trend" in data and "watermarks" in data
    assert len(data["venue_distribution"]) == 9
    assert data["kpi"]["total"] == 0


# ---- 2. 任务互斥（Mock runner）----
def test_task_mutex(ctx, monkeypatch):
    import threading

    started = threading.Event()
    release = threading.Event()

    def slow_runner(c):
        started.set()
        release.wait(timeout=5)
        return {"new_papers": 0}

    monkeypatch.setitem(tasks_module.RUNNERS, "fetch", slow_runner)

    c = ctx["client"]
    r1 = c.post("/api/tasks/fetch", json={})
    assert r1.status_code == 200
    tid = r1.json()["task_id"]
    # 等线程真正进入 RUNNING
    assert started.wait(timeout=3)
    r2 = c.post("/api/tasks/fetch", json={})
    assert r2.status_code == 409
    release.set()
    # 等待任务结束
    for _ in range(50):
        if c.get("/api/tasks/active").json().get("active") is False:
            break
        time.sleep(0.05)
    assert c.get(f"/api/tasks/{tid}/stream").status_code == 200


# ---- 3. SSE 收到 RUNNING→SUCCESS 且 run_logs 落库 ----
def test_sse_stream_and_runlog(ctx, monkeypatch):
    def quick_runner(c):
        c["emit"](stage="working", current=1, total=2, message="处理中")
        c["emit"](stage="working", current=2, total=2, message="完成中")
        return {"new_papers": 2, "tier_s": 1, "tier_a": 1}

    monkeypatch.setitem(tasks_module.RUNNERS, "export-queue", quick_runner)

    c = ctx["client"]
    before = ctx["repo"]._connect().execute("SELECT COUNT(*) FROM run_logs").fetchone()[0]
    r = c.post("/api/tasks/export-queue", json={})
    assert r.status_code == 200
    tid = r.json()["task_id"]

    # 等待完成
    for _ in range(60):
        if c.get("/api/tasks/active").json().get("active") is False:
            break
        time.sleep(0.05)

    # SSE 回放：历史缓冲含 RUNNING 与 SUCCESS
    resp = c.get(f"/api/tasks/{tid}/stream")
    assert resp.status_code == 200
    body = resp.text
    assert "RUNNING" in body and "SUCCESS" in body
    assert "text/event-stream" in resp.headers["content-type"]

    after = ctx["repo"]._connect().execute("SELECT COUNT(*) FROM run_logs").fetchone()[0]
    assert after == before + 1


# ---- 4. papers 筛选 + tier 提升 ----
def test_papers_filter_and_tier(ctx):
    repo = ctx["repo"]
    _seed_paper(repo, "arxiv_2603.11111", tier="B", status="FETCHED",
                title="Video Action Recognition Paper")
    _seed_paper(repo, "arxiv_2603.22222", tier="S", status="QUEUED",
                title="Multimodal Video Understanding Paper")
    c = ctx["client"]

    r = c.get("/api/papers?venue=CVPR&tier=B")
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = c.get("/api/papers?q=Video&status=QUEUED")
    assert r.json()["total"] == 1

    r = c.patch("/api/papers/arxiv_2603.11111/tier", json={"tier": "S"})
    assert r.status_code == 200
    assert r.json()["tier"] == "S"
    assert repo.get_paper("arxiv_2603.11111").tier == "S"
    assert repo.get_paper("arxiv_2603.11111").status == "QUEUED"


# ---- 5. staging 保存批注并校验 ----
def test_staging_save_and_validate(ctx):
    repo = ctx["repo"]
    _seed_paper(repo, "arxiv_2603.12345", tier="S", status="QUEUED")
    staging = ctx["cfg"].workspace_path / "staging" / "2026-03-16"
    staging.mkdir(parents=True, exist_ok=True)
    md = staging / "arxiv_2603.12345.md"
    md.write_text(VALID_MD, encoding="utf-8")
    c = ctx["client"]

    r = c.get("/api/staging")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1

    content = md.read_text(encoding="utf-8") + "\n\n> 💡 个人思考：值得复现。\n"
    r = c.put("/api/staging/arxiv_2603.12345", json={"content": content})
    assert r.status_code == 200
    assert r.json()["valid"] is True
    assert "个人思考" in md.read_text(encoding="utf-8")


# ---- 6. 非法配置 422 且不破坏原文件 ----
def test_settings_invalid_keeps_file(ctx):
    tmp_cfg = ctx["tmp_cfg"]
    original = tmp_cfg.read_text(encoding="utf-8")
    c = ctx["client"]

    data = yaml.safe_load(original)
    data["interest_profile"]["thresholds"]["tier_s"] = 10  # < tier_a(25)
    r = c.put("/api/settings", json={"config": data})
    assert r.status_code == 422
    assert tmp_cfg.read_text(encoding="utf-8") == original  # 未被破坏

    # 合法配置可保存
    data["interest_profile"]["thresholds"]["tier_s"] = 60
    r = c.put("/api/settings", json={"config": data})
    assert r.status_code == 200
    assert r.json()["saved"] is True


def test_dashboard_charts_use_fixed_container():
    """回归锁：Chart.js canvas 必须置于固定高度容器，禁止 height 属性导致无限增高。"""
    from paperflow.web.app import STATIC_DIR

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    # canvas 不得带 height 属性（曾导致 responsive 重建时高度累加到数千像素）
    assert '<canvas id="venueChart" height=' not in html
    assert '<canvas id="trendChart" height=' not in html
    # 两个 canvas 必须包在 chart-box 内
    for chart_id in ("venueChart", "trendChart"):
        assert f'<div class="chart-box"><canvas id="{chart_id}"></canvas></div>' in html
    # CSS 必须固定容器高度并强制 canvas 铺满
    assert ".chart-box{" in css.replace(" ", "")
    assert "height:240px" in css.replace(" ", "")


def test_settings_merge_preserves_new_nodes(ctx):
    """回归锁：不完整 config 回传（缺 topic_search/analyzer）不应删除磁盘上已有节点。"""
    tmp_cfg = ctx["tmp_cfg"]
    c = ctx["client"]

    # 读磁盘完整配置（含 topic_search/analyzer/download_policy）
    full = yaml.safe_load(tmp_cfg.read_text(encoding="utf-8"))
    assert "topic_search" in full
    assert "analyzer" in full

    # 模拟旧前端：只回传 interest_profile + publish，缺新节点
    partial = {
        "interest_profile": full["interest_profile"],
        "publish": full["publish"],
    }
    r = c.put("/api/settings", json={"config": partial})
    assert r.status_code == 200

    # 磁盘配置必须仍保留 topic_search/analyzer/download_policy
    saved = yaml.safe_load(tmp_cfg.read_text(encoding="utf-8"))
    assert "topic_search" in saved
    assert "analyzer" in saved
    assert "download_policy" in saved
    assert len(saved["topic_search"]["subscriptions"]) >= 3
