"""Phase 10：方向精准检索 REST API（07 文档第 6.1 节）。

只读 API 直接返回结果；写操作（search / run-subscriptions）走 TaskManager
互斥锁 + SSE 实时进度，终态事件携带分年结果摘要供前端展示。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from ...config import PROJECT_ROOT, AppConfig, TopicSearchConfig, TopicSubscriptionConfig
from ...pipeline.topic_query import parse_topic_query
from ..state import get_manager
from ..task_manager import TaskBusyError, TaskManager, reload_config
import os
import shutil

router = APIRouter(prefix="/api/topics", tags=["topics"])

# settings 路由可能 monkeypatch 的 config 路径；这里统一从 PROJECT_ROOT 读取
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def _result_payload(result) -> dict[str, Any]:
    """TopicSearchResult -> 可 JSON 序列化的分年摘要（供 SSE 终态事件携带）。"""
    def paper_view(p) -> dict[str, Any]:
        return {
            "paper_uid": p.paper_uid, "title": p.title, "venue": p.venue,
            "pub_year": p.pub_year, "pub_date": p.pub_date, "tier": p.tier,
            "score": p.score, "paper_url": p.paper_url, "code_url": p.code_url,
            "abstract": (p.abstract or "")[:300],
            "bibtex": "",
        }

    return {
        "topic_name": result.topic_name,
        "raw_query": result.raw_query,
        "expanded_query": result.expanded_query,
        "primary_year": result.primary_year,
        "fallback_year": result.fallback_year,
        "primary_count": result.primary_count,
        "fallback_count": result.fallback_count,
        "filtered_old_count": result.filtered_old_count,
        "relaxed_match_count": result.relaxed_match_count,
        "new_inserted_count": result.new_inserted_count,
        "papers": [paper_view(p) for p in result.papers],
    }


# ---------- 只读 API ----------

@router.post("/preview-query")
def preview_query(body: dict[str, Any] = Body(...),
                  manager: TaskManager = Depends(get_manager)):
    query = body.get("query", "")
    if not query or not str(query).strip():
        raise HTTPException(status_code=422, detail="query 不能为空")
    parsed = parse_topic_query(str(query), manager.config)
    return {
        "raw_query": parsed.raw_query,
        "expanded_query": parsed.expanded_text(),
        "arxiv_query": parsed.arxiv_query(),
        "openalex_query": parsed.openalex_query(),
        "groups": [{"raw": g.raw, "terms": g.terms} for g in parsed.groups],
        "primary_year": manager.config.primary_year,
        "fallback_year": manager.config.fallback_year,
        "min_allowed_year": manager.config.min_allowed_year,
    }


@router.get("/subscriptions")
def get_subscriptions(manager: TaskManager = Depends(get_manager)):
    cfg = manager.config
    papers = manager.repo.get_all_papers()
    items = []
    for sub in cfg.topic_search.subscriptions:
        subset = []
        for p in papers:
            import json
            try:
                tags = json.loads(getattr(p, "topic_tags_json", "[]") or "[]")
            except json.JSONDecodeError:
                tags = []
            if sub.name in tags:
                subset.append(p)
        parsed = parse_topic_query(sub.query, cfg)
        items.append({
            "name": sub.name, "slug": sub.slug, "query": sub.query,
            "enabled": sub.enabled, "limit": sub.limit,
            "only_primary_year": sub.only_primary_year,
            "top_venues_only": sub.top_venues_only,
            "expanded_query": parsed.expanded_text(),
            "primary_count": sum(1 for p in subset if p.pub_year == cfg.primary_year),
            "fallback_count": sum(1 for p in subset if p.pub_year == cfg.fallback_year),
        })
    return {"items": items, "synonym_dict": cfg.topic_search.synonym_dict}


@router.put("/subscriptions")
def put_subscriptions(body: dict[str, Any] = Body(...),
                      manager: TaskManager = Depends(get_manager)):
    """在线增删改常驻方向：Pydantic 校验 -> 备份 -> 原子写回 config.yaml。"""
    subs_raw = body.get("subscriptions")
    synonyms_raw = body.get("synonym_dict")
    if not isinstance(subs_raw, list):
        raise HTTPException(status_code=422, detail="subscriptions 必须是数组")

    # 用当前配置构造候选并从磁盘读原始配置，保留其他节点
    # 剥离前端回传的只读统计字段（expanded_query/primary_count/fallback_count），
    # 否则 extra=forbid 的 TopicSubscriptionConfig 会拒绝这些字段导致 422。
    _SUB_FIELDS = {"name", "slug", "query", "enabled", "limit",
                   "only_primary_year", "top_venues_only"}
    try:
        validated = [
            TopicSubscriptionConfig.model_validate({k: v for k, v in s.items() if k in _SUB_FIELDS})
            for s in subs_raw
        ]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"订阅方向校验失败: {exc}")

    data = __import__("yaml").safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    data.setdefault("topic_search", {})
    data["topic_search"]["subscriptions"] = [s.model_dump() for s in validated]
    if isinstance(synonyms_raw, dict):
        data["topic_search"]["synonym_dict"] = {
            str(k): [str(x) for x in v] for k, v in synonyms_raw.items()
        }
    # 整体 Pydantic 校验
    try:
        AppConfig.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"配置校验失败: {exc}")

    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, CONFIG_PATH.with_suffix(".yaml.bak"))
    tmp = CONFIG_PATH.with_suffix(".yaml.tmp")
    tmp.write_text(
        __import__("yaml").safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(tmp, CONFIG_PATH)
    reload_config(manager, CONFIG_PATH)
    return {"saved": True, "count": len(validated)}


@router.get("/history")
def get_history(limit: int = 50, offset: int = 0,
                manager: TaskManager = Depends(get_manager)):
    rows = manager.repo.get_topic_search_runs(limit=limit, offset=offset)
    return {"items": rows, "limit": limit, "offset": offset}


# ---------- 写操作 runner ----------

def _run_search(ctx: dict):
    manager: TaskManager = ctx["manager"]
    params = ctx["params"]
    emit = ctx["emit"]
    from ...fetchers.topic_fetcher import TopicSearchEngine

    emit(stage="parsing", percent=5, message="解析方向查询式…")
    engine = TopicSearchEngine(manager.config, manager.repo)

    # 阶段 → 整体进度锚点（5~95%），避免 fetcher 内部的篇数进度导致进度条跳变
    _STAGE_PCT = {
        "fetching_primary": 20, "fetching_fallback": 45, "ingesting": 70,
        "done": 80, "downloading_pdf": 88, "downloaded_pdf": 95,
    }
    def _progress(**kw):
        stage = kw.get("stage", "")
        if stage in _STAGE_PCT:
            kw["percent"] = _STAGE_PCT[stage]
        # 清掉 fetcher 传来的 current/total，避免 task_manager 用篇数覆盖整体百分比
        kw.pop("current", None); kw.pop("total", None)
        emit(**kw)

    result = engine.search(
        params.get("query", ""),
        topic_name=params.get("topic_name") or params.get("query", ""),
        limit=int(params.get("limit", 20)),
        only_primary_year=bool(params.get("only_primary_year", False)),
        top_venues_only=bool(params.get("top_venues_only", False)),
        sources=params.get("sources") or None,
        auto_download=bool(params.get("auto_download", True)),
        progress_cb=_progress,
        cancel_event=ctx.get("cancel_event"),
    )
    # 审计落库
    manager.repo.add_topic_search_run(
        task_id=ctx["task_id"],
        topic_name=result.topic_name, raw_query=result.raw_query,
        expanded_query=result.expanded_query,
        primary_year=result.primary_year, fallback_year=result.fallback_year,
        primary_count=result.primary_count, fallback_count=result.fallback_count,
        filtered_old_count=result.filtered_old_count,
        new_inserted_count=result.new_inserted_count,
        status=result.status,
    )
    payload = _result_payload(result)
    emit(stage="result", percent=100, message="检索完成", result=payload)
    return payload


def _run_subscriptions(ctx: dict):
    manager: TaskManager = ctx["manager"]
    params = ctx.get("params") or {}
    emit = ctx["emit"]
    from ...fetchers.topic_fetcher import TopicSearchEngine

    subs = [s for s in manager.config.topic_search.subscriptions if s.enabled]
    n = max(1, len(subs))
    emit(stage="preparing", percent=5, message=f"准备执行 {len(subs)} 个订阅方向")
    results = []
    for i, sub in enumerate(subs):
        base = int((i / n) * 90)
        emit(stage=f"topic_{sub.slug}", percent=base,
             message=f"正在检索方向：{sub.name}（{i+1}/{len(subs)}）")
        engine = TopicSearchEngine(manager.config, manager.repo)
        def _sub_progress(_base=base, **kw):
            # 批量追新：每个方向的阶段进度限制在自己的 1/n 区间内
            stage_pct = {"fetching_primary": 10, "fetching_fallback": 25,
                         "ingesting": 40, "done": 50, "downloading_pdf": 60,
                         "downloaded_pdf": 75}.get(kw.get("stage", ""), 5)
            kw["percent"] = min(95, _base + int(stage_pct / n))
            kw.pop("current", None); kw.pop("total", None)
            emit(**kw)
        result = engine.search(
            sub.query, topic_name=sub.name, limit=sub.limit,
            only_primary_year=sub.only_primary_year,
            top_venues_only=sub.top_venues_only,
            auto_download=bool(params.get("auto_download", True)),
            progress_cb=_sub_progress,
            cancel_event=ctx.get("cancel_event"),
        )
        manager.repo.add_topic_search_run(
            task_id=ctx["task_id"], topic_name=result.topic_name,
            raw_query=result.raw_query, expanded_query=result.expanded_query,
            primary_year=result.primary_year, fallback_year=result.fallback_year,
            primary_count=result.primary_count, fallback_count=result.fallback_count,
            filtered_old_count=result.filtered_old_count,
            new_inserted_count=result.new_inserted_count, status=result.status,
        )
        results.append(_result_payload(result))
    emit(stage="result", percent=100, message="全部订阅方向检索完成", results=results)
    return {"count": len(results), "results": results}


_TOPIC_RUNNERS = {"topic-search": _run_search, "topic-run": _run_subscriptions}


def _submit(manager: TaskManager, command: str, params: dict):
    def runner(ctx):
        ctx["manager"] = manager
        return _TOPIC_RUNNERS[command](ctx)

    try:
        task = manager.submit(command, runner, params)
    except TaskBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"task_id": task.task_id, "command": command, "status": task.status}


@router.post("/search")
def start_search(body: dict[str, Any] = Body(...),
                 manager: TaskManager = Depends(get_manager)):
    if not body.get("query"):
        raise HTTPException(status_code=422, detail="query 不能为空")
    return _submit(manager, "topic-search", body)


@router.post("/run-subscriptions")
def run_subscriptions(body: dict[str, Any] = Body(default={}),
                      manager: TaskManager = Depends(get_manager)):
    return _submit(manager, "topic-run", body)
