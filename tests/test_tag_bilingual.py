"""标签中英双语展示验收（拆开、各自可复制）。"""

from paperflow.publisher.tag_bilingual import tag_bilingual, tags_bilingual


def test_known_tag_bilingual():
    assert tag_bilingual("agent") == "`agent` · 智能体"
    assert tag_bilingual("image-fusion") == "`image-fusion` · 图像融合"
    assert tag_bilingual("vision-language-action") == "`vision-language-action` · 视觉-语言-动作"


def test_inferred_tag_bilingual():
    assert tag_bilingual("continual-RL") == "`continual-RL` · 持续强化学习"
    assert "谱方法" in tag_bilingual("spectral-methods")


def test_unknown_tag_keeps_english_code():
    assert tag_bilingual("totally-madeup-xyz") == "`totally-madeup-xyz`"


def test_tags_bilingual_separators():
    out = tags_bilingual(["agent", "agent", "image-fusion"])
    assert out == "`agent` · 智能体 ｜ `image-fusion` · 图像融合"
    assert "（" not in out  # 不再用括号黏在一起


def test_tag_pipe_escaped():
    assert "\\|" in tag_bilingual("a|b")
