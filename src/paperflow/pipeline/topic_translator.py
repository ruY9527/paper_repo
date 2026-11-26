"""研究方向中文→英文翻译（Phase 18）。

问题：中文方向词（如「图像融合」）原样进入 arXiv/OpenAlex 检索式时，英文库几乎
零召回。方案：首次走免费 API（MyMemory）翻译，结果持久化到本地缓存；
后续同一中文词直接命中缓存，零网络零成本。API 失败时保留原文，绝不阻断检索。

缓存文件：workspace/topic_translations.json  { "图像融合": "image fusion", ... }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from ..utils.logger import get_logger

logger = get_logger()

_MYMEMORY = "https://api.mymemory.translated.net/get"
_CJK_RE = __import__("re").compile(r"[\u4e00-\u9fff]")


def has_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _cache_path(config) -> Path:
    return config.workspace_path / "topic_translations.json"


def load_cache(config) -> dict[str, str]:
    p = _cache_path(config)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def save_cache(config, cache: dict[str, str]) -> None:
    p = _cache_path(config)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    __import__("os").replace(tmp, p)


def translate_via_api(text: str, timeout: float = 8.0) -> str | None:
    """免费 MyMemory API；成功返回英文译文，失败返回 None。"""
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            r = client.get(_MYMEMORY, params={"q": text, "langpair": "zh-CN|en"})
        if r.status_code == 200:
            d = r.json()
            out = (d.get("responseData") or {}).get("translatedText", "")
            if out and not has_chinese(out):
                return str(out).strip().lower()
    except Exception as exc:
        logger.debug(f"[translate] API failed for {text}: {exc}")
    return None


def translate_term(term: str, config, *, cache: dict[str, str] | None = None) -> str:
    """把一个中文/混合词翻译为英文；命中缓存直接用，否则 API 翻译并缓存。

    始终返回可用于检索的词：翻译成功→英文；失败→原文（保留原行为，不阻断）。
    """
    term = (term or "").strip()
    if not term or not has_chinese(term):
        return term
    c = cache if cache is not None else load_cache(config)
    if term in c:
        return c[term]
    en = translate_via_api(term)
    if en:
        c[term] = en
        if cache is None:
            save_cache(config, c)
        logger.info(f"[translate] {term} -> {en} (cached)")
        return en
    return term
