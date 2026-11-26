"""Phase 9 验收：本地 Bare Git 仓库离线模拟全链路（06 文档第 6 节）。"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperflow.config import load_example_config
from paperflow.db.repository import PaperRepository
from paperflow.publisher.git_service import BlogGitService, UnsafePathError
from paperflow.web.app import create_app


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"}
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=str(cwd),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        shell=False, env=env,
    )


@pytest.fixture
def git_ctx(tmp_path, monkeypatch):
    """创建 bare 远端 + 克隆的 paper_repo，并接入隔离的 app/repo。"""
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))

    repo_dir = tmp_path / "paper_repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "t@t.com")
    _git(repo_dir, "config", "user.name", "T")
    (repo_dir / "docs").mkdir()
    (repo_dir / "docs" / "index.md").write_text("# init\n", encoding="utf-8")
    _git(repo_dir, "add", "-A")
    _git(repo_dir, "commit", "-m", "init")
    _git(repo_dir, "remote", "add", "origin", str(bare))
    _git(repo_dir, "push", "-u", "origin", "main")

    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    cfg.project.paper_repo_dir = str(repo_dir)
    cfg.publish.auto_git_commit = False
    repo = PaperRepository(cfg.db_path)
    app = create_app(cfg, repo)
    client = TestClient(app)
    svc = BlogGitService(repo_dir, repo=repo, remote_name="origin")
    return {"tmp": tmp_path, "bare": bare, "repo_dir": repo_dir,
            "cfg": cfg, "repo": repo, "client": client, "svc": svc}


def _wait_task(client, task_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if client.get("/api/tasks/active").json().get("active") is False:
            return
        time.sleep(0.05)


# ---- 1. 状态与变更检测（含中文文件名） ----
def test_status_detects_chinese_filenames(git_ctx):
    c = git_ctx["client"]
    d = git_ctx["repo_dir"] / "docs"
    (d / "中文论文.md").write_text("# 中文标题\n内容", encoding="utf-8")
    (d / "english-paper.md").write_text("# English\n", encoding="utf-8")

    r = c.get("/api/git/status")
    assert r.status_code == 200
    data = r.json()
    assert data["is_git_repo"] is True
    assert data["branch"] == "main"
    assert data["has_changes"] is True
    paths = [x["path"] for x in data["changes"]]
    assert "docs/中文论文.md" in paths       # 无乱码
    assert "docs/english-paper.md" in paths
    assert data["added"] >= 2


# ---- 2. Diff 预览与路径安全 ----
def test_diff_and_path_safety(git_ctx):
    c = git_ctx["client"]
    (git_ctx["repo_dir"] / "docs" / "diff-me.md").write_text(
        "line1\nline2\nline3", encoding="utf-8"
    )
    r = c.get("/api/git/diff", params={"path": "docs/diff-me.md"})
    assert r.status_code == 200
    assert "line1" in r.json()["content"]

    # 概览 diff
    r = c.get("/api/git/diff")
    assert r.status_code == 200
    assert "changes" in r.json()

    # 越界路径被拒
    r = c.get("/api/git/diff", params={"path": "../state.db"})
    assert r.status_code in (400, 403)

    # 直接调用服务也应拒绝
    with pytest.raises(UnsafePathError):
        git_ctx["svc"].get_diff("../state.db")


# ---- 3. 一键提交并推送 + SSE + 审计 + 远端确认 ----
def test_commit_push_sse_audit(git_ctx):
    c = git_ctx["client"]
    bare, repo_dir = git_ctx["bare"], git_ctx["repo_dir"]
    (repo_dir / "docs" / "new-paper.md").write_text("# New Paper\n", encoding="utf-8")

    before_logs = len(git_ctx["repo"].get_git_push_logs())
    r = c.post("/api/git/commit-push", json={"message": "docs: add new paper", "push": True})
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    _wait_task(c, task_id)

    # SSE 历史含 SUCCESS
    sse = c.get(f"/api/tasks/{task_id}/stream")
    assert "SUCCESS" in sse.text

    # 远端收到提交
    log = _git(bare, "log", "-1", "--format=%s")
    assert log.returncode == 0
    assert "add new paper" in log.stdout

    # 审计表新增 SUCCESS + pushed=1
    logs = git_ctx["repo"].get_git_push_logs()
    assert len(logs) == before_logs + 1
    assert logs[0]["status"] == "SUCCESS"
    assert logs[0]["pushed"] == 1
    assert logs[0]["commit_hash"]

    # 状态变为干净、ahead=0
    st = c.get("/api/git/status").json()
    assert st["has_changes"] is False
    assert st["ahead_count"] == 0


# ---- 4. 提交历史与详情 + 非法 hash 防护 ----
def test_commits_history_and_detail(git_ctx):
    c = git_ctx["client"]
    (git_ctx["repo_dir"] / "docs" / "hist.md").write_text("# History\n", encoding="utf-8")
    r = c.post("/api/git/commit-push", json={"message": "docs: history test", "push": True})
    _wait_task(c, r.json()["task_id"])

    r = c.get("/api/git/commits")
    assert r.status_code == 200
    commits = r.json()["items"]
    assert len(commits) >= 2
    target = next(x for x in commits if "history test" in x["message"])
    assert target["is_pushed"] is True
    assert target["short_hash"]
    assert target["date_iso"]

    detail = c.get(f"/api/git/commits/{target['hash']}")
    assert detail.status_code == 200
    paths = [f["path"] for f in detail.json()["files"]]
    assert "docs/hist.md" in paths

    # 关键词检索
    r = c.get("/api/git/commits", params={"q": "history"})
    assert any("history test" in x["message"] for x in r.json()["items"])

    # 非法 hash（命令注入串）被拒
    r = c.get("/api/git/commits/abc%3B%20rm%20-rf")
    assert r.status_code in (400, 422)


# ---- 5. 远端领先冲突保护（pull --rebase） ----
def test_remote_ahead_pull_protection(git_ctx):
    c = git_ctx["client"]
    bare, tmp = git_ctx["bare"], git_ctx["tmp"]

    # 另一临时克隆先推一条提交
    other = tmp / "other_clone"
    _git(tmp, "clone", str(bare), str(other))
    _git(other, "config", "user.email", "t@t.com")
    _git(other, "config", "user.name", "T")
    (other / "docs" / "remote-only.md").write_text("# remote\n", encoding="utf-8")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "remote change")
    _git(other, "push", "origin", "main")

    # fetch 后 behind_count == 1
    git_ctx["svc"]._run(["fetch", "origin"])
    st = c.get("/api/git/status").json()
    assert st["behind_count"] == 1

    # 拉rebase 同步
    r = c.post("/api/git/pull", json={})
    assert r.status_code == 200
    _wait_task(c, r.json()["task_id"])
    st2 = c.get("/api/git/status").json()
    assert st2["behind_count"] == 0
    assert (git_ctx["repo_dir"] / "docs" / "remote-only.md").exists()


# ---- 附加：SSH 检测在 file:// 远端下优雅返回 ----
def test_ssh_check_graceful(git_ctx):
    r = git_ctx["client"].post("/api/git/test-ssh")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data and "message" in data
