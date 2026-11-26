"""DeepSeek Harness / WorkBuddy 分析队列导出（03 文档第 3 节）。

输出 workspace/queue/YYYY-MM-DD/<paper_uid>/ 任务包，状态置 QUEUED。
所有 JSON/MD 写入采用 .tmp -> os.replace 原子写入。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..config import AppConfig
from ..db.models import PaperRecord, PaperStatus, PaperTier
from ..db.repository import PaperRepository
from ..utils.bibtex import git_clone_hint, to_bibtex
from ..utils.logger import get_logger
from ..utils.timeutil import today_date
from .extractor import extract_for_paper

logger = get_logger()

S_PROMPT = """你是 PaperFlow 论文分析助手。请基于以下元数据与抽取文本，严格按指定 Markdown 结构输出一篇中文精读笔记。

## 论文元数据
- paper_uid: {paper_uid}
- 标题: {title}
- Venue: {venue} {pub_year}
- Tier: S（精读）
- Code: {code_url}

## 抽取全文（去 References）
{extracted_text}

## 输出要求
将结果写入 workspace/staging/{date}/{paper_uid}.md，严格遵守以下 6 节结构，并保留 YAML Frontmatter:
1. 一句话总结（TL;DR）
2. 研究背景与痛点（Motivation）
3. 核心方法拆解（Method）—— 引用抽取的架构图 `![核心架构图](../../assets/{paper_uid}/fig_1.webp)`（若存在）
4. 关键实验与 SOTA 对比（Experiments）
5. 局限性与可借鉴的 Idea（Critical Thinking）
6. 复现与引用卡片（BibTeX & Links）—— 含折叠区块的 BibTeX 与 git clone 命令

并在文末附加 PAPERFLOW_METRICS_JSON 注释块（task/backbone/datasets/sota_summary/innovation_tags）。

## BibTeX
{bibtex}
"""

A_PROMPT = """你是 PaperFlow 论文分析助手。请基于以下摘要生成一篇精简中文速览卡片。

## 论文元数据
- paper_uid: {paper_uid}
- 标题: {title}
- Venue: {venue} {pub_year}
- Tier: A（速览）

## Title + Abstract
{abstract}

