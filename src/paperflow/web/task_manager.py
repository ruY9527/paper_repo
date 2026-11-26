"""后台异步任务调度器：互斥锁、取消令牌、SSE 进度广播与历史缓冲回放。

设计要点（05 文档第 2 节）：
- 全局写锁：同一时间仅 1 个写任务（fetch/publish/clean/export-queue），并发调用返回互斥错误。
- 进度事件：统一结构 dict，注入到 pipeline 各函数的 progress_cb / cancel_event。
- SSE：每个 task 维护一个有界 deque 事件缓冲 + asyncio.Queue 订阅集合，
  刷新页面后可回放历史事件并接着看终态。
- 落库：任务启动/结束写入 run_logs；完整文本日志写入 workspace/logs/task_<id>.log。
- 优雅取消：cancel_event.set()，任务循环在安全点检查后停止。
"""

from __future__ import annotations

import asyncio
import threading
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import AppConfig
from ..db.models import RunStatus
from ..db.repository import PaperRepository
from ..utils.logger import get_logger
from ..utils.timeutil import LOCAL_TZ, now_dt, now_iso  # 全项目统一 GMT+8 时间源

logger = get_logger()


@dataclass
class TaskState:
    task_id: str
    command: str
    params: dict[str, Any] = field(default_factory=dict)
    status: str = "PENDING"  # PENDING | RUNNING | SUCCESS | FAILED | CANCELLED
    stage: str = ""
    current: int = 0
    total: int = 0
    percent: float = 0.0
    message: str = ""
    level: str = "INFO"
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: Any = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    # 事件历史缓冲（用于 SSE 断线重连 / 刷新回放）
    history: deque[dict] = field(default_factory=lambda: deque(maxlen=1000))
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    log_lines: list[str] = field(default_factory=list)
    run_log_id: int | None = None


class TaskBusyError(Exception):
    """已有写任务运行中。"""


class TaskNotFoundError(Exception):
    """任务 ID 不存在。"""


class TaskCancelledError(Exception):
    """任务被用户取消。"""


def reload_config(app_or_manager, new_config_path: str | Path | None = None) -> AppConfig:
    """统一刷新 manager/app 配置及 MkDocs 服务路径，返回新配置。"""
    from ..config import PROJECT_ROOT, load_config

    app = app_or_manager if hasattr(app_or_manager, "state") else getattr(app_or_manager, "app", None)
    manager = app.state.manager if app is not None else app_or_manager
    path = Path(new_config_path) if new_config_path else PROJECT_ROOT / "config" / "config.yaml"
    cfg = load_config(path)
    manager.config = cfg
    if app is not None:
        app.state.config = cfg
        service = getattr(app.state, "mkdocs_service", None)
        if service is not None:
            service.paper_repo = cfg.paper_repo_path.resolve()
            service.workspace = cfg.workspace_path.resolve()
            service.preview_port = cfg.publish.preview_port
    return cfg


