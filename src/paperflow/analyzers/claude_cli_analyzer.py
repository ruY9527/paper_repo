"""Phase 11：本地 Claude CLI（Kimi K3）非交互全自动解析器。

Windows 兼容：shutil.which 自动识别 claude / claude.cmd / claude.exe；
所有子进程严格 encoding="utf-8", errors="replace", shell=False；
用 Popen 轮询 stdin->stdout，支持 cancel_event 立即终止与超时保护。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, Callable

from ..config import AppConfig
from ..db.repository import PaperRepository
from ..utils.logger import get_logger
from .base import AnalysisResult, BaseAnalyzer

logger = get_logger()


def resolve_claude_executable(executable: str) -> str | None:
    """在 PATH / 常见 Windows 扩展名中解析 claude 可执行文件。"""
    direct = shutil.which(executable)
    if direct:
        return direct
    # Windows：显式尝试 .cmd / .exe（shutil.which 在部分环境不带 PATHEXT）
    for suffix in (".cmd", ".exe", ".bat"):
        found = shutil.which(executable + suffix)
        if found:
            return found
    return None


class ClaudeCliAnalyzer(BaseAnalyzer):
    backend = "claude_cli"

    def __init__(self, config: AppConfig, repo: PaperRepository):
        super().__init__(config, repo)
        self.cfg = config.analyzer.claude_cli

    def _base_env(self) -> dict[str, str]:
        env = {**os.environ, **self.cfg.extra_env}
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def _command(self, extra_args: list[str] | None = None) -> list[str]:
        executable = resolve_claude_executable(self.cfg.executable) or self.cfg.executable
        cmd = [executable, *self.cfg.args]
        if self.cfg.model:
            cmd += ["--model", self.cfg.model]
        if extra_args:
            cmd += extra_args
        return cmd

    # ---- health check ----

    def health_check(self, probe: bool = False) -> dict[str, Any]:
        t0 = int(time.time() * 1000)
        executable = resolve_claude_executable(self.cfg.executable)
        if not executable:
            return {
                "ok": False, "backend": self.backend, "executable": self.cfg.executable,
                "version": "", "latency_ms": 0,
                "message": "未找到 claude 可执行文件（请检查 PATH 或使用绝对路径）",
            }
        try:
            r = subprocess.run(
                [executable, "--version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", shell=False,
                timeout=15, env=self._base_env(),
            )
            version = (r.stdout or r.stderr or "").strip()
        except Exception as exc:
            return {"ok": False, "backend": self.backend, "executable": executable,
                    "version": "", "latency_ms": int(time.time() * 1000) - t0,
                    "message": f"版本检测失败: {exc}"}

        result = {
            "ok": r.returncode == 0, "backend": self.backend,
            "executable": executable, "version": version,
            "latency_ms": int(time.time() * 1000) - t0,
            "message": "Claude CLI 可执行" if r.returncode == 0 else "claude --version 返回非零",
        }
        if probe and result["ok"]:
            try:
                probe_result = self._call(
                    "Reply with exactly: OK", timeout=20, cancel_event=None
                )
                result["probe"] = probe_result[0].strip()[:100]
                result["ok"] = result["ok"] and "OK" in probe_result[0]
                result["message"] = (
                    "Kimi K3 探针响应正常" if result["ok"]
                    else "探针未返回预期 OK，请检查默认模型配置"
                )
            except Exception as exc:
                result["ok"] = False
                result["message"] = f"Kimi K3 探针失败: {exc}"
        return result

    # ---- generation ----

    def _call(self, prompt: str, *, timeout: int, cancel_event=None) -> tuple[str, str]:
        """Popen + 轮询：stdin 传 prompt，stdout 收结果，支持取消与超时。"""
        cmd = self._command()
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=self._base_env(),
        )
        from .base import communicate_once
        try:
            # prompt 完整且仅写入一次；取消/超时由后台线程 terminate
            out, err = communicate_once(proc, prompt, timeout, cancel_event)
        except BaseException:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            raise

        if proc.returncode != 0:
            from .base import AnalysisError
            raise AnalysisError(
                f"Claude CLI 退出码 {proc.returncode}",
                error_type="cli_nonzero_exit", stderr=err or "",
                exit_code=proc.returncode,
            )
        return out or "", (self.cfg.model or "default")

    def generate(
        self,
        prompt: str,
        *,
        paper_uid: str = "",
        previous_errors: list[str] | None = None,
        attempt: int = 1,
        cancel_event=None,
        progress_cb: Callable[..., None] | None = None,
    ) -> tuple[str, str]:
        if progress_cb:
            progress_cb(stage="claude_cli", message=f"调用本地 Claude CLI（第 {attempt} 次）")
        return self._call(
            prompt, timeout=self.config.analyzer.timeout_seconds,
            cancel_event=cancel_event,
        )
