"""论文 UID 生成与多源标准化去重（01 文档第 4 节）。

优先级：DOI > arXiv ID > OpenReview ID > 标准化标题哈希。
"""

from __future__ import annotations

import hashlib
import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_ARXIV_VERSION = re.compile(r"v\d+$")


def normalize_title(title: str) -> str:
    """标题标准化：转小写 -> 去 LaTeX 花括号与非字母数字 -> 合并空格。"""
    text = title.lower()
    text = text.replace("{", " ").replace("}", " ")
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def strip_arxiv_version(arxiv_id: str) -> str:
    """去掉 arXiv 版本号（如 2603.12345v2 -> 2603.12345）。"""
    return _ARXIV_VERSION.sub("", arxiv_id.strip())


def generate_paper_uid(
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    openreview_id: str | None = None,
    title: str = "",
) -> str:
    """按优先级生成全局唯一 paper_uid。"""
    if doi:
        return "doi_" + hashlib.sha1(doi.lower().strip().encode("utf-8")).hexdigest()[:12]
    if arxiv_id:
        clean_id = strip_arxiv_version(arxiv_id).replace("/", "_")
        return "arxiv_" + clean_id
    if openreview_id:
        return "or_" + openreview_id
    return "title_" + hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:12]