class TaskManager:
    """进程内单例任务管理器。"""

    def __init__(self, config: AppConfig, repo: PaperRepository):
        self.config = config
        self.repo = repo
        self._lock = threading.Lock()  # 互斥；非阻塞 acquire 决定是否忙碌
        self._tasks: dict[str, TaskState] = {}
        self._tasks_order: list[str] = []
        self._thread: threading.Thread | None = None

    # ---- 查询 ----

    def get_task(self, task_id: str) -> TaskState:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    def active_task(self) -> TaskState | None:
        for tid in reversed(self._tasks_order):
            task = self._tasks.get(tid)
            if task and task.status in ("PENDING", "RUNNING"):
                return task
        return None

    def is_busy(self) -> bool:
        return self.active_task() is not None

    def list_tasks(self, limit: int = 50) -> list[TaskState]:
        return [self._tasks[t] for t in reversed(self._tasks_order[-limit:]) if t in self._tasks]

    # ---- 提交 ----

    def submit(
        self,
        command: str,
        runner: Callable[[dict], Any],
        params: dict[str, Any] | None = None,
    ) -> TaskState:
        """提交一个写任务；若已有任务运行则抛 TaskBusyError。"""
        if not self._lock.acquire(blocking=False):
            raise TaskBusyError("已有任务正在运行")
        # 二次检查 active（防止状态残留）
        active = self.active_task()
        if active is not None:
            self._lock.release()
            raise TaskBusyError(f"已有任务 {active.task_id} 正在运行")

        task_id = f"task_{now_dt().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        task = TaskState(task_id=task_id, command=command, params=params or {})
        self._tasks[task_id] = task
        self._tasks_order.append(task_id)

        # run_logs 落库
        try:
            task.run_log_id = self.repo.start_run(
                command,
                date_from=(params or {}).get("date_from"),
                date_to=(params or {}).get("date_to"),
            )
        except Exception as exc:
            logger.warning(f"[TaskManager] run_logs 写入失败: {exc}")

        thread = threading.Thread(
            target=self._run, args=(task, runner), daemon=True,
            name=f"paperflow-task-{task_id}",
        )
        thread.start()
        self._thread = thread
        return task

    def _run(self, task: TaskState, runner: Callable[[dict], Any]) -> None:
        ctx = {
            "task_id": task.task_id,
            "command": task.command,
            "params": task.params,
            "emit": lambda **kw: self.emit(task.task_id, **kw),
            "cancel_event": task.cancel_event,
        }
        task.status = "RUNNING"
        task.started_at = now_iso()
        self.emit(task.task_id, status="RUNNING", stage="starting", level="INFO",
                  message=f"任务 {task.command} 已启动")
        try:
            result = runner(ctx)
            if task.cancel_event.is_set():
                task.status = "CANCELLED"
                task.message = "任务已取消"
                self.emit(task.task_id, status="CANCELLED", level="WARNING",
                          message="任务已在安全点停止（取消）")
            else:
                task.status = "SUCCESS"
                task.result = result
                task.percent = 100.0
                task.message = "任务完成"
                self.emit(task.task_id, status="SUCCESS", stage="done", percent=100.0,
                          level="INFO", message="任务完成")
        except TaskCancelledError:
            task.status = "CANCELLED"
            task.message = "任务已取消"
            self.emit(task.task_id, status="CANCELLED", level="WARNING", message="任务已取消")
        except Exception as exc:
            task.status = "FAILED"
            task.error = str(exc)
            task.message = f"任务失败: {exc}"
            logger.error(f"[TaskManager] {task.task_id} 失败: {exc}\n{traceback.format_exc()}")
            self.emit(task.task_id, status="FAILED", level="ERROR",
                      message=f"任务失败: {exc}")
        finally:
            task.finished_at = now_iso()
            self._persist_finish(task)
            self._flush_log(task)
            # 释放互斥锁
            if self._lock.locked():
                self._lock.release()

    def _persist_finish(self, task: TaskState) -> None:
        if task.run_log_id is None:
            return
        counts: dict[str, Any] = {}
        result = task.result
        if isinstance(result, dict):
            for key in ("fetched_count", "new_papers", "tier_s", "tier_a", "cleaned", "count"):
                if key in result:
                    target = {
                        "new_papers": "new_count", "tier_s": "tier_s_count",
                        "tier_a": "tier_a_count", "cleaned": "cleaned_count",
                        "count": "new_count",
                    }.get(key, key)
                    counts[target] = result[key]
        status = {
            "SUCCESS": RunStatus.SUCCESS, "FAILED": RunStatus.FAILED,
            "CANCELLED": RunStatus.SUCCESS,
        }.get(task.status, RunStatus.FAILED)
        try:
            self.repo.finish_run(
                task.run_log_id, status,
                message=(task.error or task.message or "")[:500],
                **counts,
            )
        except Exception as exc:
            logger.warning(f"[TaskManager] run_logs 更新失败: {exc}")

    def _flush_log(self, task: TaskState) -> None:
        log_dir = self.config.workspace_path / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            header = f"# {task.command} {task.task_id}\n# started: {task.started_at}\n"
            body = header + "\n".join(task.log_lines) + "\n"
            log_file = log_dir / f"task_{task.task_id}.log"
            log_file.write_text(body, encoding="utf-8")
            # 另写一份以 run_log_id 命名的别名，便于历史表直接定位
            if task.run_log_id is not None:
                (log_dir / f"task_run_{task.run_log_id}.log").write_text(body, encoding="utf-8")
        except Exception as exc:
            logger.warning(f"[TaskManager] 日志落盘失败: {exc}")

    # ---- 取消 ----

    def cancel(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task.status in ("PENDING", "RUNNING"):
            task.cancel_event.set()
            task.status = "CANCELLED"
            self.emit(task_id, status="CANCELLED", level="WARNING",
                      message="收到取消请求，将在安全点停止")
            return True
        return False

    # ---- 进度事件与 SSE ----

    def emit(
        self,
        task_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        current: int | None = None,
        total: int | None = None,
        percent: float | None = None,
        message: str | None = None,
        level: str = "INFO",
        **extra: Any,
    ) -> dict:
        task = self.get_task(task_id)
        if status is not None:
            task.status = status
        if stage is not None:
            task.stage = stage
        if current is not None:
            task.current = current
        if total is not None:
            task.total = total
        if percent is not None:
            task.percent = percent
        elif total and total > 0:
            task.percent = round(task.current / total * 100, 1)
        if message is not None:
            task.message = message

        event = {
            "task_id": task_id,
            "command": task.command,
            "status": task.status,
            "stage": task.stage,
            "current": task.current,
            "total": task.total,
            "percent": task.percent,
            "message": task.message or "",
            "level": level,
            "timestamp": now_iso(),
        }
        event.update(extra)
        task.history.append(event)
        task.log_lines.append(f"[{event['timestamp']}] [{level}] {event['stage']}: {event['message']}")

        # 广播给所有当前订阅者（线程安全：在主事件循环 push）
        for q in list(task.subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                pass
        return event

    def subscribe(self, task_id: str) -> asyncio.Queue:
        task = self.get_task(task_id)
        q: asyncio.Queue = asyncio.Queue()
        task.subscribers.add(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.subscribers.discard(q)

    def history_events(self, task_id: str) -> list[dict]:
        return list(self.get_task(task_id).history)

    def is_terminal(self, task_id: str) -> bool:
        return self.get_task(task_id).status in ("SUCCESS", "FAILED", "CANCELLED")
