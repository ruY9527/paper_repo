"""DeepSeek Harness Web 全自动解析后端（headless CLI）。

利用 `dsh --profile headless` 的非交互模式：stdin 喂完整 Prompt、stdout 收解析结果，
与 Claude CLI 后端共用超时/取消/自修复框架。可选通过临时 --patch 注入用户选择的模型。

注意：DSH checkout 路径与 cwd 必须一致（tsx 模块解析依赖），统一在构造时探测。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from ..config import AppConfig
from ..db.repository import PaperRepository
from ..utils.logger import get_logger
from .base import BaseAnalyzer

logger = get_logger()

# DSH checkout 位置（与运行时上下文一致）；可用环境变量覆盖
DEFAULT_DSH_CHECKOUT = Path(r"E:\thesis-code\github_code\deepseek-harness")
DSH_BIN = Path("apps/cli/src/bin.ts")


def _resolve_dsh_checkout() -> Path | None:
    raw = os.environ.get("PAPERFLOW_DSH_CHECKOUT", str(DEFAULT_DSH_CHECKOUT))
    p = Path(raw)
    return p if (p / DSH_BIN).exists() else None


class HarnessCliAnalyzer(BaseAnalyzer):
    """通过 dsh headless 非交互调用 DeepSeek Harness 解析论文。"""

    backend = "harness_cli"

    def __init__(self, config: AppConfig, repo: PaperRepository, model: str | None = None,
                 provider: str | None = None):
        super().__init__(config, repo)
        self.cfg = config.analyzer.harness_web
        self.model = model
        self.provider = provider
        self.checkout = _resolve_dsh_checkout()

    def _command(self) -> list[str]:
        """返回命令与 cwd；调用方需设置 cwd=checkout。

        关键：--profile/--patch 是 launcher 选项，必须在 app 参数之前；
        --approval-policy/- 属于 headless app。顺序错误会导致
        `unknown option '--patch'`（app 不认识 launcher 选项）。
        """
        node = os.environ.get("PAPERFLOW_NODE_BIN", "node")
        cmd = [node, "--import", "tsx/esm", str(DSH_BIN),
               "--profile", "headless"]
        patch = self._write_model_patch()
        if patch:
            # launcher 级 --patch 必须紧跟 --profile，在 app 参数之前
            cmd += ["--patch", str(patch)]
        # 以下为 headless app 参数
        cmd += ["--approval-policy", "never", "-"]
        return cmd

    # headless profile 实际加载的 provider（dsh-headless + workbuddy bundle）
    # 其它 provider（kimi-code / google-gemini / volcengineark）只在 web profile 可用，
    # 在 headless 里会报 NO_ADAPTER，必须回退到 workbuddy。
    HEADLESS_PROVIDERS = {"workbuddy"}
    FALLBACK_PROVIDER = "workbuddy"
    FALLBACK_MODEL = "hy4flash"

    def _effective_model(self) -> tuple[str, str]:
        """返回 headless 实际可用的 (provider, model)，不可用时自动回退。"""
        if self.provider in self.HEADLESS_PROVIDERS and self.model:
            return self.provider, self.model
        if self.provider and self.provider not in self.HEADLESS_PROVIDERS:
            logger.warning(
                f"[harness_cli] provider '{self.provider}' 在 headless 不可用，"
                f"回退到 {self.FALLBACK_PROVIDER}/{self.FALLBACK_MODEL}"
            )
        return self.FALLBACK_PROVIDER, self.FALLBACK_MODEL

    def _write_model_patch(self) -> Path | None:
        """生成临时 patch 注入 headless 可用模型（无效 provider 自动回退）。"""
        provider, model = self._effective_model()
        cfg = self.config
        patch_dir = cfg.workspace_path / "tmp" / "harness_patches"
        patch_dir.mkdir(parents=True, exist_ok=True)
        patch_file = patch_dir / "selected_model.yml"
        content = (
            "- id: agent-default-model\n"
            '  name: "@deepseek-ai/dsh-agent-default-model"\n'
            "  config:\n"
            f"    provider: {provider}\n"
            f"    model: {model}\n"
        )
        patch_file.write_text(content, encoding="utf-8")
        return patch_file

    def health_check(self, probe: bool = False) -> dict[str, Any]:
        if self.checkout is None:
            return {"ok": False, "backend": self.backend,
                    "message": f"未找到 DSH checkout（{DEFAULT_DSH_CHECKOUT}），可设置 PAPERFLOW_DSH_CHECKOUT"}
        try:
            r = subprocess.run(
                [os.environ.get("PAPERFLOW_NODE_BIN", "node"), "--import", "tsx/esm",
                 str(DSH_BIN), "headless", "--help"],
                cwd=str(self.checkout), capture_output=True, text=True,
                encoding="utf-8", errors="replace", shell=False, timeout=20,
            )
            ok = r.returncode == 0 and "headless" in (r.stdout + r.stderr)
            return {"ok": ok, "backend": self.backend,
                    "executable": str(self.checkout),
                    "version": "", "latency_ms": 0,
                    "message": "DSH headless 可用" if ok else f"headless 不可用: {(r.stderr or '')[:150]}"}
        except Exception as exc:
            return {"ok": False, "backend": self.backend, "message": f"检测失败: {exc}"}

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
        if self.checkout is None:
            raise RuntimeError("DSH checkout 不存在，无法调用 headless")
        if progress_cb:
            progress_cb(stage="harness_cli", message=f"调用 DeepSeek Harness headless（第 {attempt} 次）")
        cmd = self._command()
        timeout = self.config.analyzer.timeout_seconds
        proc = subprocess.Popen(
            cmd, cwd=str(self.checkout),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", shell=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        from .base import communicate_once
        try:
            # prompt 完整且仅写入一次；取消/超时由后台线程 terminate
            out, err = communicate_once(proc, prompt, timeout, cancel_event)
        except BaseException:
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill()
            raise
        if proc.returncode != 0:
            from .base import AnalysisError
            raise AnalysisError(
                f"Harness headless 退出码 {proc.returncode}",
                error_type="cli_nonzero_exit", stderr=err or "",
                exit_code=proc.returncode,
            )
        _, used_model = self._effective_model()
        return out or "", f"workbuddy/{used_model}"
