"""Phase 14：博客导航页自动渲染器。

安全红线：只渲染 is_public == 1 的网站；私密书签绝不写入任何博客文件。
生成 paper_repo/docs/sites/index.md，并幂等更新 mkdocs.yml（attr_list/md_in_html/nav）。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from ..config import AppConfig
from ..db.repository import PaperRepository
from ..utils.logger import get_logger
from ..utils.timeutil import today_date

logger = get_logger()


def _md_escape(text: str) -> str:
    """转义破坏 Markdown 的字符：管道、换行、制表符。"""
    return (text or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _card(site: dict[str, Any], category: dict[str, Any]) -> list[str]:
    tags = __import__("json").loads(site.get("tags_json") or "[]")
    title = _md_escape(site["title"])
    domain = _md_escape(site["domain"])
    desc = _md_escape(site.get("description") or "")
    note = _md_escape(site.get("personal_note") or "")
    tag_str = " · ".join(f"`{_md_escape(t)}`" for t in tags)
    lines = [
        f"-   **[{title}]({site['normalized_url']}){{ target=\"_blank\" }}**",
        "",
        "    ---",
        "",
        f"    {desc or domain}",
    ]
    if note:
        lines += ["", f"    > 💡 个人心得：{note}"]
    meta = f"    `{_md_escape(category['name'])}`"
    if tag_str:
        meta += f" · {tag_str}"
    lines += ["", meta]
    return lines


def render_sites_index(config: AppConfig, repo: PaperRepository) -> str:
    """生成导航页 Markdown（仅公开站点）。"""
    # 安全：只取公开
    all_sites = repo.get_sites(is_public=1, limit=100000)
    if config.sites.hide_dead_links_in_blog:
        all_sites = [s for s in all_sites if s["health_status"] != "DEAD"]
    cats = {c["id"]: c for c in repo.get_site_categories()}
    pinned = [s for s in all_sites if s["is_pinned"] == 1]
    by_cat: dict[int, list[dict[str, Any]]] = {}
    for s in all_sites:
        by_cat.setdefault(s["category_id"], []).append(s)

    lines = [
        "# 🌐 科研与工具网站导航",
        "",
        f"!!! info \"导航总览\"",
        f"    - 公开收录：**{len(all_sites)}** 个网站",
        f"    - 覆盖分类：**{len({s['category_id'] for s in all_sites})}** 个",
        f"    - 最后同步：{today_date().isoformat()}",
        "",
    ]

    if pinned:
        lines += ["## ⭐ 精选置顶", "", '<div class="grid cards" markdown>', ""]
        for s in pinned:
            lines += _card(s, cats.get(s["category_id"], {"name": "精选"}))
            lines.append("")
        lines += ["</div>", ""]

    for cat in repo.get_site_categories():
        sites = by_cat.get(cat["id"], [])
        if not sites:
            continue
        lines += [f"## {cat['icon']} {cat['name']}", ""]
        if config.sites.blog_layout == "table":
            lines += ["| 网站 | 简介 | 个人心得 | 标签 |", "| :--- | :--- | :--- | :--- |"]
            for s in sites:
                tags = __import__("json").loads(s.get("tags_json") or "[]")
                title = _md_escape(s["title"])
                desc = _md_escape(s.get("description") or "")
                note = _md_escape(s.get("personal_note") or "")
                tag_str = " · ".join(f"`{_md_escape(t)}`" for t in tags)
                lines.append(
                    f"| [{title}]({s['normalized_url']}) | {desc} | {note} | {tag_str} |"
                )
            lines.append("")
        else:
            lines += ['<div class="grid cards" markdown>', ""]
            for s in sites:
                lines += _card(s, cat)
                lines.append("")
            lines += ["</div>", ""]
    return "\n".join(lines) + "\n"


def update_mkdocs_nav(mkdocs_path: Path) -> bool:
    """幂等补齐 attr_list / md_in_html 扩展与网站导航 nav，返回是否有改动。

    用纯文本插入而非 YAML round-trip：mkdocs.yml 含 !!python/name 标签，
    yaml.safe_dump 无法保真，必须原样保留其余配置。
    """
    text = mkdocs_path.read_text(encoding="utf-8")
    changed = False
    # 补齐扩展：直接在 markdown_extensions: 标题行后插入缺失项（缩进 2 空格）
    missing = [e for e in ("attr_list", "md_in_html")
               if not re.search(rf"^\s*-\s*{re.escape(e)}\s*$", text, re.M)]
    if missing and "markdown_extensions:" in text:
        text = text.replace(
            "markdown_extensions:\n",
            "markdown_extensions:\n" + "".join(f"  - {e}\n" for e in missing), 1,
        )
        changed = True
    # 补 nav 项：网站导航固定在末尾（首页 → 顶会总表 → 知识矩阵 → 网站导航）
    if "网站导航" not in text and "nav:" in text:
        lines = text.split("\n")
        nav_start = next((i for i, l in enumerate(lines) if l.rstrip() == "nav:"), None)
        if nav_start is not None:
            # 找 nav 块末尾：下一个顶层 key（无前导空格且非列表项）或文件末尾
            end = len(lines)
            for i in range(nav_start + 1, len(lines)):
                l = lines[i]
                if l.strip() and not l.startswith((" ", "\t", "-")):
                    end = i
                    break
            # 去掉末尾空行后插入
            while end > nav_start + 1 and not lines[end - 1].strip():
                end -= 1
            lines.insert(end, "  - 网站导航: sites/index.md")
            text = "\n".join(lines)
            changed = True
    if changed:
        mkdocs_path.write_text(text, encoding="utf-8")
    return changed


def sync_sites_blog(config: AppConfig, repo: PaperRepository,
                    layout: str | None = None) -> dict[str, Any]:
    """执行同步：渲染导航页 + 更新 mkdocs.yml（不写 git）。"""
    if layout and layout in ("cards", "table"):
        # 临时覆盖布局（不修改全局配置）
        original = config.sites.blog_layout
        try:
            config.sites.blog_layout = layout
            content = render_sites_index(config, repo)
        finally:
            config.sites.blog_layout = original
    else:
        content = render_sites_index(config, repo)

    sites_dir = config.paper_repo_path / "docs" / "sites"
    sites_dir.mkdir(parents=True, exist_ok=True)
    index = sites_dir / "index.md"
    from ..publisher.ai_notice import append_ai_notice
    index.write_text(append_ai_notice(content), encoding="utf-8")
    mkdocs_changed = update_mkdocs_nav(config.paper_repo_path / "mkdocs.yml")
    public = repo.get_sites(is_public=1, limit=100000)
    logger.info(f"[sites] 导航页已同步：{len(public)} 个公开站点")
    return {"ok": True, "index_path": str(index), "public_count": len(public),
            "mkdocs_updated": mkdocs_changed, "layout": config.sites.blog_layout}
