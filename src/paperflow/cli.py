"""统一命令行入口（Typer + Rich），9 个子命令。

安装后可通过 paperflow ... 或 python -m paperflow ... 调用。
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

# Windows GBK 控制台兼容：把 stdout/stderr 强制为 UTF-8，
# 避免 Rich 输出 ✓ / • 等符号时抛 UnicodeEncodeError。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from .__init__ import __version__
from .config import ALL_VENUES, PROJECT_ROOT, VENUE_DISPLAY_NAMES, AppConfig, load_config
from .db.models import PaperRecord, PaperStatus, PaperTier
from .db.repository import PaperRepository
from .utils.logger import get_logger
from .utils.timeutil import today_date

app = typer.Typer(
    name="paperflow",
    help="PaperFlow 2026 — 顶会顶刊论文自动化采集、分析与博客发布系统",
    add_completion=False,
)
console = Console()
logger = get_logger()

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
EXAMPLE_PATH = PROJECT_ROOT / "config" / "config.example.yaml"


def _load() -> AppConfig:
    return load_config(CONFIG_PATH)


def _repo(cfg: AppConfig) -> PaperRepository:
    return PaperRepository(cfg.db_path)


# ---------------- init ----------------
@app.command()
def init(
    config: str | None = typer.Option(None, "--config", help="指定配置文件路径"),
):
    """初始化工作区目录、SQLite 数据库、配置模板与 paper_repo 骨架。"""
    example = Path(config) if config else EXAMPLE_PATH
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        console.print(f"[green]✓[/green] 已创建 {CONFIG_PATH}")
    else:
        console.print("[yellow]配置已存在，跳过[/yellow]")

    cfg = _load()
    dirs = [
        cfg.workspace_path,
        cfg.workspace_path / "logs",
        cfg.workspace_path / "tmp" / "pdfs",
        cfg.workspace_path / "queue",
        cfg.workspace_path / "staging" / "assets",
        cfg.paper_repo_path / "docs" / "papers",
        cfg.paper_repo_path / "docs" / "assets",
        cfg.paper_repo_path / "docs" / "venues",
        cfg.paper_repo_path / "docs" / "matrix",
        cfg.paper_repo_path / "docs" / "weekly",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    _repo(cfg)  # 触发建表
    console.print(f"[green]✓[/green] 工作区初始化完成: {cfg.workspace_path}")


# ---------------- fetch ----------------
@app.command()
def fetch(
    from_date: str | None = typer.Option(None, "--from", help="起始日期 YYYY-MM-DD"),
    to_date: str | None = typer.Option(None, "--to", help="结束日期 YYYY-MM-DD"),
    venue: str | None = typer.Option(None, "--venue", help="逗号分隔的 venue"),
    source: str | None = typer.Option(None, "--source", help="逗号分隔的数据源"),
    force: bool = typer.Option(False, "--force", help="强制重拉"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅打印，不写库"),
):
    """拉取最新论文；不传日期则按水位线自动补录，并自动打分、下载 S 级 PDF、抽图。"""
    cfg = _load()
    repo = _repo(cfg)

    if dry_run:
        console.print("[cyan][dry-run][/cyan] 将执行论文拉取（不写入数据库）")
        console.print(f"  配置 Venue 数: {len(cfg.venues.names())}；启用数据源: "
                      f"{[k for k, v in vars(cfg.sources).items() if getattr(v, 'enabled', False)]}")
        return

    from .pipeline.backfill import BackfillEngine, ingest_papers
    from .pipeline.downloader import download_s_papers
    from .pipeline.extractor import extract_for_paper

    engine = BackfillEngine(cfg, repo)
    venues_list = [v.strip().upper() for v in venue.split(",")] if venue else None
    sources_list = [s.strip() for s in source.split(",")] if source else None

    if from_date and to_date:
        result = engine.run_manual(date.fromisoformat(from_date), date.fromisoformat(to_date),
                                   venues=venues_list, sources=sources_list)
    else:
        result = engine.run_auto(force=force)

    dl = download_s_papers(cfg, repo)
    table = Table(title="Fetch 结果")
    table.add_column("指标"); table.add_column("值")
    table.add_row("补录切片数", str(len(result.slices)))
    table.add_row("新增论文", str(result.new_papers))
    table.add_row("S 级", str(result.tier_s))
    table.add_row("A 级", str(result.tier_a))
    table.add_row("PDF 下载", str(dl["downloaded"]))
    table.add_row("降级 A 级", str(dl["fallback"]))
    console.print(table)


# ---------------- add ----------------
@app.command()
def add(
    url: str = typer.Option(..., "--url", help="arXiv URL / DOI"),
    venue: str | None = typer.Option(None, "--venue", help="手动覆盖 venue"),
):
    """单篇论文临时插队，强制标为 S 级并立即准备分析包。"""
    cfg = _load()
    repo = _repo(cfg)
    from .fetchers.single_adder import SinglePaperAdder
    from .pipeline.dedup import generate_paper_uid, normalize_title
    from .pipeline.scorer import score_and_persist

    raw = SinglePaperAdder(cfg).add(url, venue=venue)
    uid = generate_paper_uid(doi=raw.doi, arxiv_id=raw.arxiv_id,
                             openreview_id=raw.openreview_id, title=raw.title)
    record, is_new = repo.insert_paper_from_fields(
        paper_uid=uid, title=raw.title, normalized_title=normalize_title(raw.title),
        authors_json=json.dumps(raw.authors, ensure_ascii=False),
        affiliations_json=json.dumps(raw.affiliations, ensure_ascii=False),
        venue=raw.venue.upper(), pub_year=raw.pub_year, pub_date=raw.pub_date,
        fetch_date=today_date().isoformat(), source="manual",
        doi=raw.doi, arxiv_id=raw.arxiv_id, openreview_id=raw.openreview_id,
        abstract=raw.abstract, comment=raw.comment, paper_url=raw.paper_url,
        pdf_url=raw.pdf_url, code_url=raw.code_url, project_url=raw.project_url,
    )
    score_and_persist(record, cfg, repo, force_tier_s=True)
    console.print(f"[green]✓[/green] 已插队 {record.paper_uid}（强制 S 级）")


# ---------------- export-queue ----------------
@app.command("export-queue")
def export_queue_cmd(
    target_date: str | None = typer.Option(None, "--date", help="日期 YYYY-MM-DD"),
    limit: int | None = typer.Option(None, "--limit", help="最多导出篇数"),
):
    """导出待 DeepSeek Harness / WorkBuddy 分析的任务队列。"""
    cfg = _load()
    from .pipeline.queue_exporter import export_queue
    result = export_queue(cfg, _repo(cfg), target_date=target_date, limit=limit)
    console.print(f"[green]✓[/green] 已导出 {result['count']} 篇任务 → {result['queue_root']}")


# ---------------- validate ----------------
@app.command()
def validate(
    target_date: str | None = typer.Option(None, "--date", help="日期 YYYY-MM-DD"),
):
    """校验 staging MD，提取 metrics 入库并生成 TODAY_DIGEST.md。"""
    cfg = _load()
    repo = _repo(cfg)
    from .pipeline.md_validator import validate_all_staged
    from .publisher.digest import generate_digest

    results = validate_all_staged(cfg, repo, target_date=target_date)
    ok = sum(1 for r in results if r.ok)
    for r in results:
        if not r.ok:
            console.print(f"[red]✗[/red] {r.paper_uid}: {', '.join(r.errors)}")
    digest = generate_digest(cfg, repo, target_date=target_date)
    console.print(f"[green]✓[/green] 校验通过 {ok}/{len(results)}；速览清单: {digest}")


# ---------------- publish ----------------
@app.command()
def publish(
    push: bool = typer.Option(False, "--push", help="推送到 GitHub"),
    clean: bool = typer.Option(False, "--clean", help="发布后自动清理 PDF"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅打印变更清单"),
    no_push: bool = typer.Option(False, "--no-push", help="显式禁止推送（覆盖配置）"),
):
    """校验并同步至 paper_repo、刷新知识矩阵、提交/推送 GitHub、自动清理 PDF。"""
    cfg = _load()
    if no_push:
        cfg.publish.auto_git_push = False
    from .publisher.sync_blog import publish as do_publish
    result = do_publish(cfg, _repo(cfg), push=push and not no_push,
                        clean=clean or cfg.storage.auto_clean_after_publish,
                        dry_run=dry_run)
    console.print(
        f"[green]✓[/green] publish 完成: 校验 {result['validated']}，通过 {result['passed']}，"
        f"失败 {result['failed']}，变更 {len(result['changes'])} 项"
    )
    for c in result["changes"]:
        console.print(f"  • {c}")


# ---------------- clean ----------------
@app.command()
def clean(
    dry_run: bool = typer.Option(False, "--dry-run", help="预览，不实际删除"),
    include_staged: bool = typer.Option(False, "--include-staged", help="放宽到 STAGED/ANALYZED"),
):
    """安全清理已分析/已发布论文的临时 PDF 与队列目录。"""
    cfg = _load()
    from .pipeline.cleaner import clean_papers
    result = clean_papers(cfg, _repo(cfg), include_staged=include_staged, dry_run=dry_run)
    console.print(
        f"[green]✓[/green] 清理 {result['cleaned']} 篇，释放 {result['freed_mb']} MB"
        + ("（dry-run）" if dry_run else "")
    )


# ---------------- status ----------------
@app.command()
def status(
    venue: str | None = typer.Option(None, "--venue", help="只看指定 venue"),
    failed: bool = typer.Option(False, "--failed", help="只看失败重试列表"),
):
    """Rich 彩色看板：9 大 Venue 收录数、状态统计、水位线、失败列表。"""
    cfg = _load()
    repo = _repo(cfg)
    papers = repo.get_all_papers()
    if venue:
        papers = [p for p in papers if p.venue.upper() == venue.upper()]

    if failed:
        table = Table(title="失败重试列表")
        for col in ("UID", "标题", "重试次数", "错误"):
            table.add_column(col)
        for p in papers:
            if p.status == PaperStatus.FAILED.value:
                table.add_row(p.paper_uid, p.title[:40], str(p.retry_count), (p.last_error or "")[:50])
        console.print(table)
        return

    t = Table(title=f"PaperFlow 状态看板（共 {len(papers)} 篇）")
    for col in ("Venue", "总数", "S", "A", "B"):
        t.add_column(col)
    for v in ALL_VENUES:
        subset = [p for p in papers if p.venue.upper() == v]
        if not subset and not venue:
            continue
        t.add_row(
            VENUE_DISPLAY_NAMES.get(v, v), str(len(subset)),
            str(sum(1 for p in subset if p.tier == "S")),
            str(sum(1 for p in subset if p.tier == "A")),
            str(sum(1 for p in subset if p.tier == "B")),
        )
    console.print(t)

    wm_table = Table(title="数据源水位线")
    for col in ("Source", "Venue", "最后成功日期", "状态"):
        wm_table.add_column(col)
    for wm in repo.get_all_watermarks():
        wm_table.add_row(wm.source_name, wm.venue, wm.last_success_date, wm.last_status)
    console.print(wm_table)


# ---------------- retry-failed ----------------
@app.command("retry-failed")
def retry_failed(
    max_retries: int = typer.Option(3, "--max-retries", help="最大重试次数"),
):
    """重新拉取/下载此前标记为 FAILED 的论文。"""
    cfg = _load()
    repo = _repo(cfg)
    failed = [p for p in repo.get_papers_by_status(PaperStatus.FAILED.value)
              if p.retry_count < max_retries]
    for p in failed:
        repo.update_status(
            p.paper_uid, PaperStatus.FETCHED,
            retry_count=p.retry_count + 1, last_error=None,
        )
    console.print(f"[green]✓[/green] 已重置 {len(failed)} 篇 FAILED 论文待重试")


# ---------------- Phase 10：方向精准检索 ----------------

@app.command("topic-search")
def topic_search_cmd(
    query: str = typer.Argument(..., help="研究方向，如 agent / agent+图像融合 / HSI-MSI图像融合"),
    limit: int = typer.Option(20, "--limit", help="目标拉取篇数"),
    only_primary_year: bool = typer.Option(False, "--only-primary-year", help="仅看优先年份（不兜底）"),
    top_venues_only: bool = typer.Option(False, "--top-venues-only", help="仅保留 9 大顶会顶刊"),
    sources: str | None = typer.Option(None, "--sources", help="数据源，逗号分隔，如 arxiv,openalex"),
    download: bool = typer.Option(True, "--download", help="检索后立即下载 S 级 PDF 并抽图（--no-download 关闭）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅预览扩展后的检索式，不拉取不入库"),
):
    """按方向精准检索论文（优先年份填满，不足才兜底去年，严禁更早）。"""
    cfg = _load()
    from .fetchers.topic_fetcher import TopicSearchEngine
    from .pipeline.topic_query import parse_topic_query

    parsed = parse_topic_query(query, cfg)
    console.print("[cyan]扩展检索式预览[/cyan]")
    console.print(f"  arXiv   : {parsed.arxiv_query()}")
    console.print(f"  OpenAlex: {parsed.openalex_query()}")
    console.print(f"  时效窗口: {cfg.primary_year} 优先 → {cfg.fallback_year} 兜底，≤{cfg.min_allowed_year - 1} 硬过滤")
    if dry_run:
        return

    engine = TopicSearchEngine(cfg, _repo(cfg))
    result = engine.search(
        query, limit=limit, only_primary_year=only_primary_year,
        top_venues_only=top_venues_only,
        sources=[s.strip() for s in sources.split(",")] if sources else None,
        auto_download=download,
    )
    table = Table(title=f"方向检索结果：{query}")
    for col in ("年份", "标题", "Venue", "相关性分"):
        table.add_column(col)
    for p in result.papers:
        table.add_row(
            str(p.pub_year), p.title[:50], p.venue,
            str(result.relevance.get(p.title, 0)),
        )
    console.print(table)
    console.print(
        f"[green]✓[/green] {cfg.primary_year}: {result.primary_count} 篇 / "
        f"{cfg.fallback_year}: {result.fallback_count} 篇 / "
        f"过滤老论文: {result.filtered_old_count} / 新增入库: {result.new_inserted_count}"
    )
    if download:
        from .pipeline.downloader import download_s_papers
        from .pipeline.extractor import extract_for_paper
        dl = download_s_papers(cfg, _repo(cfg))
        console.print(f"[green]✓[/green] PDF 下载 {dl['downloaded']} 篇，降级 {dl['fallback']} 篇")


@app.command("topic-run")
def topic_run_cmd(
    topic: str | None = typer.Option(None, "--topic", help="只跑指定 slug 的订阅方向"),
    download: bool = typer.Option(False, "--download", help="检索后下载 S 级 PDF"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅预览不入库"),
):
    """批量执行 config.yaml 中所有已启用的常驻订阅方向。"""
    cfg = _load()
    from .fetchers.topic_fetcher import TopicSearchEngine

    subs = [s for s in cfg.topic_search.subscriptions if s.enabled]
    if topic:
        subs = [s for s in subs if s.slug == topic]
    if not subs:
        console.print("[yellow]没有启用的订阅方向[/yellow]")
        return

    repo = _repo(cfg)
    for sub in subs:
        console.print(f"[cyan]→ 方向 {sub.name} ({sub.query})[/cyan]")
        if dry_run:
            continue
        engine = TopicSearchEngine(cfg, repo)
        result = engine.search(
            sub.query, topic_name=sub.name, limit=sub.limit,
            only_primary_year=sub.only_primary_year,
            top_venues_only=sub.top_venues_only,
            auto_download=download,
        )
        console.print(
            f"  {cfg.primary_year}:{result.primary_count} / {cfg.fallback_year}:{result.fallback_count} / "
            f"过滤:{result.filtered_old_count} / 新增:{result.new_inserted_count}"
        )


@app.command("topic-list")
def topic_list_cmd():
    """展示常驻方向、同义词扩展与各方向 2026/2025 收录统计。"""
    cfg = _load()
    repo = _repo(cfg)
    from .pipeline.topic_query import parse_topic_query

    table = Table(title=f"常驻研究方向（{cfg.primary_year} 优先 → {cfg.fallback_year} 兜底）")
    for col in ("名称", "Slug", "检索式", "启用", "2026", "2025"):
        table.add_column(col)
    for sub in cfg.topic_search.subscriptions:
        parsed = parse_topic_query(sub.query, cfg)
        papers = [p for p in repo.get_all_papers() if sub.name in (json.loads(getattr(p, "topic_tags_json", "[]") or "[]"))]
        table.add_row(
            sub.name, sub.slug, parsed.expanded_text()[:60],
            "✓" if sub.enabled else "✗",
            str(sum(1 for p in papers if p.pub_year == cfg.primary_year)),
            str(sum(1 for p in papers if p.pub_year == cfg.fallback_year)),
        )
    console.print(table)


# ---------------- Phase 11：AI 解析引擎 ----------------

@app.command("pipeline-run")
def pipeline_run_cmd(
    engine: str = typer.Option(None, "--engine", help="解析引擎：claude_cli / harness_cli / openai_api（默认取配置）"),
    model: str | None = typer.Option(None, "--model", help="覆盖模型 ID"),
    steps: str = typer.Option("fetch,queue,analyze,publish", "--steps", help="要执行的阶段，逗号分隔"),
    push: bool = typer.Option(False, "--push", help="发布后 git 推送"),
    clean: bool = typer.Option(False, "--clean", help="发布后清理临时文件"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅预览执行计划"),
):
    """一键全自动：采集 → 导出队列 → AI 解析 → 校验发布（全程无人值守）。"""
    cfg = _load(); repo = _repo(cfg)
    eng = engine or cfg.analyzer.default_backend
    if eng == "harness_web":
        eng = "harness_cli"
    step_list = [s.strip() for s in steps.split(",") if s.strip()]
    if dry_run:
        console.print(f"[cyan]将依次执行：[/cyan] {' → '.join(step_list)}  [引擎={eng}] [模型={model or '默认'}]")
        return
    from .analyzers.runner import AnalyzerRunner
    from .pipeline.backfill import BackfillEngine
    from .pipeline.downloader import download_s_papers
    from .pipeline.queue_exporter import export_queue
    from .publisher.sync_blog import publish
    from .db.models import PaperStatus

    if "fetch" in step_list:
        console.print("[cyan][1/4] 采集最新论文…[/cyan]")
        r = BackfillEngine(cfg, repo).run_auto()
        dl = download_s_papers(cfg, repo)
        console.print(f"  新增 {r.new_papers} 篇，下载 {dl.get('downloaded',0)} 篇")
    if "queue" in step_list:
        console.print("[cyan][2/4] 导出分析队列…[/cyan]")
        qr = export_queue(cfg, repo)
        console.print(f"  导出 {qr.get('count',0)} 篇")
    if "analyze" in step_list:
        console.print(f"[cyan][3/4] AI 解析（{eng}）…[/cyan]")
        runner = AnalyzerRunner(cfg, repo, backend=eng, model=model)
        uids = [p.paper_uid for p in repo.get_papers_by_status(PaperStatus.QUEUED.value)]
        results = runner.run_batch(uids)
        ok = sum(1 for x in results if x.ok)
        console.print(f"  成功 {ok}/{len(results)} 篇")
    if "publish" in step_list:
        console.print("[cyan][4/4] 校验并发布…[/cyan]")
        pub = publish(cfg, repo, push=push, clean=clean)
        console.print(f"  通过 {pub.get('passed',0)} 篇")
    console.print("[green]✓[/green] 全自动流水线完成")


@app.command("analyzer-check")
def analyzer_check_cmd(
    backend: str = typer.Option("claude_cli", "--backend", help="claude_cli | openai_api"),
    probe: bool = typer.Option(False, "--probe", help="执行真实最小探针（消耗极少 Token）"),
    model: str | None = typer.Option(None, "--model", help="覆盖模型 ID（来自本地 DSH 模型目录）"),
    list_models: bool = typer.Option(False, "--list-models", help="列出本地 DSH 可用模型后退出"),
):
    """检查 AI 解析器连通性（Claude CLI 版本 / Kimi K3 探针 / OpenAI API）。"""
    cfg = _load()
    from .analyzers.runner import create_analyzer

    if list_models:
        from .analyzers.model_catalog import load_harness_models
        cat = load_harness_models()
        table = Table(title="本地 DSH 可用模型")
        for col in ("提供方", "模型 ID", "名称", "来源"):
            table.add_column(col)
        for m in cat["models"]:
            table.add_row(m["provider"], m["id"], m["name"], m["source"])
        console.print(table)
        console.print(f"[green]✓[/green] {cat['message']}")
        return

    try:
        analyzer = create_analyzer(backend, cfg, _repo(cfg), model=model)
    except ValueError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(1)
    health = analyzer.health_check(probe=probe)
    table = Table(title=f"解析器连通性：{backend}")
    for col in ("项目", "值"):
        table.add_column(col)
    table.add_row("结果", "✓ 正常" if health.get("ok") else "✗ 异常")
    table.add_row("消息", str(health.get("message", "")))
    if health.get("executable"):
        table.add_row("可执行文件", str(health["executable"]))
    if health.get("version"):
        table.add_row("版本", str(health["version"])[:120])
    if probe and health.get("probe"):
        table.add_row("探针响应", str(health["probe"])[:120])
    if health.get("latency_ms"):
        table.add_row("延迟", f"{health['latency_ms']} ms")
    console.print(table)
    if not health.get("ok"):
        raise typer.Exit(1)


@app.command("analyze")
def analyze_cmd(
    backend: str | None = typer.Option(None, "--backend", help="claude_cli | openai_api"),
    target_date: str | None = typer.Option(None, "--date", help="仅解析指定日期队列"),
    paper_uid: str | None = typer.Option(None, "--paper-uid", help="仅解析指定论文"),
    tiers: str | None = typer.Option(None, "--tier", help="按分级筛选，如 S,A"),
    limit: int | None = typer.Option(None, "--limit", help="最多解析篇数"),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="重试上次失败的论文"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅预览待解析列表"),
    model: str | None = typer.Option(None, "--model", help="覆盖模型 ID（来自本地 DSH 模型目录）"),
):
    """批量调用 AI 引擎解析队列、校验入库（Claude CLI 全自动）。"""
    cfg = _load()
    repo = _repo(cfg)
    from .analyzers.runner import AnalyzerRunner

    backend = backend or cfg.analyzer.default_backend
    runner = AnalyzerRunner(cfg, repo, backend=backend, model=model)

    # 收集待解析：QUEUED（或 --retry-failed 时取 analysis_runs 失败的）
    if retry_failed:
        failed_uids = {r["paper_uid"] for r in repo.get_analysis_runs(limit=500)
                       if r["status"] in ("FAILED", "TIMEOUT", "VALIDATION_FAILED", "ERROR")}
        candidates = [p for p in repo.get_all_papers() if p.paper_uid in failed_uids]
    else:
        # 已导出队列(QUEUED) 与 已下载PDF(DOWNLOADED) 都可解析
        candidates = (repo.get_papers_by_status(PaperStatus.QUEUED.value)
                      + repo.get_papers_by_status(PaperStatus.DOWNLOADED.value))

    if paper_uid:
        candidates = [p for p in candidates if p.paper_uid == paper_uid]
    if target_date:
        candidates = [p for p in candidates if p.fetch_date == target_date]
    if tiers:
        wanted = {t.strip().upper() for t in tiers.split(",")}
        candidates = [p for p in candidates if p.tier in wanted]
    if limit:
        candidates = candidates[:limit]

    if dry_run:
        table = Table(title=f"待解析预览（{len(candidates)} 篇，backend={backend}）")
        for col in ("UID", "标题", "Tier", "状态"):
            table.add_column(col)
        for p in candidates:
            table.add_row(p.paper_uid, p.title[:50], p.tier, p.status)
        console.print(table)
        return

    if not candidates:
        console.print("[yellow]没有待解析论文[/yellow]")
        return

    results = runner.run_batch([p.paper_uid for p in candidates])
    ok = sum(1 for r in results if r.ok)
    table = Table(title="解析结果")
    for col in ("UID", "状态", "尝试", "耗时", "备注"):
        table.add_column(col)
    for r in results:
        table.add_row(r.paper_uid, r.status, str(r.attempt), f"{r.duration_ms}ms",
                      (r.error_message or "")[:60])
    console.print(table)
    console.print(f"[green]✓[/green] 成功 {ok}/{len(results)} 篇（backend={backend}）")


# ---------------- Phase 12：构建门禁 / 预览 / Prompt 工作室 ----------------

@app.command("build-check")
def build_check_cmd():
    """本地运行 mkdocs build --strict 门禁检查并输出结构化问题列表。"""
    cfg = _load()
    from .publisher.mkdocs_service import MkDocsService
    svc = MkDocsService(cfg.paper_repo_path, cfg.workspace_path, cfg.publish.preview_port)
    result = svc.build_strict()
    table = Table(title="MkDocs 严格构建门禁")
    for col in ("项目", "值"):
        table.add_column(col)
    table.add_row("结果", "[green]✓ 通过[/green]" if result.ok else "[red]✗ 失败[/red]")
    table.add_row("错误数", str(result.error_count))
    table.add_row("警告数", str(result.warning_count))
    table.add_row("耗时", f"{result.duration_ms} ms")
    console.print(table)
    if result.issues:
        issue_table = Table(title="问题列表")
        for col in ("级别", "文件", "信息"):
            issue_table.add_column(col)
        for i in result.issues:
            issue_table.add_row(i["level"], i["file"] or "—", i["message"][:80])
        console.print(issue_table)
    if not result.ok:
        raise typer.Exit(1)


@app.command("preview")
def preview_cmd(
    port: int = typer.Option(8001, "--port", help="预览端口"),
    open_browser: bool = typer.Option(False, "--open", help="启动后打开浏览器"),
):
    """启动本地 mkdocs serve 实时预览博客（Ctrl+C 停止）。"""
    import threading
    import webbrowser

    cfg = _load()
    from .publisher.mkdocs_service import MkDocsService
    svc = MkDocsService(cfg.paper_repo_path, cfg.workspace_path, port)
    result = svc.start_preview()
    if result.get("ok"):
        url = result["url"]
        console.print(f"[green]✓[/green] 本地预览已启动: {url}")
        if open_browser:
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        console.print("按 Ctrl+C 停止预览")
        try:
            import time as _t
            while True:
                _t.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            svc.stop_preview()
    else:
        console.print(f"[red]✗[/red] 预览启动失败: {result.get('message', '未知错误')}")
        raise typer.Exit(1)


@app.command("prompts-list")
def prompts_list_cmd():
    """表格展示所有 Prompt 模板、优先级与方向匹配规则。"""
    from .pipeline.prompt_manager import PromptManager
    pm = PromptManager()
    pm.ensure_builtin_templates()
    table = Table(title="Prompt 模板列表")
    for col in ("ID", "名称", "Tier", "优先级", "匹配方向", "内置"):
        table.add_column(col)
    for t in pm.list_templates():
        table.add_row(
            t["id"], t["name"], t.get("tier", "S"), str(t.get("priority", 0)),
            ", ".join(t.get("match_topics", []) or []) or "—",
            "✓" if t.get("is_builtin") else "",
        )
    console.print(table)


@app.command("prompts-init")
def prompts_init_cmd(
    force: bool = typer.Option(False, "--force", help="强制重置内置模板"),
):
    """初始化（或重置）config/prompts/ 内置默认模板。"""
    from .pipeline.prompt_manager import PromptManager
    pm = PromptManager()
    if force:
        import shutil
        if pm.dir.exists():
            shutil.rmtree(pm.dir)
    created = pm.ensure_builtin_templates()
    console.print(
        f"[green]✓[/green] {'已初始化' if created else '已存在'} {len(pm.list_templates())} 套模板: {pm.dir}"
    )


# ---------------- Phase 13：受限论文清单 ----------------

@app.command("paywall-list")
def paywall_list_cmd(
    status: str | None = typer.Option(None, "--status", help="PENDING_MANUAL 等状态"),
    publisher: str | None = typer.Option(None, "--publisher", help="出版商，如 IEEE"),
):
    """展示被过滤拦截的受限论文清单。"""
    cfg = _load()
    repo = _repo(cfg)
    items = repo.get_paywall_papers(manual_status=status, publisher=publisher)
    table = Table(title=f"受限论文清单（{len(items)} 篇）")
    for col in ("UID", "标题", "Venue", "年份", "出版商", "原因", "状态"):
        table.add_column(col)
    for p in items:
        table.add_row(p["paper_uid"], p["title"][:40], p["venue"], str(p["pub_year"]),
                      p["publisher"], p["block_reason"], p["manual_status"])
    console.print(table)


@app.command("paywall-rescue")
def paywall_rescue_cmd(
    paper_uid: str | None = typer.Option(None, "--paper-uid", help="单篇论文 UID"),
    all_pending: bool = typer.Option(False, "--all-pending", help="抢救所有待处理"),
):
    """对待处理受限论文尝试按标题搜寻 arXiv 同名开放版。"""
    cfg = _load()
    repo = _repo(cfg)
    from .pipeline.paywall_filter import PaywallFilter
    pf = PaywallFilter(cfg, repo)
    if paper_uid:
        paper = repo.get_paper(paper_uid)
        targets = [paper] if paper else []
    elif all_pending:
        pending_uids = [p["paper_uid"] for p in repo.get_paywall_papers(manual_status="PENDING_MANUAL")]
        targets = [repo.get_paper(u) for u in pending_uids]
        targets = [t for t in targets if t is not None]
    else:
        console.print("[yellow]请指定 --paper-uid 或 --all-pending[/yellow]")
        return

    rescued = 0
    for paper in targets:
        result = pf.filter_and_rescue(paper)
        if result["action"] == "rescued":
            rescued += 1
            console.print(f"[green]✓[/green] 抢救成功: {paper.paper_uid} -> {result['arxiv_id']}")
        else:
            console.print(f"[yellow]未找到 arXiv 同名版: {paper.paper_uid}[/yellow]")
    console.print(f"[green]✓[/green] 共抢救 {rescued}/{len(targets)} 篇")


@app.command("paywall-attach")
def paywall_attach_cmd(
    paper_uid: str = typer.Argument(..., help="论文 UID"),
    pdf_path: str = typer.Argument(..., help="本地 PDF 路径"),
):
    """手动将本地 PDF 绑定到受限论文并自动抽图。"""
    from pathlib import Path as _P
    cfg = _load()
    repo = _repo(cfg)
    from .pipeline.manual_pdf import attach_local_pdf
    p = _P(pdf_path)
    if not p.exists():
        console.print(f"[red]✗[/red] 文件不存在: {pdf_path}")
        raise typer.Exit(1)
    try:
        result = attach_local_pdf(cfg, repo, paper_uid, p.read_bytes())
    except ValueError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] 补传成功: {result['paper_uid']}（文本 {result['text_chars']} 字符，图 {result['figures']} 张）")


@app.command("paywall-scan-inbox")
def paywall_scan_inbox_cmd():
    """扫描 inbox_pdfs 自动匹配并绑定批量下载的 PDF。"""
    cfg = _load()
    repo = _repo(cfg)
    from .pipeline.manual_pdf import scan_inbox_pdfs
    result = scan_inbox_pdfs(cfg, repo)
    console.print(f"[green]✓[/green] 匹配 {result['matched']} 篇，未匹配 {result['unmatched']} 篇")
    for r in result["report"]:
        console.print(f"  {r['file']} -> {r['status']}")


@app.command("paywall-export")
def paywall_export_cmd(
    fmt: str = typer.Option("md", "--format", help="md | csv"),
    output: str | None = typer.Option(None, "--output", help="输出文件路径"),
):
    """导出待人工下载清单。"""
    cfg = _load()
    repo = _repo(cfg)
    from .pipeline.manual_pdf import export_pending_checklist
    content, suggested = export_pending_checklist(cfg, repo, fmt=fmt)
    path = output or suggested
    from pathlib import Path as _P
    _P(path).write_text(content, encoding="utf-8")
    console.print(f"[green]✓[/green] 已导出到 {path}")


@app.command("site-add")
def site_add_cmd(
    url: str = typer.Argument(..., help="要收录的网站 URL"),
    category: str = typer.Option("ai-llm", "--category", help="分类 slug"),
    title: str | None = typer.Option(None, "--title", help="网站标题（默认自动抓取）"),
    note: str = typer.Option("", "--note", help="个人推荐语/心得"),
    tags: str = typer.Option("", "--tags", help="逗号分隔标签"),
    pin: bool = typer.Option(False, "--pin", help="置顶精选"),
    private: bool = typer.Option(False, "--private", help="私密收藏（不发布到博客）"),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="不自动抓取元信息"),
):
    """收录单个网站（默认自动抓取标题与简介）。"""
    cfg = _load(); repo = _repo(cfg)
    from .sites.metadata_fetcher import fetch_metadata, normalize_url
    try:
        norm, domain = normalize_url(url)
    except ValueError as exc:
        console.print(f"[red]✗[/red] {exc}"); raise typer.Exit(1)
    if repo.get_site_by_normalized_url(norm):
        console.print("[yellow]该网站已收录（标准化 URL 去重）[/yellow]"); return
    meta = {"title": "", "description": "", "favicon_url": ""}
    if not no_fetch:
        meta = fetch_metadata(url, timeout=cfg.sites.fetch_timeout_seconds)
    cats = {c["slug"]: c for c in repo.get_site_categories()}
    cat = cats.get(category)
    if cat is None:
        console.print(f"[red]✗[/red] 未知分类: {category}（可用: {', '.join(cats)}）"); raise typer.Exit(1)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    sid = repo.add_site(
        url=url, normalized_url=norm, domain=domain,
        title=title or meta.get("title") or domain,
        description=meta.get("description", ""), personal_note=note,
        category_id=cat["id"], tags=tag_list, favicon_url=meta.get("favicon_url", ""),
        is_pinned=int(pin), is_public=0 if private else 1,
    )
    console.print(f"[green]✓[/green] 已收录 #{sid}: {title or meta.get('title')} ({domain})"
                  + (" [私密]" if private else ""))


@app.command("site-list")
def site_list_cmd(
    category: str | None = typer.Option(None, "--category", help="按分类 slug 过滤"),
    public_only: bool = typer.Option(False, "--public-only", help="仅看公开"),
    dead_only: bool = typer.Option(False, "--dead-only", help="仅看死链"),
    q: str | None = typer.Option(None, "--q", help="关键词搜索"),
):
    """Rich 表格展示已收录网站。"""
    repo = _repo(_load())
    cat_id = None
    if category:
        for c in repo.get_site_categories():
            if c["slug"] == category:
                cat_id = c["id"]; break
    sites = repo.get_sites(category_id=cat_id, is_public=1 if public_only else None,
                           health_status="DEAD" if dead_only else None, q=q, limit=500)
    table = Table(title=f"已收录网站（{len(sites)}）")
    for col in ("ID", "标题", "域名", "分类", "公开", "置顶", "健康"):
        table.add_column(col)
    cats = {c["id"]: c["name"] for c in repo.get_site_categories()}
    for s in sites:
        table.add_row(str(s["id"]), s["title"][:40], s["domain"],
                      cats.get(s["category_id"], "?"), "🌐" if s["is_public"] else "🔒",
                      "⭐" if s["is_pinned"] else "", s["health_status"])
    console.print(table)


@app.command("site-check")
def site_check_cmd(
    category: str | None = typer.Option(None, "--category", help="仅巡检指定分类 slug"),
):
    """执行死链巡检并更新可达性状态。"""
    cfg = _load(); repo = _repo(cfg)
    from .sites.health_checker import check_many
    cat_id = None
    if category:
        for c in repo.get_site_categories():
            if c["slug"] == category:
                cat_id = c["id"]; break
    sites = repo.get_sites(category_id=cat_id, limit=100000)
    console.print(f"[cyan]巡检 {len(sites)} 个网站…[/cyan]")
    results = check_many(sites, timeout=cfg.sites.health_check_timeout_seconds,
                         concurrency=cfg.sites.health_check_concurrency)
    for r in results:
        repo.update_site_health(r["id"], status=r["status"],
                                http_status=r.get("http_status"), checked_at=r["checked_at"])
    from collections import Counter
    counts = Counter(r["status"] for r in results)
    console.print(f"[green]✓[/green] 巡检完成：" +
                  " / ".join(f"{k} {v}" for k, v in counts.items()))


@app.command("site-sync")
def site_sync_cmd(
    layout: str | None = typer.Option(None, "--layout", help="cards | table（覆盖配置）"),
):
    """重新生成博客导航页并确保 mkdocs.yml 挂载。"""
    cfg = _load(); repo = _repo(cfg)
    from .sites.blog_renderer import sync_sites_blog
    if layout and layout not in ("cards", "table"):
        console.print("[red]✗[/red] --layout 必须是 cards 或 table"); raise typer.Exit(1)
    r = sync_sites_blog(cfg, repo, layout=layout)
    console.print(f"[green]✓[/green] 已同步 {r['public_count']} 个公开网站 → {r['index_path']}"
                  + ("（mkdocs.yml 已更新）" if r["mkdocs_updated"] else ""))


@app.command()
def ui(
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址（默认仅本地）"),
    port: int = typer.Option(8000, "--port", help="监听端口"),
    open_browser: bool = typer.Option(False, "--open", help="启动后自动打开浏览器"),
):
    """启动本地 Web 控制台 PaperFlow Studio（http://127.0.0.1:8000）。"""
    import threading
    import webbrowser

    try:
        import uvicorn
    except ImportError:
        console.print("[red]缺少 uvicorn，请先 pip install 'uvicorn[standard]'[/red]")
        raise typer.Exit(1)

    url = f"http://{host}:{port}"
    console.print(f"[green]启动 PaperFlow Studio:[/green] {url}")
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    from .web.app import app
    uvicorn.run(app, host=host, port=port, log_level="info")


@app.callback()
def main_version(
    version: bool = typer.Option(False, "--version", help="显示版本号"),
):
    if version:
        console.print(f"PaperFlow {__version__}")
        raise typer.Exit()


def run():
    app()


if __name__ == "__main__":
    run()
