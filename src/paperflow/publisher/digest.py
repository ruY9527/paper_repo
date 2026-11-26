"""每日人工速览清单 TODAY_DIGEST.md（03 文档第 5 节）。"""

from __future__ import annotations

from pathlib import Path

from ..config import AppConfig
from ..db.models import PaperTier
from ..db.repository import PaperRepository
from ..utils.logger import get_logger
from ..utils.timeutil import today_date

logger = get_logger()


def generate_digest(
    config: AppConfig,
    repo: PaperRepository,
    target_date: str | None = None,
) -> Path:
    """生成 staging/<date>/TODAY_DIGEST.md，返回文件路径。"""
    from datetime import date
    target_date = target_date or today_date().isoformat()
    staging_dir = config.workspace_path / "staging" / target_date
    staging_dir.mkdir(parents=True, exist_ok=True)

    papers = repo.get_all_papers()
    today_papers = [p for p in papers if p.fetch_date == target_date]

    s_papers = [p for p in today_papers if p.tier == PaperTier.S.value]
    a_papers = [p for p in today_papers if p.tier == PaperTier.A.value]
    b_count = sum(1 for p in today_papers if p.tier == PaperTier.B.value)

    lines = [
        f"# PaperFlow 每日速览 — {target_date}",
        "",
        f"> 今日入库 **{len(today_papers)}** 篇｜S 级精读 {len(s_papers)}｜A 级速览 {len(a_papers)}｜B 级归档 {b_count}",
        "",
        "## S 级精读列表",
        "",
    ]
    if s_papers:
        for p in s_papers:
            code = f" [💻 Code]({p.code_url})" if p.code_url else ""
            tldr = _short_tldr(p)
            lines.append(f"- **[{p.venue} {p.pub_year}] {p.title}**{code}")
            lines.append(f"  - {tldr}")
            if p.md_staging_path and Path(p.md_staging_path).exists():
                lines.append(f"  - 📄 本地笔记: `{p.md_staging_path}`")
    else:
        lines.append("_今日无 S 级论文_")

    lines += ["", "## A 级速览列表", ""]
    if a_papers:
        for p in a_papers:
            lines.append(f"- **[{p.venue}] {p.title}** — {_short_tldr(p)}")
    else:
        lines.append("_今日无 A 级论文_")

    lines += ["", "## B 级归档统计", "", f"今日共 **{b_count}** 篇 B 级论文仅入库，不消耗分析 Token。", ""]

    digest_path = staging_dir / "TODAY_DIGEST.md"
    digest_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"[digest] 生成速览清单: {digest_path}")
    return digest_path


def _short_tldr(paper) -> str:
    """从论文记录构造简短 TL;DR（优先 abstract 首句）。"""
    if not paper.abstract:
        return "_无摘要_"
    first = paper.abstract.strip().split(". ")[0]
    if len(first) > 120:
        first = first[:120] + "…"
    return first
