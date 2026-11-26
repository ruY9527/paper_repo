"""博客精读页的「返回」导航注入（幂等）。"""

from __future__ import annotations

_BACK_MARKER = "<!-- BACK-TO-HOME -->"

# 相对路径：文章位于 docs/papers/<year>/<venue>/<uid>.md，回到首页需 ../../../
# 固定在左侧、不随页面滚动；自带样式（自包含，无需改 mkdocs.yml/全局 CSS）
_BACK_LINK = """

<!-- BACK-TO-HOME -->
<style>
.pf-back-home{position:fixed;left:18px;top:76px;z-index:60;display:inline-flex;align-items:center;gap:6px;padding:7px 12px;border-radius:20px;background:rgba(99,102,241,.94);color:#fff;font-size:12px;font-weight:600;text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.22);transition:transform .15s,background .15s;backdrop-filter:blur(4px)}
.pf-back-home:hover{background:rgba(79,70,229,1);color:#fff;text-decoration:none;transform:translateX(-2px)}
.pf-back-home .pf-arrow{font-size:15px;line-height:1}
@media screen and (max-width:1220px){.pf-back-home{left:auto;right:18px;top:12px}}
@media screen and (max-width:760px){.pf-back-home{position:static;display:inline-flex;margin:0 0 14px;box-shadow:none}}
</style>
<a class="pf-back-home" href="../../../index.md" title="返回首页 · 最近发布的高价值论文">
  <span class="pf-arrow">←</span><span>返回首页</span>
</a>
"""


def append_back_link(content: str) -> str:
    """在精读页 frontmatter 之后注入返回首页按钮；已注入则原样返回。"""
    if not content:
        return content
    if _BACK_MARKER in content:
        return content
    lines = content.split("\n")
    # 找 frontmatter 结束的第二个 ---
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                head = "\n".join(lines[: i + 1])
                body = "\n".join(lines[i + 1 :])
                return head + _BACK_LINK + "\n" + body.lstrip("\n")
    # 无 frontmatter：开头注入
    return _BACK_LINK.strip() + "\n\n" + content
