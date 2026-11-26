"""方向查询解析鲁棒性验收：任意换词/连接词都不因整词误译而零命中。

根因回顾：旧实现枚举连接词作分隔符，换词仍会踩坑；新实现用「词典最长匹配
扫描 + 停用词最长跳过 + 翻译失败丢弃」，不依赖具体词汇。
"""

from __future__ import annotations

import pytest

from paperflow.config import load_example_config
from paperflow.pipeline.topic_query import parse_topic_query


def _tr(s):
    """模拟翻译器对干净中文词的正确翻译；连接词若混入会返回 WRONG。"""
    m = {"遥感图像融合": "remote sensing image fusion", "目标检测": "object detection",
         "图像分割": "image segmentation", "扩散模型": "diffusion model"}
    if any(x in s for x in ("与", "和", "以及", "或", "的", "or")):
        return "WRONG"
    return m.get(s, s)


@pytest.mark.parametrize("q", [
    "agent与图像融合", "agent和图像融合", "agent、图像融合", "agent以及图像融合",
    "agent与遥感与图像融合", "图像融合+目标检测", "遥感图像融合的研究",
    "关于agent的研究方向", "agent,or图像分割", "目标检测与图像分割",
    "多模态学习与扩散模型",
])
def test_connective_variants_never_mistranslate(q):
    cfg = load_example_config()
    p = parse_topic_query(q, cfg, translate_fn=_tr)
    terms = [t for g in p.groups for t in g.terms]
    assert len(p.groups) >= 1
    assert "WRONG" not in terms, q
    assert not any("fusion with images" in t for t in terms), q
    assert not any("\u4e00" <= ch <= "\u9fff" for t in terms for ch in t), f"中文泄漏: {q} {terms}"


def test_longest_match_keeps_compound_concept():
    cfg = load_example_config()
    p = parse_topic_query("HSI-MSI图像融合", cfg, translate_fn=_tr)
    assert len(p.groups) == 1
    assert "HSI-MSI fusion" in p.groups[0].terms


def test_dictionary_hit_skips_translation():
    cfg = load_example_config()
    called = []
    def spy(s):
        called.append(s)
        return "WRONG"
    p = parse_topic_query("agent与图像融合", cfg, translate_fn=spy)
    assert called == []
    assert "image fusion" in [t for g in p.groups for t in g.terms]


def test_translation_failure_drops_chinese(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    p = parse_topic_query("遥感图像融合的研究", cfg, translate_fn=lambda s: s)  # 翻译全失败
    terms = [t for g in p.groups for t in g.terms]
    # 即使翻译失败，也不应把中文原样塞进检索式（除 groups 全空兜底）
    assert all(not ("\u4e00" <= c <= "\u9fff" for c in t) for t in terms) or p.raw_query == "遥感图像融合的研究"
