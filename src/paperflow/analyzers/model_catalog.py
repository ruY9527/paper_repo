"""Phase 14：读取本地 DeepSeek Harness Web（DSH）的模型目录，供 PaperFlow 选择。

数据源：~/.dsh/profiles/web/cordis.patch.yml（DSH 实际配置补丁），解析两处：
1. llm-pi-ai.config.providers —— 自定义 OpenAI 兼容 provider（kimi-code / volcengineark / google-gemini …），
   每个含 models: [{id, name}]。
2. dsh-connect-workbuddy.config.regions.<region>.lastCatalog —— workbuddy 内置模型目录
   （hy4 / hy4flash / deepseek-v4.1-flash …）。

纯本地读取，无网络、无认证依赖。文件缺失或格式异常时返回空列表 + 说明，不影响其它功能。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from ..utils.logger import get_logger

logger = get_logger()

DEFAULT_PATCH = Path.home() / ".dsh" / "profiles" / "web" / "cordis.patch.yml"


def _provider_models(patch: dict[str, Any]) -> list[dict[str, str]]:
    """从 llm-pi-ai.config.providers 提取自定义 provider 模型。"""
    out: list[dict[str, str]] = []
    for entry in patch if isinstance(patch, list) else []:
        if not isinstance(entry, dict):
            continue
        if entry.get("id") != "llm-pi-ai":
            continue
        providers = (((entry.get("config") or {}).get("providers")) or {})
        for provider, meta in providers.items():
            if not isinstance(meta, dict):
                continue
            display = meta.get("displayName") or provider
            for m in meta.get("models") or []:
                if isinstance(m, dict) and m.get("id"):
                    out.append({
                        "provider": str(provider),
                        "provider_name": str(display),
                        "id": str(m["id"]),
                        "name": str(m.get("name") or m["id"]),
                        "source": "custom_provider",
                    })
    return out


def _workbuddy_models(patch: dict[str, Any]) -> list[dict[str, str]]:
    """从 dsh-connect-workbuddy 的 regions.*.lastCatalog 提取内置模型。"""
    out: list[dict[str, str]] = []
    for entry in patch if isinstance(patch, list) else []:
        if not isinstance(entry, dict):
            continue
        if "workbuddy" not in str(entry.get("id", "")):
            continue
        regions = (((entry.get("config") or {}).get("regions")) or {})
        for region, meta in regions.items():
            for m in (meta or {}).get("lastCatalog") or []:
                if isinstance(m, dict) and m.get("id"):
                    out.append({
                        "provider": "workbuddy",
                        "provider_name": f"WorkBuddy ({region})",
                        "id": str(m["id"]),
                        "name": str(m.get("name") or m["id"]),
                        "source": "workbuddy_catalog",
                    })
    return out


def load_harness_models(patch_path: str | Path | None = None) -> dict[str, Any]:
    """返回 DSH 模型目录。

    结构：{"ok": bool, "source": str, "models": [...], "providers": [...], "message": str}
    """
    path = Path(patch_path) if patch_path else DEFAULT_PATCH
    if not path.exists():
        return {"ok": False, "source": str(path), "models": [], "providers": [],
                "message": f"未找到 DSH 配置文件: {path}"}
    try:
        patch = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except Exception as exc:
        return {"ok": False, "source": str(path), "models": [], "providers": [],
                "message": f"解析 DSH 配置失败: {exc}"}

    models = _provider_models(patch) + _workbuddy_models(patch)
    # 去重（provider + id）
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for m in models:
        key = (m["provider"], m["id"])
        if key not in seen:
            seen.add(key)
            unique.append(m)
    providers = sorted({m["provider"] for m in unique})
    return {
        "ok": True,
        "source": str(path),
        "models": unique,
        "providers": providers,
        "message": f"从 DSH 配置读取到 {len(unique)} 个模型（{len(providers)} 个 provider）",
    }
