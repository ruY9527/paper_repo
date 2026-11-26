"""Phase 14：多行 URL 与 Chrome/Edge bookmarks.html 导入解析。"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ..utils.logger import get_logger

logger = get_logger()


def parse_url_lines(text: str) -> list[str]:
    """从多行文本提取 URL（忽略空行与 # 注释），保持顺序并去重。"""
    seen: set[str] = set()
    out: list[str] = []
    for line in (text or "").splitlines():
        u = line.strip()
        if not u or u.startswith("#"):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


class _NetscapeBookmarksParser(HTMLParser):
    """解析 Netscape Bookmark 格式（Chrome/Edge 导出的 bookmarks.html）。

    <H3> 入栈表示文件夹名，<A HREF> 记录链接与所属文件夹及标题；
    </DL> 出栈。标准导出文件中 H3 之后紧跟 DL。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._folders: list[str] = []
        self._in_h3 = False
        self._h3_buf = ""
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs):
        t = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if t == "h3":
            self._in_h3 = True
            self._h3_buf = ""
        elif t == "a" and a.get("href"):
            item = {
                "url": a["href"].strip(), "title": "",
                "folder": self._folders[-1] if self._folders else "",
                "add_date": a.get("add_date", ""),
            }
            self.items.append(item)
            self._current = item

    def handle_endtag(self, tag: str):
        t = tag.lower()
        if t == "h3":
            folder = self._h3_buf.strip() or "未分类"
            self._folders.append(folder)
            self._in_h3 = False
        elif t == "dl" and self._folders:
            self._folders.pop()

    def handle_data(self, data: str):
        if self._in_h3:
            self._h3_buf += data
        elif self._current is not None and not self._current["title"]:
            txt = data.strip()
            if txt:
                self._current["title"] = txt


def parse_bookmarks_html(path_or_text: str | Path) -> list[dict[str, str]]:
    """解析书签 HTML，返回 [{url, title, folder, add_date}]。"""
    p = Path(path_or_text)
    try:
        text = p.read_text(encoding="utf-8", errors="replace") if p.exists() and p.is_file() else str(path_or_text)
    except OSError:
        text = str(path_or_text)
    parser = _NetscapeBookmarksParser()
    parser.feed(text)
    return parser.items
