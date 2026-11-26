"""博客底部 AI 生成声明验收。"""

from __future__ import annotations

from paperflow.publisher.ai_notice import AI_NOTICE, append_ai_notice


def test_append_notice():
    content = "# Title\n\n正文内容\n"
    out = append_ai_notice(content)
    assert "AI-GENERATED-NOTICE" in out
    assert "内容由 AI 生成" in out
    assert out.startswith("# Title")


def test_notice_idempotent():
    once = append_ai_notice("# A\ntext")
    twice = append_ai_notice(once)
    assert twice.count("AI-GENERATED-NOTICE") == 1
    assert twice == once


def test_notice_mentions_discrimination():
    assert "甄别" in AI_NOTICE
    assert "以论文原文" in AI_NOTICE
