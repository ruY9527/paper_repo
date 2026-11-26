"""知识矩阵与自动聚合页面生成器（04 文档第 2 节）。

每次 publish 直接查 papers + paper_metrics 两表，幂等覆盖 paper_repo/docs/ 下汇总页。
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from ..config import ALL_VENUES, VENUE_DISPLAY_NAMES, AppConfig
from ..db.models import PaperStatus, PaperTier
from ..db.repository import PaperRepository
from ..utils.logger import get_logger
from ..utils.timeutil import today_date

logger = get_logger()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _tldr_of(paper) -> str:
    if not paper.abstract:
        return "—"
    first = paper.abstract.strip().split(". ")[0]
    return first[:100] + ("…" if len(first) > 100 else "")


def build_index(config: AppConfig, repo: PaperRepository) -> str:
    papers = repo.get_all_papers()
    year = today_date().year
    s_count = sum(1 for p in papers if p.tier == PaperTier.S.value)
    a_count = sum(1 for p in papers if p.tier == PaperTier.A.value)
    code_count = sum(1 for p in papers if p.code_url)
    # Phase 14：收录网站统计
    try:
        site_count = repo.count_sites(is_public=1)["public"]
    except Exception:
        site_count = 0

    lines = [
        f"# PaperFlow {year} — 顶会顶刊论文精读库",
        "",
        "!!! info \"年度总览\"",
        f"    - 已收录论文：**{len(papers)}** 篇",
        f"    - S 级精读：**{s_count}** 篇",
        f"    - A 级速览：**{a_count}** 篇",
        f"    - 带开源代码：**{code_count}** 篇",
        f"    - 收录网站：**{site_count}** 个 → [网站导航](sites/index.md)",
        f"    - 最近更新：{today_date().isoformat()}",
        "",
        "## 各顶会/顶刊收录数量",
        "",
        f"按发表年份分列统计；数字可点击跳转到对应 Venue 年度总表。当前优先年份 **{year}**。",
        "",
        "| Venue | 今年 " + str(year) + " | 去年 " + str(year - 1) + " | 往期 | 合计 |",
        "| :--- | ---: | ---: | ---: | ---: |",
    ]

    def _year_of(p) -> int:
        y = getattr(p, "pub_year", None)
        if y:
            try:
                return int(y)
            except (ValueError, TypeError):
                pass
        fd = getattr(p, "fetch_date", "") or ""
        return int(fd[:4]) if fd[:4].isdigit() else year

    # 行集合：9 大顶会/顶刊 + 数据中出现的其它来源（预印本 / 未归类）
    venue_rows = list(ALL_VENUES)
    other_venues = sorted({(p.venue or "UNCATEGORIZED").upper() for p in papers}
                          - set(ALL_VENUES))
    # 当前年份的 Venue 年度页由 build_venue_tables 统一生成（含其它来源），
    # 因此首页数字可直接链接；往期年份没有对应页则保持纯数字，避免 strict build 断链。
    def _venue_page(display: str, yr: int) -> str | None:
        if yr != year:
            return None
        return f"{display}-{yr}.md"

    def _cell(display: str, yr: int, count: int) -> str:
        if count <= 0:
            return "0"
        page = _venue_page(display, yr)
        return f"[{count}](venues/{page})" if page else str(count)

    for v in venue_rows + other_venues:
        display = VENUE_DISPLAY_NAMES.get(v, v)
        subset = [p for p in papers if (p.venue or "UNCATEGORIZED").upper() == v]
        y_now = sum(1 for p in subset if _year_of(p) == year)
        y_prev = sum(1 for p in subset if _year_of(p) == year - 1)
        y_old = sum(1 for p in subset if _year_of(p) < year - 1)
        total = len(subset)
        total_cell = (f"[{total}](venues/{_venue_page(display, year)})"
                      if total and _venue_page(display, year) else str(total))
        label = display if v in ALL_VENUES else f"{display}（其它来源）"
        lines.append(f"| {label} | {_cell(display, year, y_now)} | "
                     f"{_cell(display, year - 1, y_prev)} | {y_old} | {total_cell} |")

    lines += ["", "## 最近发布的高价值论文", ""]
    # 关键：只链接已真正发布到博客仓库的论文（有 md_blog_path 或状态 PUBLISHED），
    # 否则 mkdocs --strict 会因链接指向不存在的文档而报警告/构建失败。
    published = [
        p for p in papers
        if (getattr(p, "md_blog_path", "") or p.status == PaperStatus.PUBLISHED.value)
    ]
    high_value = [p for p in published if p.tier in ("S", "A")][:15]

    from .tag_bilingual import tags_bilingual

    def _tags_of(p) -> str:
        # 真相源：博客精读 MD frontmatter 的 tags；回退到 DB 的方向/兴趣标签
        rel = getattr(p, "md_blog_path", "")
        md = config.paper_repo_path / "docs" / rel if rel else None
        tags: list[str] = []
        if md and md.exists():
            try:
                import frontmatter as _fm
                post = _fm.load(str(md))
                tags = list(post.get("tags") or [])
            except Exception:
                tags = []
        if not tags:
            try:
                tags = json.loads(getattr(p, "topic_tags_json", "[]") or "[]")
            except (ValueError, TypeError):
                tags = []
        return tags_bilingual(tags[:6])

    if high_value:
        lines += ["| 日期 | Venue | 标题 | Tier | 标签 | TL;DR |",
                  "| :--- | :--- | :--- | :--- | :--- | :--- |"]
        for p in high_value:
            display = VENUE_DISPLAY_NAMES.get(p.venue.upper(), p.venue)
            rel = getattr(p, "md_blog_path", "") or f"papers/{year}/{p.venue}/{p.paper_uid}.md"
            link = f"[{p.title}]({str(rel).replace(chr(92), '/')})"
            code = f" [💻]({p.code_url})" if p.code_url else ""
            lines.append(
                f"| {p.pub_date or p.fetch_date} | {display} | {link}{code} | {p.tier} "
                f"| {_tags_of(p)} | {_tldr_of(p)} |"
            )
        # 客户端分页：>8 条时显示页码控件（无第三方依赖）
        if len(high_value) > 8:
            lines += [
                "",
                '<div class="hv-pager" id="hv-pager" markdown>',
                "",
                "每页 8 篇 · 第 <b id=\"hv-page\">1</b> / "
                f"{((len(high_value) - 1) // 8) + 1} 页",
                "",
                '<button type="button" onclick="hvGo(-1)">← 上一页</button> '
                '<button type="button" onclick="hvGo(1)">下一页 →</button>',
                "",
                "</div>",
                "",
                "<script>",
                "(function(){",
                "  var tables=document.querySelectorAll('table');",
                "  var tbl=null; tables.forEach(function(x){ if(x.querySelector('th') && "
                "x.textContent.indexOf('TL;DR')>=0 && x.textContent.indexOf('标签')>=0) tbl=x; });",
                "  if(!tbl) return;",
                "  var rows=Array.prototype.slice.call(tbl.querySelectorAll('tbody tr'));",
                "  var per=8, page=0, total=Math.ceil(rows.length/per);",
                "  window.hvGo=function(d){ page=Math.max(0,Math.min(total-1,page+d));",
                "    rows.forEach(function(r,i){ r.style.display=(i>=page*per&&i<(page+1)*per)?'':'none'; });",
                "    var el=document.getElementById('hv-page'); if(el) el.textContent=page+1;",
                "    window.scrollTo({top:document.getElementById('hv-pager').offsetTop-80,behavior:'smooth'});",
                "  };",
                "  window.hvGo(0);",
                "})();",
                "</script>",
            ]
    else:
        lines.append("_暂无已发布论文_")

    # Phase 10：按研究方向浏览入口
    topic_counter: Counter[str] = Counter()
    for paper in papers:
        try:
            for tag in json.loads(getattr(paper, "topic_tags_json", "[]") or "[]"):
                if tag:
                    topic_counter[tag] += 1
        except json.JSONDecodeError:
            continue
    if topic_counter:
        lines += ["", "## 按研究方向浏览", ""]
        for tag, cnt in topic_counter.most_common():
            lines.append(f"- [{tag}](topics/{_topic_slug(tag)}.md)（{cnt} 篇）")
    return "\n".join(lines) + "\n"


def _topic_slug(name: str) -> str:
    """方向名 -> 文件 slug：小写、非字母数字换连字符、压缩重复。"""
    import re
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", (name or "").lower()).strip("-")
    return slug or "topic"


def build_venue_tables(config: AppConfig, repo: PaperRepository) -> dict[str, str]:
    papers = repo.get_all_papers()
    year = today_date().year
    tables: dict[str, str] = {}
    # 9 大顶会/顶刊 + 数据中出现的其它来源（预印本/未归类），保证收录数对得上
    all_rows = list(ALL_VENUES) + sorted(
        {(p.venue or "UNCATEGORIZED").upper() for p in papers} - set(ALL_VENUES)
    )
    for v in all_rows:
        display = VENUE_DISPLAY_NAMES.get(v, v)
        subset = [p for p in papers if p.venue.upper() == v]
        subset.sort(key=lambda p: (p.pub_date or p.fetch_date), reverse=True)
        lines = [
            f"# {display} {year} 年度总表",
            "",
            f"共收录 **{len(subset)}** 篇论文。",
            "",
        ]
        if not subset:
            lines += [
                f"!!! info \"{year} 年暂无收录\"",
                f"    本 Venue 在 {year} 年暂无收录论文。",
                "    当前论文多为 arXiv 预印本，可到首页「各顶会/顶刊收录数量」的",
                "    「其它来源」查看；后续按 Venue 归类后会自动出现在这里。",
                "",
            ]
            tables[v] = "\n".join(lines) + "\n"
            continue
        lines += [
            "| 日期 | 标题 | Tier | Code | 状态 | TL;DR |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for p in subset:
            blog_rel = getattr(p, "md_blog_path", "")
            title = (p.title or p.paper_uid).replace("|", "\\|")
            # 链接优先级：本地精读页（必须真实存在）→ 原文链接 → arXiv 链接
            title_cell = title
            if blog_rel:
                blog_file = config.paper_repo_path / "docs" / blog_rel
                if blog_file.exists():
                    title_cell = f"[{title}](../{str(blog_rel).replace(chr(92), '/')})"
            if title_cell == title:
                if p.paper_url:
                    title_cell = f"[{title}]({p.paper_url})"
                elif getattr(p, "arxiv_id", ""):
                    title_cell = f"[{title}](https://arxiv.org/abs/{p.arxiv_id})"
            code = f"[💻]({p.code_url})" if p.code_url else "—"
            # Phase 13：受限论文标注
            access = getattr(p, "access_type", "open")
            if access == "paywall_blocked" and p.status not in ("PUBLISHED", "CLEANED"):
                status_cell = "🔒 需登录/待补传"
            else:
                status_cell = "—"
            lines.append(
                f"| {p.pub_date or p.fetch_date} | {title_cell} | {p.tier} | {code} | {status_cell} | {_tldr_of(p)} |"
            )
        tables[v] = "\n".join(lines) + "\n"
    return tables


def _fmt_metric(value, *, max_len: int = 240) -> str:
    """把任意形态的 metrics 字段转成可读的一行文本（截断但信息完整）。

    AI 生成的字段可能是纯文本 / list / 嵌套 dict / JSON 字符串，
    统一处理，杜绝", ".join(str)逐字符拆分与整坨 JSON 塞单元格。
    """
    import json as _json
    if value is None or value == "":
        return "—"
    if isinstance(value, str):
        text = value.strip()
        # 形似 JSON 的字符串先尝试解析为结构化数据再展示
        if text.startswith(("{", "[")):
            try:
                return _fmt_metric(_json.loads(text), max_len=max_len)
            except (ValueError, TypeError):
                pass
        result = text
    elif isinstance(value, dict):
        parts = []
        for k, v in list(value.items())[:6]:
            if isinstance(v, (dict, list)):
                v = _fmt_metric(v, max_len=80)
            parts.append(f"**{k}**: {v}")
        result = "；".join(parts)
    elif isinstance(value, (list, tuple)):
        result = " · ".join(_fmt_metric(v, max_len=60) for v in value[:12])
    else:
        result = str(value)
    result = result.replace("|", "\\|").replace("\n", " ")
    if len(result) > max_len:
        result = result[:max_len].rstrip() + " …"
    return result or "—"


def build_sota_matrix(config: AppConfig, repo: PaperRepository) -> str:
    """跨论文能力对照：一篇一卡，字段分行，长文截断，链接原文看全文。"""
    metrics = repo.get_all_metrics()
    paper_map = {p.paper_uid: p for p in repo.get_all_papers()}
    year = today_date().year

    lines = [
        f"# {year} 跨论文能力对照",
        "",
        "!!! info \"怎么读这一页\"",
        "    每篇论文一张卡片，按「研究任务 / 方法骨架 / 数据集 / 核心结论 / 创新点」分行呈现。",
        "    为避免表格过宽，长文本已做截断；点击论文标题可读完整精读笔记与原文。",
        "    这些条目由 AI 从论文中自动抽取，关键数字请回原文核对。",
        "",
    ]
    if not metrics:
        lines.append("_暂无指标数据。等待分析结果写入 `PAPERFLOW_METRICS_JSON` 后自动生成。_")
        return "\n".join(lines) + "\n"

    # 有博客精读页的排在前面，按 venue 聚合便于横向比较
    def sort_key(m):
        p = paper_map.get(m["paper_uid"])
        return (0 if (p and getattr(p, "md_blog_path", "")) else 1,
                (p.venue if p else "—"), (p.title if p else m["paper_uid"]))

    for m in sorted(metrics, key=sort_key):
        p = paper_map.get(m["paper_uid"])
        title = (p.title if p else m["paper_uid"]).replace("|", "\\|")
        uid = m["paper_uid"]
        if p and getattr(p, "md_blog_path", ""):
            link = f"[{title}](../{str(p.md_blog_path).replace(chr(92), '/')})"
        elif p and p.paper_url:
            link = f"[{title}]({p.paper_url})"
        else:
            link = title
        venue = (p.venue if p else "—")
        date = (p.pub_date or p.fetch_date if p else "—")

        lines += [
            f"### {link}",
            "",
            f"> **{venue}** · {date} · `{uid}`",
            "",
            f"- **研究任务**：{_fmt_metric(m.get('task'), max_len=180)}",
            f"- **方法骨架**：{_fmt_metric(m.get('backbone'), max_len=220)}",
            f"- **数据集 / 场景**：{_fmt_metric(m.get('datasets'), max_len=180)}",
            f"- **核心结论**：{_fmt_metric(m.get('sota_summary'), max_len=280)}",
            f"- **创新点**：{_fmt_metric(m.get('innovation_tags'), max_len=200)}",
            "",
        ]
    return "\n".join(lines) + "\n"


def build_open_source(config: AppConfig, repo: PaperRepository) -> str:
    papers = [p for p in repo.get_all_papers() if p.code_url]
    papers.sort(key=lambda p: (p.code_stars or 0, p.pub_date or ""), reverse=True)
    year = today_date().year
    lines = [
        f"# {year} 开源代码精选库",
        "",
        f"共 **{len(papers)}** 篇论文附带开源代码。",
        "",
        "| 论文 | Venue | Stars | 代码仓库 |",
        "| :--- | :--- | ---: | :--- |",
    ]
    for p in papers:
        stars = str(p.code_stars) if p.code_stars is not None else "—"
        title = (p.title or p.paper_uid).replace("|", "\\|")
        blog_rel = getattr(p, "md_blog_path", "")
        if blog_rel and (config.paper_repo_path / "docs" / blog_rel).exists():
            # 本页在 docs/matrix/，回 docs 根需 ../
            title_cell = f"[{title}](../{str(blog_rel).replace(chr(92), '/')})"
        elif p.paper_url:
            title_cell = f"[{title}]({p.paper_url})"
        elif getattr(p, "arxiv_id", ""):
            title_cell = f"[{title}](https://arxiv.org/abs/{p.arxiv_id})"
        else:
            title_cell = title
        lines.append(f"| {title_cell} | {p.venue} | {stars} | [代码仓库]({p.code_url}) |")
    return "\n".join(lines) + "\n"


def build_weeklies(config: AppConfig, repo: PaperRepository) -> dict[str, str]:
    """按 ISO 周归档已发布 S/A 论文。"""
    weeklies: dict[str, list] = {}
    for p in repo.get_all_papers():
        if p.tier not in ("S", "A"):
            continue
        d_str = p.pub_date or p.fetch_date
        if not d_str:
            continue
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        iso = d.isocalendar()
        week_key = f"{iso.year}-W{iso.week:02d}"
        weeklies.setdefault(week_key, []).append(p)

    result: dict[str, str] = {}
    for week_key, papers in sorted(weeklies.items()):
        keywords = Counter()
        for p in papers:
            try:
                tags = json.loads(p.matched_tags_json or "[]")
            except json.JSONDecodeError:
                tags = []
            keywords.update(tags)
        top = keywords.most_common(10)

        lines = [
            f"# 趋势周报 {week_key}",
            "",
            f"本周收录 S/A 级论文 **{len(papers)}** 篇。",
            "",
            "## 论文列表",
            "",
        ]
        for p in papers:
            title = (p.title or p.paper_uid).replace("|", "\\|")
            # 链接优先级：本地精读页（真实存在）→ 原文 → arXiv
            link = title
            blog_rel = getattr(p, "md_blog_path", "")
            if blog_rel and (config.paper_repo_path / "docs" / blog_rel).exists():
                # 周报在 docs/weekly/，回到 docs 根需 ../
                link = f"[{title}](../{str(blog_rel).replace(chr(92), '/')})"
            elif p.paper_url:
                link = f"[{title}]({p.paper_url})"
            elif getattr(p, "arxiv_id", ""):
                link = f"[{title}](https://arxiv.org/abs/{p.arxiv_id})"
            lines.append(f"- **[{p.venue} {p.pub_year}] {p.tier}** — {link}")
        lines += ["", "## 高频关键词 Top 10", ""]
        if top:
            for kw, cnt in top:
                lines.append(f"- {kw}: {cnt}")
        else:
            lines.append("_暂无关键词统计_")
        result[week_key] = "\n".join(lines) + "\n"
    return result


def build_topic_pages(config: AppConfig, repo: PaperRepository) -> dict[str, str]:
    """Phase 10：按 topic_tags_json 生成方向专题页（优先年 / 兜底年分区）。"""
    papers = repo.get_all_papers()
    grouped: dict[str, list] = {}
    for paper in papers:
        try:
            tags = json.loads(getattr(paper, "topic_tags_json", "[]") or "[]")
        except json.JSONDecodeError:
            tags = []
        for tag in tags:
            if tag:
                grouped.setdefault(tag, []).append(paper)

    primary_year = config.primary_year
    fallback_year = config.fallback_year
    pages: dict[str, str] = {}
    for tag, items in grouped.items():
        primary = [p for p in items if p.pub_year == primary_year]
        fallback = [p for p in items if p.pub_year == fallback_year]
        code_count = sum(1 for p in items if p.code_url)
        lines = [
            f"# 研究方向：{tag}",
            "",
            f"!!! info \"方向统计\"",
            f"    - {primary_year} 收录：**{len(primary)}** 篇",
            f"    - {fallback_year} 兜底：**{len(fallback)}** 篇",
            f"    - 带开源代码：**{code_count}** 篇",
            "",
        ]
        for heading, subset in (
            (f"## 🔥 {primary_year} 最新前沿", primary),
            (f"## 📌 {fallback_year} 精选兜底", fallback),
        ):
            lines += [heading, ""]
            if not subset:
                lines += ["_暂无_", ""]
                continue
            lines += [
                "| 日期 | 标题 | Venue | Tier | Code | TL;DR |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
            ]
            for p in sorted(subset, key=lambda x: x.pub_date or "", reverse=True):
                title = p.title
                blog_rel = getattr(p, "md_blog_path", "")
                if p.tier in ("S", "A") and blog_rel:
                    title = f"[{p.title}](../{str(blog_rel).replace(chr(92), '/')})"
                elif p.paper_url:
                    title = f"[{p.title}]({p.paper_url})"
                code = f"[💻]({p.code_url})" if p.code_url else "—"
                lines.append(
                    f"| {p.pub_date or p.fetch_date} | {title} | {p.venue} | {p.tier} | {code} | {_tldr_of(p)} |"
                )
            lines.append("")
        pages[_topic_slug(tag)] = "\n".join(lines) + "\n"
    return pages


def _write_navigation_indexes(docs: Path, topics: dict[str, str], weeklies: dict[str, str]) -> int:
    """为目录式导航生成轻量索引，保留既有扁平页面及其相对链接。"""
    count = 0
    for slug in sorted(topics):
        _write(
            docs / "topics" / slug / "index.md",
            f"# 研究方向：{slug}\n\n[查看该方向论文](../{slug}.md)\n",
        )
        count += 1
    years = sorted({key[:4] for key in weeklies if key[:4].isdigit()}, reverse=True)
    for year in years:
        keys = sorted((key for key in weeklies if key.startswith(year + "-")), reverse=True)
        lines = [f"# {year} 趋势周报", ""]
        lines.extend(f"- [{key}](../{key}.md)" for key in keys)
        _write(docs / "weekly" / year / "index.md", "\n".join(lines) + "\n")
        count += 1
    return count


def _navigation_entries(docs: Path) -> dict[str, list[tuple[str, str]]]:
    """收集实际存在的 topics/weekly 页面，避免向 nav 写入断链。"""
    entries: dict[str, list[tuple[str, str]]] = {"研究方向": [], "趋势周报": []}
    topics = docs / "topics"
    topic_dirs = {p.name for p in topics.iterdir() if p.is_dir() and (p / "index.md").is_file()} if topics.exists() else set()
    entries["研究方向"] = [(name, f"topics/{name}/") for name in sorted(topic_dirs)]
    if topics.exists():
        entries["研究方向"].extend(
            (p.stem, f"topics/{p.name}")
            for p in sorted(topics.glob("*.md"))
            if p.stem not in topic_dirs and p.name != "index.md"
        )
    weekly = docs / "weekly"
    weekly_dirs = {p.name for p in weekly.iterdir() if p.is_dir() and (p / "index.md").is_file()} if weekly.exists() else set()
    entries["趋势周报"] = [(year, f"weekly/{year}/") for year in sorted(weekly_dirs, reverse=True)]
    if weekly.exists():
        entries["趋势周报"].extend(
            (p.stem, f"weekly/{p.name}")
            for p in sorted(weekly.glob("*.md"), reverse=True)
            if p.stem[:4] not in weekly_dirs
        )
    return entries


def _upsert_nav_section(lines: list[str], title: str, entries: list[tuple[str, str]]) -> bool:
    """纯文本幂等挂载一个 nav 小节，不经过 YAML round-trip。"""
    if not entries:
        return False
    try:
        nav_start = next(i for i, line in enumerate(lines) if line.strip() == "nav:")
    except StopIteration:
        return False
    nav_end = len(lines)
    for i in range(nav_start + 1, len(lines)):
        if lines[i] and not lines[i][0].isspace():
            nav_end = i
            break
    header = f"  - {title}:"
    section_start = next(
        (i for i in range(nav_start + 1, nav_end) if lines[i].rstrip() == header), None,
    )
    if section_start is None:
        block = [header] + [f"    - {name}: {path}" for name, path in entries]
        lines[nav_end:nav_end] = block
        return True
    section_end = nav_end
    for i in range(section_start + 1, nav_end):
        if lines[i].startswith("  - "):
            section_end = i
            break
    existing = "\n".join(lines[section_start:section_end])
    missing = [f"    - {name}: {path}" for name, path in entries if f": {path}" not in existing]
    if not missing:
        return False
    lines[section_end:section_end] = missing
    return True


def _update_mkdocs_navigation(config: AppConfig) -> bool:
    path = config.paper_repo_path / "mkdocs.yml"
    if not path.exists():
        return False
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    changed = False
    for title, entries in _navigation_entries(config.paper_repo_path / "docs").items():
        changed = _upsert_nav_section(lines, title, entries) or changed
    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def rebuild_all(config: AppConfig, repo: PaperRepository, dry_run: bool = False) -> dict:
    """重建全部汇总页并安全挂载导航。dry_run 时只统计不写盘。"""
    docs = config.paper_repo_path / "docs"
    year = today_date().year
    index = build_index(config, repo)
    venues = build_venue_tables(config, repo)
    sota = build_sota_matrix(config, repo)
    opensource = build_open_source(config, repo)
    weeklies = build_weeklies(config, repo)
    topics = build_topic_pages(config, repo)

    # Phase 14：同步网站导航页（仅公开站点）并幂等更新 mkdocs.yml
    sites_info = None
    if not dry_run:
        try:
            from ..sites.blog_renderer import sync_sites_blog
            sites_info = sync_sites_blog(config, repo)
        except Exception as exc:
            logger.warning(f"[aggregator] 网站导航页同步跳过: {exc}")

    navigation_pages = len(topics) + len({key[:4] for key in weeklies if key[:4].isdigit()})
    count = (1 + len(venues) + 1 + 1 + len(weeklies) + len(topics)
             + (1 if sites_info else 0) + navigation_pages)
    if not dry_run:
        from .ai_notice import append_ai_notice
        _write(docs / "index.md", append_ai_notice(index))
        for v, content in venues.items():
            _write(docs / "venues" / f"{VENUE_DISPLAY_NAMES.get(v, v)}-{year}.md", append_ai_notice(content))
        _write(docs / "matrix" / f"sota-{year}.md", append_ai_notice(sota))
        _write(docs / "matrix" / f"open-source-{year}.md", append_ai_notice(opensource))
        for week_key, content in weeklies.items():
            _write(docs / "weekly" / f"{week_key}.md", append_ai_notice(content))
        for slug, content in topics.items():
            _write(docs / "topics" / f"{slug}.md", append_ai_notice(content))
        _write_navigation_indexes(docs, topics, weeklies)
        _update_mkdocs_navigation(config)
        logger.info(f"[aggregator] 重建 {count} 个汇总页并挂载导航")
    return {"pages": count, "dry_run": dry_run}
