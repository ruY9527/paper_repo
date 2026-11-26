"""全局应用状态（避免 app 与 routes 循环依赖）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .task_manager import TaskManager

_MANAGER: "TaskManager | None" = None


def set_manager(manager: "TaskManager") -> None:
    global _MANAGER
    _MANAGER = manager


def get_manager() -> "TaskManager":
    if _MANAGER is None:
        raise RuntimeError("TaskManager 尚未初始化")
    return _MANAGER
