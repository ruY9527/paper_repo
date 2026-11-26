"""博客页面统一的 AI 生成内容声明（所有公开页面底部注入）。

用 Markdown admonition 呈现，简洁克制；带幂等检查，重建页面不会重复追加。
"""

from __future__ import annotations

_AI_NOTICE_MARKER = "<!-- AI-GENERATED-NOTICE -->"

AI_NOTICE = """

---

<!-- AI-GENERATED-NOTICE -->
!!! note "内容由 AI 生成，请审慎甄别"
    本站的论文解读、摘要速览与网站点评均由人工智能自动整理生成，仅用于学习与快速检索。
    AI 输出可能存在事实偏差、理解误差或信息滞后，涉及关键结论、数据与观点时，
    请以论文原文及官方来源为准，并自行判断其准确性。
"""


def append_ai_notice(content: str) -> str:
    """在页面内容末尾追加 AI 声明；若已存在则原样返回（幂等）。"""
    if _AI_NOTICE_MARKER in (content or ""):
        return content
    return (content or "").rstrip() + AI_NOTICE
