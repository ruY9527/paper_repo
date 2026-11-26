"""Phase 11：可选 OpenAI 兼容 HTTP API 解析器（预留扩展）。

不硬编码密钥：从 config.analyzer.openai_api.api_key_env 指定的环境变量读取。
"""

from __future__ import annotations

import os
from typing import Any, Callable

import httpx

from ..config import AppConfig
from ..db.repository import PaperRepository
from ..utils.logger import get_logger
from .base import BaseAnalyzer

logger = get_logger()


class OpenAIApiAnalyzer(BaseAnalyzer):
    backend = "openai_api"

    def __init__(self, config: AppConfig, repo: PaperRepository):
        super().__init__(config, repo)
        self.cfg = config.analyzer.openai_api

    def health_check(self, probe: bool = False) -> dict[str, Any]:
        key = os.environ.get(self.cfg.api_key_env, "")
        if not self.cfg.base_url:
            return {"ok": False, "backend": self.backend, "message": "未配置 base_url"}
        try:
            client = httpx.Client(timeout=10.0, trust_env=False)
            r = client.get(f"{self.cfg.base_url.rstrip('/')}/models")
            ok = r.status_code == 200
            return {"ok": ok, "backend": self.backend, "version": "",
                    "latency_ms": 0,
                    "message": "OpenAI 兼容 API 可达" if ok else f"HTTP {r.status_code}",
                    "api_key_set": bool(key)}
        except Exception as exc:
            return {"ok": False, "backend": self.backend, "message": f"连接失败: {exc}"}

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
            progress_cb(stage="openai_api", message=f"调用 OpenAI 兼容 API（第 {attempt} 次）")
        key = os.environ.get(self.cfg.api_key_env, "")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        with httpx.Client(timeout=self.config.analyzer.timeout_seconds, trust_env=False) as client:
            resp = client.post(
                f"{self.cfg.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": self.cfg.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
            )
        if resp.status_code != 200:
            from .base import AnalysisError
            raise AnalysisError(
                f"OpenAI API HTTP {resp.status_code}",
                error_type="http_error", http_status=resp.status_code,
                response_snippet=resp.text[:2000],
            )
        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return content or "", self.cfg.model
