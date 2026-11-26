"""中文方向词翻译与缓存验收：首次 API、后续缓存零网络。"""

from __future__ import annotations

import pytest

from paperflow.config import load_example_config
from paperflow.pipeline.topic_query import parse_topic_query
from paperflow.pipeline.topic_translator import (
    has_chinese, load_cache, save_cache, translate_term,
)


def test_has_chinese():
    assert has_chinese("图像融合") is True
    assert has_chinese("image fusion") is False
    assert has_chinese("HSI-MSI图像融合") is True


def test_translate_and_cache(monkeypatch, tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    calls = []
    def fake_api(text, timeout=8.0):
        calls.append(text)
        return "image fusion"
    monkeypatch.setattr("paperflow.pipeline.topic_translator.translate_via_api", fake_api)

    cache = load_cache(cfg)
    assert translate_term("图像融合", cfg, cache=cache) == "image fusion"
    save_cache(cfg, cache)
    # 第二次：缓存命中，不再调 API
    cache2 = load_cache(cfg)
    assert translate_term("图像融合", cfg, cache=cache2) == "image fusion"
    assert calls == ["图像融合"]


def test_api_failure_keeps_original(monkeypatch, tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    monkeypatch.setattr("paperflow.pipeline.topic_translator.translate_via_api", lambda *a, **k: None)
    assert translate_term("图像融合", cfg, cache={}) == "图像融合"  # 不阻断


def test_parse_translates_chinese(monkeypatch, tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    # 中文词翻译后应拿到 synonym_dict 里的英文扩展
    parsed = parse_topic_query("图像融合", cfg, translate_fn=lambda s: "image fusion")
    terms = parsed.groups[0].terms
    assert "image fusion" in terms
    assert not any(has_chinese(t) for t in terms)


def test_parse_mixed_zh_en(monkeypatch, tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    parsed = parse_topic_query("图像融合+agent", cfg,
                               translate_fn=lambda s: "image fusion" if has_chinese(s) else s)
    all_terms = [t for g in parsed.groups for t in g.terms]
    assert any("fusion" in t for t in all_terms)
    assert any("agent" in t.lower() for t in all_terms)
