"""架构图 Markdown 路径的唯一归一化规则。"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Iterable


_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()([^)]+)(\))")


def build_figures_markdown(
    figure_names: Iterable[str], paper_uid: str, *, empty: str = "（未抽取到架构图）"
) -> str:
    """生成 staging/queue 统一使用的两级相对资源链接。"""
    names = [PurePosixPath(str(name).replace("\\", "/")).name for name in figure_names]
    names = [name for name in names if name and name.lower().endswith(".webp")]
    if not names:
        return empty
    return "\n\n".join(
        f"![架构图](../../assets/{paper_uid}/{name})" for name in names
    )


def normalize_blog_image_paths(content: str, paper_uid: str) -> str:
    """把本地架构图链接转换为博客文章所需的三级相对路径。

    兼容裸文件名、staging 两级路径和已发布三级路径；外部 URL 与非 WebP
    图片保持原样。重复执行结果不变。
    """
    def replace(match: re.Match[str]) -> str:
        target = match.group(2).strip()
        if not target or any(ch.isspace() for ch in target):
            return match.group(0)
        path = target.strip("<>").replace("\\", "/")
        name = PurePosixPath(path).name
        if not name.lower().endswith(".webp"):
            return match.group(0)
        bare = re.fullmatch(r"(?:\./)?[^/]+\.webp", path, flags=re.I)
        owned_asset = re.fullmatch(
            rf"(?:\.\./)*assets/{re.escape(paper_uid)}/[^/]+\.webp",
            path, flags=re.I,
        )
        if not (bare or owned_asset):
            return match.group(0)
        return f"{match.group(1)}../../../assets/{paper_uid}/{name}{match.group(3)}"

    return _IMAGE_RE.sub(replace, content or "")