## 输出要求
将结果写入 workspace/staging/{date}/{paper_uid}.md，只需包含:
1. TL;DR
2. 核心问题与思路
3. 主要结论
4. BibTeX 卡片
保留 YAML Frontmatter 与 PAPERFLOW_METRICS_JSON 注释块。
"""


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, data: dict) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _merge_manifest(queue_root: Path, target_date: str, new_items: list[dict]) -> int:
    manifest_path = queue_root / "queue_manifest.json"
    existing_items: list[dict] = []
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing_items = old.get("items", []) if isinstance(old, dict) else []
        except (ValueError, OSError):
            existing_items = []
    known_uids = {item.get("paper_uid") for item in new_items}
    merged = [item for item in existing_items if item.get("paper_uid") not in known_uids] + new_items
    _atomic_write_json(manifest_path, {"date": target_date, "count": len(merged), "items": merged})
    return len(merged)


def export_paper_to_queue(
    config: AppConfig,
    repo: PaperRepository,
    paper: PaperRecord,
    target_date: str | None = None,
    *,
    update_manifest: bool = True,
) -> dict:
    """导出单篇任务包；供批量导出与单篇闭环共用同一实现。"""
    target_date = target_date or paper.fetch_date or today_date().isoformat()
    queue_root = config.workspace_path / "queue" / target_date
    paper_dir = queue_root / paper.paper_uid
    paper_dir.mkdir(parents=True, exist_ok=True)

    extraction = extract_for_paper(paper, config, paper_dir)
    figures_rel = [
        str(Path(f).relative_to(config.workspace_path)) for f in extraction["figures"]
    ]
    meta = {
        "paper_uid": paper.paper_uid,
        "title": paper.title,
        "authors": json.loads(paper.authors_json or "[]"),
        "venue": paper.venue,
        "pub_year": paper.pub_year,
        "pub_date": paper.pub_date,
        "tier": paper.tier,
        "doi": paper.doi,
        "paper_url": paper.paper_url,
        "code_url": paper.code_url,
        "abstract": paper.abstract,
        "figures": figures_rel,
        "bibtex": to_bibtex(paper),
        "git_clone": git_clone_hint(paper),
    }
    _atomic_write_json(paper_dir / "meta.json", meta)

    extracted_text = Path(extraction["text_path"]).read_text(encoding="utf-8")
    from ..utils.figure_links import build_figures_markdown
    figures_markdown = build_figures_markdown(
        [Path(f).name for f in extraction["figures"]], paper.paper_uid,
        empty="（本文未抽取到架构图）",
    )

    import shutil
    src_pdf = None
    if paper.pdf_local_path and Path(paper.pdf_local_path).exists():
        src_pdf = Path(paper.pdf_local_path)
    else:
        candidate = config.workspace_path / "tmp" / "pdfs" / f"{paper.paper_uid}.pdf"
        if candidate.exists():
            src_pdf = candidate
    pkg_pdf = paper_dir / f"{paper.paper_uid}.pdf"
    if src_pdf is not None:
        try:
            if src_pdf.resolve() != pkg_pdf.resolve():
                shutil.copyfile(str(src_pdf), str(pkg_pdf))
        except OSError:
            pass
    pdf_path_str = str(pkg_pdf.resolve()) if pkg_pdf.exists() else (
        str(src_pdf.resolve()) if src_pdf else "（未找到本地 PDF）")

    from .prompt_manager import PromptManager
    context = {
        "paper_uid": paper.paper_uid, "title": paper.title,
        "venue": paper.venue, "year": paper.pub_year,
        "pub_date": paper.pub_date or "", "tier": paper.tier,
        "authors": ", ".join(json.loads(paper.authors_json or "[]")),
        "abstract": paper.abstract, "code_url": paper.code_url or "N/A",
        "paper_url": paper.paper_url, "figures_markdown": figures_markdown,
        "bibtex": meta["bibtex"],
        "content": extracted_text if paper.tier == PaperTier.S.value else paper.abstract,
        "date": target_date, "pdf_path": pdf_path_str,
    }
    template_id, prompt = PromptManager().render_for_paper(paper, context)
    meta["prompt_template_id"] = template_id
    _atomic_write_json(paper_dir / "meta.json", meta)
    _atomic_write_text(paper_dir / "prompt.md", prompt)

    repo.update_status(paper.paper_uid, PaperStatus.QUEUED)
    item = {
        "paper_uid": paper.paper_uid, "title": paper.title, "tier": paper.tier,
        "meta_path": f"{paper.paper_uid}/meta.json",
        "prompt_path": f"{paper.paper_uid}/prompt.md",
        "output_path": f"workspace/staging/{target_date}/{paper.paper_uid}.md",
    }
    if update_manifest:
        _merge_manifest(queue_root, target_date, [item])
    return item


def export_queue(
    config: AppConfig,
    repo: PaperRepository,
    target_date: str | None = None,
    limit: int | None = None,
) -> dict:
    """导出待分析队列；重复调用合并且不覆盖既有 manifest。"""
    target_date = target_date or today_date().isoformat()
    queue_root = config.workspace_path / "queue" / target_date
    queue_root.mkdir(parents=True, exist_ok=True)
    candidates = [
        p for p in repo.get_papers_by_status(PaperStatus.DOWNLOADED.value, PaperStatus.SCORED.value)
        if p.tier in (PaperTier.S.value, PaperTier.A.value)
    ]
    if limit:
        candidates = candidates[:limit]
    manifest_items = [
        export_paper_to_queue(config, repo, paper, target_date, update_manifest=False)
        for paper in candidates
    ]
    total = _merge_manifest(queue_root, target_date, manifest_items)
    logger.info(f"[queue] 导出 {len(manifest_items)} 篇（累计 {total}）到 {queue_root}")
    return {"date": target_date, "count": len(manifest_items),
            "total": total, "queue_root": str(queue_root)}
