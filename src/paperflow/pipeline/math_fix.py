"""把 AI 生成的「裸公式」修复为可渲染的 LaTeX 定界符形式。

问题：AI 常输出 `(a_t, g_t) ~ \\pi(...)` 这类类 LaTeX 文本但不带 `$...$`，
MathJax 不渲染，博客上显示为原样下划线文本。这里在写入 staging/blog 前
做保守兜底：仅把「独占一行、明确是方程、无定界符」的行包成 `$$...$$`。

行内下标（如 `c_tool 成本`）不处理，避免误伤普通文本。
"""

from __future__ import annotations

import re

# 明确方程特征：赋值/分布/求和/常见希腊字母命令
_EQ_MARKERS = re.compile(r"(=|~|\\pi|\\tau|\\sum|\\frac|\\in|\\cup|\\leq|\\geq|\\cdot)")
# 行内「变量 = (...元组...)」表达式：如 g_t = (R_t, p_t, q_t, e_t, threshold_t)
_INLINE_TUPLE = re.compile(
    r"(?<![\w$])([a-zA-Z]_\{?[a-zA-Z0-9]+\}?)\s*=\s*\(([^()]{3,120})\)"
)
# 行内 LaTex 命令或定界符已存在则跳过
_HAS_MATH = re.compile(r"(\$|\\\(|\\\[|```)")
# 明显是普通句子的前缀（含中文冒号/句号结尾的说明）
_PROSE = re.compile(r"[：:。；;]$")


def fix_bare_math(markdown: str) -> str:
    """保守地把独占一行的裸方程包成 $$...$$；已带定界符或代码块不动。"""
    if not markdown:
        return markdown
    out: list[str] = []
    in_fence = False
    in_math_block = False  # 已在 $$...$$ 块内，内部行不再处理
    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if stripped == "$$":
            in_math_block = not in_math_block
            out.append(line)
            continue
        if in_math_block:
            out.append(line)
            continue
        if (not in_fence and stripped and not _HAS_MATH.search(stripped)
                and not stripped.startswith("#") and not stripped.startswith("|")
                and not stripped.startswith(">") and not stripped.startswith("-")
                and not _PROSE.search(stripped)
                and len(stripped) <= 160 and _EQ_MARKERS.search(stripped)
                and re.search(r"[a-zA-Z\\].*[=_~]", stripped)):
            out.append(f"$$\n{stripped}\n$$")
        elif not in_fence and "$" not in line and not line.strip().startswith("```"):
            # 行内「变量=(元组)」→ $...$（保守：只匹配明确模式）
            fixed_line = _INLINE_TUPLE.sub(
                lambda m: f"${m.group(1)} = ({m.group(2)})$", line
            )
            out.append(fixed_line)
        else:
            out.append(line)
    return "\n".join(out)
