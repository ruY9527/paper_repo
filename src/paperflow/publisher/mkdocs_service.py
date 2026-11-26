"""Phase 12 模块 A：发布前 MkDocs 严格构建门禁与本地预览服务。

- 统一 [sys.executable, "-m", "mkdocs", ...] 调用，复用当前虚拟环境。
- build_strict() 输出到 workspace/tmp/ 临时目录并在结束后清理，绝不残留 paper_repo/site。
- 单实例 mkdocs serve 预览进程管理 + TCP 就绪探测 + atexit 清理。
"""

from __future__ import annotations

import atexit
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..utils.logger import get_logger

logger = get_logger()


class BuildCheckResult(BaseModel):
    ok: bool
    duration_ms: int
    error_count: int
    warning_count: int
    issues: list[dict] = field(default_factory=list)
    raw_output: str = ""


_WARN_RE = re.compile(
    r"(WARNING|ERROR)\s*-\s*(.+?)(?:\s*\[[^\]]+\])?\s*$", re.IGNORECASE
)
_FILE_RE = re.compile(r"([A-Za-z0-9_\-\./\\]+\.(?:md|yml|yaml|webp|png|jpg|jpeg))")


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


class MkDocsService:
    """MkDocs 严格构建门禁与本地预览服务。"""

    def __init__(self, paper_repo_dir: Path, workspace_dir: Path, preview_port: int = 8001):
        self.paper_repo = Path(paper_repo_dir).resolve()
        self.workspace = Path(workspace_dir).resolve()
        self.preview_port = preview_port
        self._preview_proc: subprocess.Popen | None = None
        # 关闭钩子：确保关闭控制台时不残留 mkdocs serve 进程
        atexit.register(self.stop_preview)

    # ---- 严格构建门禁 ----

    def build_strict(self) -> BuildCheckResult:
        temp_site = self.workspace / "tmp" / "mkdocs_strict_check"
        if temp_site.exists():
            shutil.rmtree(temp_site, ignore_errors=True)
        temp_site.mkdir(parents=True, exist_ok=True)

        if not self.paper_repo.exists():
            shutil.rmtree(temp_site, ignore_errors=True)
            return BuildCheckResult(
                ok=False, duration_ms=0, error_count=1, warning_count=0,
                issues=[{"level": "ERROR", "file": "", "message": f"博客仓库目录不存在: {self.paper_repo}"}],
                raw_output="paper_repo dir not found",
            )

        cmd = [
            sys.executable, "-m", "mkdocs", "build", "--strict",
            "--site-dir", str(temp_site),
        ]
        started = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, cwd=str(self.paper_repo), capture_output=True, text=True,
                encoding="utf-8", errors="replace", shell=False, timeout=60,
            )
        except subprocess.TimeoutExpired:
            return BuildCheckResult(
                ok=False, duration_ms=int((time.monotonic() - started) * 1000),
                error_count=1, warning_count=0,
                issues=[{"level": "ERROR", "file": "", "message": "mkdocs build 超时（60s）"}],
                raw_output="mkdocs build timed out",
            )
        except (FileNotFoundError, NotADirectoryError) as exc:
            shutil.rmtree(temp_site, ignore_errors=True)
            return BuildCheckResult(
                ok=False, duration_ms=int((time.monotonic() - started) * 1000),
                error_count=1, warning_count=0,
                issues=[{"level": "ERROR", "file": "", "message": f"无法执行 mkdocs: {exc}"}],
                raw_output=str(exc),
            )
        finally:
            # 无论成功失败都清理临时目录
            shutil.rmtree(temp_site, ignore_errors=True)

        raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
        issues: list[dict] = []
        for line in raw.splitlines():
            m = _WARN_RE.search(line)
            if m:
                level = m.group(1).upper()
                message = m.group(2).strip()
                fm = _FILE_RE.search(message)
                issues.append({
                    "level": level,
                    "file": fm.group(1) if fm else "",
                    "message": message,
                })

        error_count = sum(1 for i in issues if i["level"] == "ERROR")
        warning_count = sum(1 for i in issues if i["level"] == "WARNING")
        ok = proc.returncode == 0

        return BuildCheckResult(
            ok=ok, duration_ms=int((time.monotonic() - started) * 1000),
            error_count=error_count, warning_count=warning_count,
            issues=issues, raw_output=raw,
        )

    # ---- 本地预览 ----

    def start_preview(self) -> dict[str, Any]:
        if self._preview_proc is not None and self._preview_proc.poll() is None:
            return {"ok": True, "already_running": True, "url": self.preview_url()}
        cmd = [
            sys.executable, "-m", "mkdocs", "serve",
            "-a", f"127.0.0.1:{self.preview_port}",
        ]
        try:
            self._preview_proc = subprocess.Popen(
                cmd, cwd=str(self.paper_repo), stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", shell=False,
            )
        except FileNotFoundError:
            return {"ok": False, "message": "未找到 mkdocs"}
        # 轮询端口就绪（最多 10 秒）
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if _port_open("127.0.0.1", self.preview_port):
                return {"ok": True, "already_running": False, "url": self.preview_url()}
            if self._preview_proc.poll() is not None:
                return {"ok": False, "message": "mkdocs serve 启动失败"}
            time.sleep(0.3)
        return {"ok": False, "message": "mkdocs serve 端口就绪超时（10s）"}

    def stop_preview(self) -> dict[str, Any]:
        if self._preview_proc is not None:
            proc = self._preview_proc
            self._preview_proc = None
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return {"ok": True, "stopped": True}
        return {"ok": True, "stopped": False, "message": "预览未在运行"}

    def get_preview_status(self) -> dict[str, Any]:
        running = self._preview_proc is not None and self._preview_proc.poll() is None
        return {
            "running": running,
            "url": self.preview_url() if running else None,
            "port": self.preview_port,
        }

    def preview_url(self) -> str:
        return f"http://127.0.0.1:{self.preview_port}"
