"""裸公式修复验收：AI 输出的裸方程/行内表达式变为可渲染的 LaTeX。"""

from __future__ import annotations

from paperflow.pipeline.math_fix import fix_bare_math


def test_block_equation():
    out = fix_bare_math("(a_t, g_t) ~ \\pi(\\cdot | G, O_pre_t, h_t)")
    assert out.startswith("$$\n") and out.endswith("\n$$")
    assert "\\pi" in out


def test_inline_tuple():
    s = "输出不是自由文本，而是结构化契约：g_t = (R_t, p_t, q_t, e_t, threshold_t)。"
    out = fix_bare_math(s)
    assert "$g_t = (R_t, p_t, q_t, e_t, threshold_t)$" in out


def test_does_not_touch_prose_or_existing_math():
    prose = "critic 用 GPT-6，输入 g_t 和 O_t。判断动作是否推进 G。"
    assert fix_bare_math(prose) == prose
    existing = "$g_t = (R_t)$"
    assert fix_bare_math(existing) == existing
    fence = "```python\nx = (a_t, g_t)\n```"
    assert fix_bare_math(fence) == fence


def test_idempotent():
    once = fix_bare_math("τ = {(a_t, g_t)}_{t=1}^T")
    assert fix_bare_math(once) == once
