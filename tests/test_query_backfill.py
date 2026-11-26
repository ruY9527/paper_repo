"""方向与关键词补录：去重漏洞修复 + query-backfill 端到端验收。"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.fetchers.base import BaseFetcher, RawPaper
from paperflow.pipeline.backfill import BackfillEngine, ingest_papers
from paperflow.web.app import create_app


def _paper(title="A Repeated Paper", doi="10.1/repeat") -> RawPaper:
    return RawPaper(title=title, authors=["A"], venue="CVPR", pub_year=2026,
                    pub_date="2026-01-01", doi=doi, abstract="x", source="arxiv")


def test_ingest_same_uid_title_variant_no_duplicate(tmp_path):
    """UID 相同、标题略变时，第二次补录不重复入库且不崩溃（原 UNIQUE 漏洞）。"""
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    n1, _, _ = ingest_papers([_paper()], repo, cfg)
    # 同 DOI，标题变化 → UID 相同
    n2, _, _ = ingest_papers([_paper(title="A Repeated Paper v2")], repo, cfg)
    assert n1 == 1 and n2 == 0
    assert len(repo.get_all_papers()) == 1
    # 原始标题保留（不被 v2 覆盖）
    assert repo.get_all_papers()[0].title == "A Repeated Paper"


def test_query_history_ledger(tmp_path):
    """方向检索台账：记录 query 的检索时间与新增数。"""
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    repo.add_topic_search_run(task_id="t1", topic_name="agent", raw_query="agent",
        expanded_query="agent", primary_year=2026, fallback_year=2025,
        primary_count=5, fallback_count=2, filtered_old_count=1,
        new_inserted_count=7, status="SUCCESS")
    h = repo.get_query_history("agent")
    assert len(h) == 1 and h[0]["new_inserted_count"] == 7


def test_query_backfill_endpoints(tmp_path):
    """query-backfill 端点：空 query 拒绝；历史查询可用。"""
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    c = TestClient(create_app(cfg, PaperRepository(cfg.db_path)))
    assert c.post("/api/tasks/query-backfill", json={"query": ""}).status_code == 422
    assert c.get("/api/tasks/query-history?q=agent").status_code == 200
