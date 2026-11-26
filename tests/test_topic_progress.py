"""方向检索进度条验收：阶段→整体进度映射，无 current/total 跳变。"""

from __future__ import annotations

from paperflow.web.routes.topics import _run_search


def test_stage_progress_mapping(monkeypatch):
    """_run_search 内嵌的 _progress 把 fetcher 阶段映射到 5~95%。"""
    emitted = []
    # 用一个假 engine 捕获 progress_cb 行为
    class FakeResult:
        topic_name="t"; raw_query="q"; expanded_query="q"; primary_year=2026
        fallback_year=2025; primary_count=0; fallback_count=0; filtered_old_count=0
        relaxed_match_count=0; new_inserted_count=0; status="SUCCESS"; papers=[]
    class FakeEngine:
        def __init__(self, *a, **k): pass
        def search(self, *a, **kw):
            cb = kw.get("progress_cb")
            if cb:
                cb(stage="fetching_primary", current=1, total=20, message="p")
                cb(stage="ingesting", current=3, total=3, message="i")
            return FakeResult()
    import paperflow.fetchers.topic_fetcher as tf
    monkeypatch.setattr(tf, "TopicSearchEngine", FakeEngine)

    ctx = {
        "manager": type("M", (), {
            "config": type("C", (), {"topic_search": type("T", (), {"synonym_dict": {}})})(),
            "repo": type("R", (), {"add_topic_search_run": lambda self, **k: None})(),
        })(),
        "params": {"query": "agent", "limit": 20},
        "task_id": "t1",
        "emit": lambda **kw: emitted.append(kw),
        "cancel_event": None,
    }
    _run_search(ctx)
    pcts = {e.get("stage"): e.get("percent") for e in emitted}
    assert pcts["parsing"] == 5
    assert pcts["fetching_primary"] == 20   # 阶段映射，非 current/total 算出的 5%
    assert pcts["ingesting"] == 70
    assert pcts["result"] == 100
    # 不应残留 current/total 导致 task_manager 覆盖百分比
    assert all("current" not in e and "total" not in e
               for e in emitted if e.get("stage") in ("fetching_primary", "ingesting"))
