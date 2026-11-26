"""系统元信息：代码版本指纹，用于前端检测旧进程/旧代码。

paperflow ui 不热重载 Python 代码。当前端页面来自磁盘新文件、而后端进程加载的是
旧代码时，会出现"界面有功能、点击报旧错误"的错位。本接口暴露后端进程的源码指纹，
前端与页面加载时的指纹对比，不一致即提示重启。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends

from ..state import get_manager
from ..task_manager import TaskManager

router = APIRouter(prefix="/api/system", tags=["system"])

_SRC = Path(__file__).resolve().parents[2]  # src/paperflow


def _code_fingerprint() -> str:
    """对关键源码文件的 (path, mtime_ns, size) 取哈希，反映进程加载代码的磁盘版本。"""
    h = hashlib.sha256()
    for rel in (
        "config.py", "cli.py",
        "analyzers/runner.py", "analyzers/base.py", "analyzers/harness_cli_analyzer.py",
        "web/routes/analyzer.py", "web/routes/sites.py", "web/routes/topics.py",
        "db/repository.py", "pipeline/downloader.py",
        "web/static/app.js", "web/static/index.html",
    ):
        p = _SRC / rel
        if p.exists():
            st = p.stat()
            h.update(f"{rel}:{st.st_mtime_ns}:{st.st_size};".encode("utf-8"))
        else:
            h.update(f"{rel}:missing;".encode("utf-8"))
    return h.hexdigest()[:16]


@router.get("/version")
def system_version(manager: TaskManager = Depends(get_manager)):
    import sys
    return {
        "fingerprint": _code_fingerprint(),
        "python": sys.version.split()[0],
        "pid": __import__("os").getpid(),
        "message": "ok",
    }
