"""链路闭环验收：历史分页 total + 队列导出合并防覆盖。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.queue_exporter import export_queue
from paperflow.web.app import create_app
from fastapi.testclient import TestClient


def test_history_pagination_total(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    conn = repo._connect()
    for i in range(5):
        conn.execute("INSERT INTO run_logs (command, started_at, status, new_count, tier_s_count, tier_a_count) "
                     "VALUES (?,?,?,?,?,?)", ("fetch", "2026-05-01", "SUCCESS", i, 0, 0))
    conn.commit(); conn.close()
    c = TestClient(create_app(cfg, repo))
    d = c.get("/api/tasks/history?limit=2&offset=0").json()
    assert d["total"] == 5 and len(d["items"]) == 2
    d2 = c.get("/api/tasks/history?limit=2&offset=2").json()
    assert d2["items"][0]["id"] != d["items"][0]["id"]


def test_export_queue_merges_manifest(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    for uid in ("p1", "p2"):
        repo.upsert_paper(PaperRecord(paper_uid=uid, title=uid, normalized_title=uid,
            authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-23",
            source="arxiv", tier="S", status=PaperStatus.DOWNLOADED.value,
            abstract="abstract " * 20))
    date = "2026-11-23"
    r1 = export_queue(cfg, repo, target_date=date)
    assert r1["count"] == 2
    # 再导出一次：无新候选，但已有 manifest 不应被清空
    r2 = export_queue(cfg, repo, target_date=date)
    assert r2["count"] == 0
    assert r2["total"] == 2
    import json
    mf = json.loads((cfg.workspace_path / "queue" / date / "queue_manifest.json").read_text(encoding="utf-8"))
    assert mf["count"] == 2
