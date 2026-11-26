"""历史操作记录删除验收。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from paperflow.config import load_example_config
from paperflow.db.repository import PaperRepository
from paperflow.web.app import create_app


def _seed(repo, n):
    conn = repo._connect()
    for i in range(n):
        conn.execute("INSERT INTO run_logs (command, started_at, status) VALUES (?,?,?)",
                     ("fetch", "2026-11-23", "SUCCESS"))
    conn.commit(); conn.close()


def test_delete_single_and_clear(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path); _seed(repo, 5)
    c = TestClient(create_app(cfg, repo))
    first = c.get("/api/tasks/history").json()["items"][0]["id"]
    assert c.delete(f"/api/tasks/history/{first}").json()["deleted"] == 1
    assert c.get("/api/tasks/history").json()["total"] == 4
    assert c.delete("/api/tasks/history?keep=2").json()["deleted"] == 2
    assert c.get("/api/tasks/history").json()["total"] == 2
    assert c.delete("/api/tasks/history?keep=0").json()["deleted"] == 2
    assert c.get("/api/tasks/history").json()["total"] == 0


def test_delete_removes_log_file(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path); _seed(repo, 1)
    log = cfg.workspace_path / "logs" / "task_run_1.log"
    log.parent.mkdir(parents=True, exist_ok=True); log.write_text("x", encoding="utf-8")
    c = TestClient(create_app(cfg, repo))
    c.delete("/api/tasks/history/1")
    assert not log.exists()
