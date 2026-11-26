"""任务 API：启动 fetch/export-queue/publish/clean，SSE 流，取消，历史。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ...db.models import PaperStatus
from ..state import get_manager
from ..task_manager import (
    TaskBusyError,
    TaskManager,
    TaskNotFoundError,
    TaskCancelledError,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _emit(emit, stage, current, total, message, level="INFO"):
    emit(stage=stage, current=current, total=total, message=message, level=level)


# ---------- runner 实现 ----------

def run_fetch(ctx: dict):
    manager: TaskManager = ctx["manager"]
    p = ctx["params"]
    emit, cancel_event = ctx["emit"], ctx["cancel_event"]
    cfg, repo = manager.config, manager.repo

    from ...pipeline.backfill import BackfillEngine
    from ...pipeline.downloader import download_s_papers

    engine = BackfillEngine(cfg, repo)
    _emit(emit, "fetching", 0, 0, "开始拉取论文")

    venues = p.get("venues") or None
    sources = p.get("sources") or None
    dry_run = bool(p.get("dry_run"))
    if p.get("date_from") and p.get("date_to"):
        from datetime import date
        result = engine.run_manual(
            date.fromisoformat(p["date_from"]), date.fromisoformat(p["date_to"]),
            venues=venues, sources=sources, dry_run=dry_run,
        )
    else:
        result = engine.run_auto(dry_run=dry_run)

    if cancel_event.is_set():
        raise TaskCancelledError()

    if dry_run:
        _emit(emit, "dry_run", result.new_papers, result.new_papers,
              f"试算完成：新增 {result.new_papers} 篇；未写库、未下载")
        return {
            "new_papers": result.new_papers, "tier_s": result.tier_s,
            "tier_a": result.tier_a, "slices": len(result.slices),
            "downloaded": 0, "queued": 0, "dry_run": True,
        }

    _emit(emit, "scoring", result.new_papers, result.new_papers,
          f"拉取完成，新增 {result.new_papers} 篇，开始打分")
    _emit(emit, "downloading_pdf", 0, 0, "检查 S 级论文 PDF")
    dl = download_s_papers(cfg, repo)
    queued = 0
    if bool(p.get("auto_export", True)):
        from ...pipeline.queue_exporter import export_queue
        queued = export_queue(cfg, repo, target_date=p.get("date")).get("count", 0)
    return {
        "new_papers": result.new_papers, "tier_s": result.tier_s,
        "tier_a": result.tier_a, "slices": len(result.slices),
        "downloaded": dl.get("downloaded", 0), "queued": queued, "dry_run": False,
    }


def run_export_queue(ctx: dict):
    manager: TaskManager = ctx["manager"]
    emit = ctx["emit"]
    from ...pipeline.queue_exporter import export_queue
    _emit(emit, "exporting", 0, 0, "导出分析队列")
    result = export_queue(manager.config, manager.repo,
                          target_date=ctx["params"].get("date"))
    _emit(emit, "exported", result["count"], result["count"],
          f"导出 {result['count']} 篇任务")
    return result


def run_publish(ctx: dict):
    manager: TaskManager = ctx["manager"]
    p = ctx["params"]
    emit = ctx["emit"]
    from ...publisher.sync_blog import publish
    _emit(emit, "validating", 0, 0, "校验待审 Markdown")
    result = publish(
        manager.config, manager.repo,
        push=bool(p.get("push")), clean=bool(p.get("clean")),
        dry_run=bool(p.get("dry_run")), target_date=p.get("date"),
    )
    _emit(emit, "published", result["passed"], result["validated"],
          f"发布完成，通过 {result['passed']} 篇")
    return result


def run_clean(ctx: dict):
    manager: TaskManager = ctx["manager"]
    p = ctx["params"]
    emit = ctx["emit"]
    from ...pipeline.cleaner import clean_papers
    _emit(emit, "cleaning", 0, 0, "扫描可清理文件")
    result = clean_papers(
        manager.config, manager.repo,
        include_staged=bool(p.get("include_staged")),
        dry_run=bool(p.get("dry_run")),
    )
    _emit(emit, "cleaned", result["cleaned"], result["cleaned"],
          f"清理 {result['cleaned']} 篇，释放 {result['freed_mb']} MB")
    return result


def run_pipeline(ctx: dict):
    """一键全自动流水线：采集 → 导出队列 → AI 解析 → 校验发布 → 清理。

    全部复用既有模块，单任务内串行执行，逐阶段 emit 进度；任一阶段支持取消。
    engine 由参数指定（claude_cli / harness_cli / openai_api），默认取配置默认后端。
    """
    manager: TaskManager = ctx["manager"]
    p = ctx["params"]
    emit, cancel_event = ctx["emit"], ctx["cancel_event"]
    cfg, repo = manager.config, manager.repo

    from ...pipeline.backfill import BackfillEngine
    from ...pipeline.downloader import download_s_papers
    from ...pipeline.queue_exporter import export_queue
    from ...analyzers.runner import AnalyzerRunner
    from ...publisher.sync_blog import publish

    steps = p["steps"] if "steps" in p else ["fetch", "queue", "analyze", "publish"]
    engine = p.get("engine") or cfg.analyzer.default_backend
    summary: dict[str, Any] = {}

    def cancelled():
        return cancel_event is not None and cancel_event.is_set()

    # 1) 采集 + 打分 + 下载
    if "fetch" in steps:
        if cancelled():
            raise TaskCancelledError()
        _emit(emit, "fetching", 0, 0, "[1/4] 采集最新论文")
        fe = BackfillEngine(cfg, repo)
        result = fe.run_auto()
        dl = download_s_papers(cfg, repo)
        summary["fetch"] = {"new": result.new_papers, "downloaded": dl.get("downloaded", 0)}
        _emit(emit, "fetched", 1, 4, f"采集完成：新增 {result.new_papers} 篇，下载 {dl.get('downloaded',0)} 篇")

    # 2) 方向追新（可选）
    if p.get("topic_run") or "topics" in steps:
        if cancelled():
            raise TaskCancelledError()
        _emit(emit, "topics", 0, 0, "[1.5/4] 方向订阅追新")
        from ...fetchers.topic_fetcher import TopicSearchEngine
        subs = [s for s in cfg.topic_search.subscriptions if s.enabled]
        topic_new = 0
        for s in subs:
            if cancelled():
                raise TaskCancelledError()
            tr = TopicSearchEngine(cfg, repo).search(
                s.query, topic_name=s.name, limit=s.limit,
                only_primary_year=s.only_primary_year,
                top_venues_only=s.top_venues_only, auto_download=True,
            )
            topic_new += tr.new_inserted_count
        summary["topics"] = {"new": topic_new}

    # 3) 导出队列
    if "queue" in steps:
        if cancelled():
            raise TaskCancelledError()
        _emit(emit, "queueing", 2, 4, "[2/4] 导出分析队列")
        qr = export_queue(cfg, repo, target_date=p.get("date"))
        summary["queue"] = {"count": qr.get("count", 0)}
        _emit(emit, "queued", 2, 4, f"队列导出 {qr.get('count',0)} 篇")

    # 4) AI 解析（选定引擎）
    if "analyze" in steps:
        if cancelled():
            raise TaskCancelledError()
        _emit(emit, "analyzing", 3, 4, f"[3/4] AI 解析（{engine}）")
        runner = AnalyzerRunner(cfg, repo, backend=engine,
                                model=p.get("model"), provider=p.get("provider"))
        uids = p.get("paper_uids") or [x.paper_uid for x in
                repo.get_papers_by_status(PaperStatus.QUEUED.value)]
        if p.get("limit"):
            uids = uids[: int(p["limit"])]
        results = runner.run_batch(
            uids, task_id=ctx["task_id"], cancel_event=cancel_event,
            progress_cb=lambda **kw: emit(**kw),
        )
        ok = sum(1 for r in results if r.ok)
        summary["analyze"] = {"total": len(results), "success": ok, "engine": engine}
        _emit(emit, "analyzed", 3, 4, f"解析完成：成功 {ok}/{len(results)} 篇")

    # 5) 校验 + 发布
    if "publish" in steps:
        if cancelled():
            raise TaskCancelledError()
        _emit(emit, "publishing", 4, 4, "[4/4] 校验并发布到博客")
        pub = publish(cfg, repo, push=bool(p.get("push")), clean=bool(p.get("clean")),
                      dry_run=bool(p.get("dry_run")))
        summary["publish"] = {"passed": pub.get("passed", 0)}
        _emit(emit, "published", 4, 4, f"发布完成：通过 {pub.get('passed',0)} 篇")

    emit(stage="result", percent=100, message="全自动流水线完成", result=summary)
    return summary


def run_query_backfill(ctx: dict):
    """按方向/关键词补录：复用 TopicSearchEngine 的时效策略与去重，写检索审计。"""
    manager: TaskManager = ctx["manager"]
    p = ctx["params"]
    emit, cancel_event = ctx["emit"], ctx["cancel_event"]
    from ...fetchers.topic_fetcher import TopicSearchEngine

    query = str(p.get("query", "")).strip()
    limit = int(p.get("limit", 20) or 20)
    only_primary = bool(p.get("only_primary_year", False))
    top_only = bool(p.get("top_venues_only", False))

    # 检索前提示：该方向是否检索过（去重透明化）
    history = manager.repo.get_query_history(query, limit=1)
    if history:
        h = history[0]
        emit(stage="history", level="INFO",
             message=f"该方向上次检索于 {h['created_at']}，新增 {h['new_inserted_count']} 篇；本次仅补充新论文")

    emit(stage="searching", current=0, total=limit,
         message=f"按方向检索补录：{query}（2026 优先 → 2025 兜底）")
    engine = TopicSearchEngine(manager.config, manager.repo)
    result = engine.search(
        query, topic_name=p.get("topic_name") or query, limit=limit,
        only_primary_year=only_primary, top_venues_only=top_only,
        auto_download=bool(p.get("auto_download", True)),
        progress_cb=lambda **kw: emit(**kw),
        cancel_event=cancel_event,
    )
    # 写检索审计（与方向检索页统一台账）
    manager.repo.add_topic_search_run(
        task_id=ctx["task_id"], topic_name=result.topic_name,
        raw_query=result.raw_query, expanded_query=result.expanded_query,
        primary_year=result.primary_year, fallback_year=result.fallback_year,
        primary_count=result.primary_count, fallback_count=result.fallback_count,
        filtered_old_count=result.filtered_old_count,
        new_inserted_count=result.new_inserted_count, status=result.status,
    )
    summary = {
        "query": query, "new": result.new_inserted_count,
        "primary": result.primary_count, "fallback": result.fallback_count,
        "filtered_old": result.filtered_old_count,
    }
    emit(stage="result", percent=100,
         message=f"补录完成：新增 {result.new_inserted_count} 篇（2026:{result.primary_count} / 兜底:{result.fallback_count} / 过滤:{result.filtered_old_count}）",
         result=summary)
    return summary


RUNNERS = {
    "fetch": run_fetch,
    "export-queue": run_export_queue,
    "publish": run_publish,
    "clean": run_clean,
    "pipeline": run_pipeline,
    "query-backfill": run_query_backfill,
}

# 互斥任务集合（这些命令之间互斥）
WRITE_COMMANDS = set(RUNNERS.keys())


def _submit(manager: TaskManager, command: str, params: dict):
    def runner(ctx):
        ctx["manager"] = manager
        return RUNNERS[command](ctx)

    try:
        task = manager.submit(command, runner, params)
    except TaskBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"task_id": task.task_id, "command": command, "status": task.status}


@router.post("/fetch")
def start_fetch(body: dict[str, Any] = Body(default={}), manager: TaskManager = Depends(get_manager)):
    return _submit(manager, "fetch", body)


@router.post("/export-queue")
def start_export(body: dict[str, Any] = Body(default={}), manager: TaskManager = Depends(get_manager)):
    return _submit(manager, "export-queue", body)


@router.post("/publish")
def start_publish(body: dict[str, Any] = Body(default={}), manager: TaskManager = Depends(get_manager)):
    return _submit(manager, "publish", body)


@router.post("/clean")
def start_clean(body: dict[str, Any] = Body(default={}), manager: TaskManager = Depends(get_manager)):
    return _submit(manager, "clean", body)


@router.post("/pipeline")
def start_pipeline(body: dict[str, Any] = Body(default={}), manager: TaskManager = Depends(get_manager)):
    """一键全自动流水线（采集→队列→AI解析→校验发布），单任务+全程SSE。"""
    return _submit(manager, "pipeline", body)


@router.post("/query-backfill")
def start_query_backfill(body: dict[str, Any] = Body(default={}), manager: TaskManager = Depends(get_manager)):
    """按研究方向/关键词查询补录（2026 优先 + 去年兜底 + 更早硬过滤）。"""
    q = str(body.get("query", "")).strip()
    if not q:
        raise HTTPException(status_code=422, detail="研究方向/关键词不能为空")
    return _submit(manager, "query-backfill", body)


@router.get("/query-history")
def query_history(q: str = "", limit: int = 5, manager: TaskManager = Depends(get_manager)):
    """某方向/关键词的历史检索记录（已检索过提示）。"""
    if not q.strip():
        return {"items": []}
    return {"items": manager.repo.get_query_history(q.strip(), limit=limit)}


@router.get("/active")
def active(manager: TaskManager = Depends(get_manager)):
    task = manager.active_task()
    if task is None:
        return {"active": False}
    return {
        "active": True,
        "task_id": task.task_id, "command": task.command,
        "status": task.status, "stage": task.stage,
        "percent": task.percent, "message": task.message,
    }


@router.get("/{task_id}/poll")
def poll_task(task_id: str, manager: TaskManager = Depends(get_manager)):
    """轮询任务状态与最近日志（SSE 之外的兜底，前端定时调用）。"""
    try:
        task = manager.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")
    history = manager.history_events(task_id)
    return {
        "task_id": task_id, "command": task.command,
        "status": task.status, "stage": task.stage,
        "current": task.current, "total": task.total,
        "percent": task.percent, "message": task.message,
        "level": task.level, "result": task.result,
        "events": history[-100:],
        "terminal": task.status in ("SUCCESS", "FAILED", "CANCELLED"),
    }


@router.post("/{task_id}/cancel")
def cancel(task_id: str, manager: TaskManager = Depends(get_manager)):
    try:
        ok = manager.cancel(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task_id": task_id, "cancelled": ok}


@router.get("/{task_id}/stream")
async def stream(task_id: str, manager: TaskManager = Depends(get_manager)):
    try:
        manager.get_task(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def gen():
        # 先回放历史缓冲
        for event in manager.history_events(task_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        if manager.is_terminal(task_id):
            return
        q = manager.subscribe(task_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("status") in ("SUCCESS", "FAILED", "CANCELLED"):
                    break
        finally:
            manager.unsubscribe(task_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/history")
def history(limit: int = 50, offset: int = 0,
            manager: TaskManager = Depends(get_manager)):
    conn = manager.repo._connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM run_logs").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM run_logs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    finally:
        conn.close()
    items = []
    for r in rows:
        d = dict(r)
        d["log_path"] = f"workspace/logs/task_run_{d['id']}.log"
        items.append(d)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.delete("/history/{log_id}")
def delete_history(log_id: int, manager: TaskManager = Depends(get_manager)):
    """删除单条历史记录及其日志文件。"""
    conn = manager.repo._connect()
    try:
        cur = conn.execute("DELETE FROM run_logs WHERE id=?", (log_id,))
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()
    log_file = manager.config.workspace_path / "logs" / f"task_run_{log_id}.log"
    log_file.unlink(missing_ok=True)
    return {"ok": True, "deleted": deleted}


@router.delete("/history")
def clear_history(keep: int = 0, manager: TaskManager = Depends(get_manager)):
    """清空历史记录；keep>0 时仅保留最近 keep 条。"""
    import sqlite3
    conn = manager.repo._connect()
    try:
        if keep > 0:
            keep = min(keep, 1000)
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM run_logs ORDER BY id DESC LIMIT -1 OFFSET ?", (keep,)
            ).fetchall()]
        else:
            ids = [r[0] for r in conn.execute("SELECT id FROM run_logs").fetchall()]
        if ids:
            conn.executemany("DELETE FROM run_logs WHERE id=?", [(i,) for i in ids])
        conn.commit()
    finally:
        conn.close()
    for i in ids:
        (manager.config.workspace_path / "logs" / f"task_run_{i}.log").unlink(missing_ok=True)
    return {"ok": True, "deleted": len(ids), "kept": keep}


@router.get("/history/{log_id}/log")
def history_log(log_id: int, manager: TaskManager = Depends(get_manager)):
    # 日志文件以 task_id 命名，run_logs 里无 task_id 字段，尝试两种定位
    log_dir = manager.config.workspace_path / "logs"
    log_file = log_dir / f"task_run_{log_id}.log"
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="日志文件不存在")
    return {"log_id": log_id, "content": log_file.read_text(encoding="utf-8")}
