"""Phase 15：全链路闭环验收；所有文件与数据库均隔离在 tmp_path。"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.publisher.sync_blog import publish
from paperflow.utils.timeutil import today_date


def _context(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    cfg.project.paper_repo_dir = str(tmp_path / "paper_repo")
    cfg.publish.auto_git_commit = False
    cfg.publish.auto_git_push = False
    cfg.publish.require_mkdocs_strict_build = False
    repo = PaperRepository(cfg.db_path)
    return cfg, repo


def _add_paper(repo, uid: str, *, fetch_date: str, status: str = PaperStatus.STAGED.value,
               tier: str = "S", **fields) -> PaperRecord:
    values = dict(
        paper_uid=uid, title=f"Title {uid}", normalized_title=f"title {uid}",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date=fetch_date,
        source="arxiv", tier=tier, status=status,
    )
    values.update(fields)
    paper = PaperRecord(**values)
    repo.upsert_paper(paper)
    return repo.get_paper(uid)


def _write_valid_staging(cfg, paper: PaperRecord, *, image: str | None = None):
    target = cfg.workspace_path / "staging" / paper.fetch_date / f"{paper.paper_uid}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    image_md = f"\n![核心架构图]({image})\n" if image else ""
    target.write_text(
        f'---\npaper_uid: "{paper.paper_uid}"\ntitle: "{paper.title}"\n'
        f'venue: "{paper.venue}"\nyear: {paper.pub_year}\ntier: "{paper.tier}"\n'
        'tldr: "闭环测试摘要。"\n---\n\n'
        + "有效正文。" * 100 + image_md,
        encoding="utf-8",
    )
    return target


def test_cross_day_publish_scans_all_unpublished(tmp_path):
    cfg, repo = _context(tmp_path)
    yesterday = (today_date() - timedelta(days=1)).isoformat()
    paper = _add_paper(repo, "arxiv_cross_day", fetch_date=yesterday)
    _write_valid_staging(cfg, paper)

    result = publish(cfg, repo, skip_build_check=True)

    assert result["passed"] == 1
    assert result["date"] == today_date().isoformat()
    assert repo.get_paper(paper.paper_uid).status == PaperStatus.PUBLISHED.value
    assert publish(cfg, repo, skip_build_check=True)["validated"] == 0


def test_single_paper_add_tier_and_retry_close_the_loop(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from paperflow.fetchers.single_adder import SinglePaperAdder
    from paperflow.web.app import create_app

    cfg, repo = _context(tmp_path)
    client = TestClient(create_app(cfg, repo))
    raw = SimpleNamespace(
        doi="", arxiv_id="2603.99999", openreview_id="", title="Manual Closure",
        authors=["Alice"], affiliations=[], venue="CVPR", pub_year=2026,
        pub_date="2026-03-16", abstract="Abstract only.", comment="",
        paper_url="https://arxiv.org/abs/2603.99999", pdf_url="", code_url="",
        project_url="",
    )
    monkeypatch.setattr(SinglePaperAdder, "add", lambda self, url, venue=None: raw)

    added = client.post("/api/papers/add", json={"url": "https://arxiv.org/abs/2603.99999"})
    assert added.status_code == 200
    uid = added.json()["paper_uid"]
    assert added.json()["status"] == PaperStatus.QUEUED.value
    assert (cfg.workspace_path / "queue" / today_date().isoformat() / uid / "prompt.md").exists()

    other = _add_paper(repo, "arxiv_manual_upgrade", fetch_date=today_date().isoformat(),
                       status=PaperStatus.FETCHED.value, tier="B")
    upgraded = client.patch(f"/api/papers/{other.paper_uid}/tier", json={"tier": "A"})
    assert upgraded.json()["status"] == PaperStatus.QUEUED.value
    retried = client.post(f"/api/papers/{other.paper_uid}/retry")
    assert retried.json()["status"] == PaperStatus.QUEUED.value
    assert retried.json()["retry_count"] == 1


def test_paywall_rescue_fallback_and_missing_prompt_close_the_loop(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from paperflow.pipeline.paywall_filter import PaywallFilter
    from paperflow.web.app import create_app

    cfg, repo = _context(tmp_path)
    client = TestClient(create_app(cfg, repo))
    monkeypatch.setattr(
        PaywallFilter, "_arxiv_rescue",
        lambda self, paper: ("2603.12345", "https://arxiv.org/pdf/2603.12345.pdf"),
    )

    def fake_download(paper, target, max_mb, client=None):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.4\nclosure")
        return "ok"

    def fake_extract(paper, config, paper_dir):
        from pathlib import Path
        text_path = Path(paper_dir) / "extracted_text.md"
        text_path.write_text(paper.abstract or paper.title, encoding="utf-8")
        return {"text_path": str(text_path), "figures": []}

    monkeypatch.setattr("paperflow.pipeline.downloader._download_one", fake_download)
    monkeypatch.setattr("paperflow.pipeline.queue_exporter.extract_for_paper", fake_extract)
    rescued = _add_paper(
        repo, "doi_paywall_rescue", fetch_date=today_date().isoformat(),
        status=PaperStatus.SCORED.value, tier="S",
        pdf_url="https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=1",
        paper_url="https://ieeexplore.ieee.org/document/1", abstract="Rescued abstract.",
    )
    repo.add_paywall_paper(
        paper_uid=rescued.paper_uid, title=rescued.title, venue=rescued.venue,
        pub_year=rescued.pub_year, publisher="IEEE Xplore",
        domain="ieeexplore.ieee.org", block_reason="domain_blacklist",
    )
    response = client.post(f"/api/paywall/papers/{rescued.paper_uid}/rescue")
    assert response.status_code == 200
    assert response.json()["action"] == "rescued"
    assert response.json()["status"] == PaperStatus.QUEUED.value
    assert response.json()["oa_rescue_status"] == "RESCUED_ARXIV"
    assert repo.get_paper(rescued.paper_uid).access_type == "open"
    assert repo.get_paywall_paper(rescued.paper_uid)["manual_status"] == "RESCUED"

    fallback = _add_paper(
        repo, "doi_abstract_fallback", fetch_date=today_date().isoformat(),
        status=PaperStatus.SCORED.value, tier="S", abstract="Fallback abstract.",
    )
    repo.add_paywall_paper(
        paper_uid=fallback.paper_uid, title=fallback.title, venue=fallback.venue,
        pub_year=fallback.pub_year, publisher="IEEE Xplore",
        domain="ieeexplore.ieee.org", block_reason="domain_blacklist",
    )
    response = client.post(f"/api/paywall/papers/{fallback.paper_uid}/fallback-abstract")
    assert response.json()["status"] == PaperStatus.QUEUED.value
    manifest = cfg.workspace_path / "queue" / fallback.fetch_date / "queue_manifest.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["count"] == 2

    missing = _add_paper(
        repo, "arxiv_missing_prompt", fetch_date=today_date().isoformat(),
        status=PaperStatus.FETCHED.value, tier="A", abstract="Prompt fallback body.",
    )
    response = client.get(f"/api/analyzer/prompt/{missing.paper_uid}")
    assert response.status_code == 200
    assert "Prompt fallback body." in response.json()["prompt"]
    package = cfg.workspace_path / "queue" / missing.fetch_date / missing.paper_uid
    assert (package / "prompt.md").exists()
    assert (package / "extracted_text.md").exists()

    from paperflow.pipeline.manual_pdf import attach_local_pdf
    monkeypatch.setattr("paperflow.pipeline.extractor.extract_clean_text", lambda path: "manual text")
    monkeypatch.setattr("paperflow.pipeline.extractor.extract_figures", lambda *args: [])
    attached = attach_local_pdf(cfg, repo, rescued.paper_uid, b"%PDF-1.4\nmanual")
    assert attached["status"] == PaperStatus.QUEUED.value
    prompt = client.get(f"/api/analyzer/prompt/{rescued.paper_uid}")
    assert prompt.status_code == 200
    assert rescued.paper_uid in prompt.json()["prompt"]


def test_batch_publish_delegates_to_shared_kernel(tmp_path, monkeypatch):
    from paperflow.publisher import sync_blog

    cfg, repo = _context(tmp_path)
    paper = _add_paper(repo, "arxiv_shared_publish", fetch_date=today_date().isoformat())
    _write_valid_staging(cfg, paper)
    calls = []

    def fake_publish_one(config, repository, paper_uid, *, staging_path=None, dry_run=False):
        calls.append((paper_uid, Path(staging_path), dry_run))
        return {"ok": True, "repo_rel": f"papers/2026/CVPR/{paper_uid}.md"}

    monkeypatch.setattr(sync_blog, "publish_one", fake_publish_one)
    result = sync_blog.publish(cfg, repo, dry_run=True, target_date=paper.fetch_date)
    assert result["passed"] == 1
    assert result["publish_errors"] == []
    assert calls == [(paper.paper_uid, Path(cfg.workspace_path / "staging" / paper.fetch_date / f"{paper.paper_uid}.md"), True)]


def test_cleaner_resolves_relative_blog_path_and_updates_manifest(tmp_path):
    from paperflow.pipeline.cleaner import clean_papers

    cfg, repo = _context(tmp_path)
    paper = _add_paper(
        repo, "arxiv_relative_clean", fetch_date=today_date().isoformat(),
        status=PaperStatus.PUBLISHED.value, tier="S", pdf_url=None,
    )
    blog_rel = f"papers/2026/CVPR/{paper.paper_uid}.md"
    blog_md = cfg.paper_repo_path / "docs" / blog_rel
    blog_md.parent.mkdir(parents=True, exist_ok=True)
    blog_md.write_text("# Published\n", encoding="utf-8")
    pdf = cfg.workspace_path / "tmp" / "pdfs" / f"{paper.paper_uid}.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\ncleanup")
    repo.update_status(
        paper.paper_uid, PaperStatus.PUBLISHED,
        md_blog_path=blog_rel, pdf_local_path=str(pdf),
    )
    queue_dir = cfg.workspace_path / "queue" / paper.fetch_date / paper.paper_uid
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "prompt.md").write_text("prompt", encoding="utf-8")
    manifest_path = queue_dir.parent / "queue_manifest.json"
    manifest_path.write_text(json.dumps({"items": [
        {"paper_uid": paper.paper_uid}, {"paper_uid": "arxiv_keep"},
    ]}), encoding="utf-8")

    result = clean_papers(cfg, repo)
    assert result["cleaned"] == 1
    assert not pdf.exists()
    assert not queue_dir.exists()
    assert repo.get_paper(paper.paper_uid).pdf_deleted == 1
    remaining = json.loads(manifest_path.read_text(encoding="utf-8"))["items"]
    assert remaining == [{"paper_uid": "arxiv_keep"}]


def test_figure_paths_are_normalized_from_prompt_to_blog(tmp_path, monkeypatch):
    from paperflow.analyzers.base import ensure_analysis_package
    from paperflow.pipeline.queue_exporter import export_paper_to_queue
    from paperflow.publisher.blog_articles import publish_one
    from paperflow.utils.figure_links import normalize_blog_image_paths

    cfg, repo = _context(tmp_path)
    paper = _add_paper(
        repo, "arxiv_figure_closure", fetch_date=today_date().isoformat(),
        status=PaperStatus.DOWNLOADED.value, abstract="Figure fallback.",
    )
    assets = cfg.workspace_path / "staging" / "assets" / paper.paper_uid
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "fig_1.webp").write_bytes(b"fake webp")

    ensure_analysis_package(cfg, repo, paper.paper_uid)
    package = cfg.workspace_path / "queue" / paper.fetch_date / paper.paper_uid
    expected_staging = f"../../assets/{paper.paper_uid}/fig_1.webp"
    assert expected_staging in (package / "prompt.md").read_text(encoding="utf-8")

    def fake_extract(record, config, paper_dir):
        text_path = Path(paper_dir) / "extracted_text.md"
        text_path.write_text(record.abstract, encoding="utf-8")
        return {"text_path": str(text_path), "figures": [str(assets / "fig_1.webp")]}

    monkeypatch.setattr("paperflow.pipeline.queue_exporter.extract_for_paper", fake_extract)
    export_paper_to_queue(cfg, repo, paper, paper.fetch_date)
    assert expected_staging in (package / "prompt.md").read_text(encoding="utf-8")

    staging = _write_valid_staging(cfg, paper)
    staging.write_text(staging.read_text(encoding="utf-8") + "\n![架构](fig_1.webp)\n", encoding="utf-8")
    published = publish_one(cfg, repo, paper.paper_uid)
    content = (cfg.paper_repo_path / "docs" / published["repo_rel"]).read_text(encoding="utf-8")
    expected_blog = f"../../../assets/{paper.paper_uid}/fig_1.webp"
    assert expected_blog in content
    assert normalize_blog_image_paths(content, paper.paper_uid) == content
    assert (cfg.paper_repo_path / "docs" / "assets" / paper.paper_uid / "fig_1.webp").exists()


def test_topic_rescore_exempts_global_exclude_keywords(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from paperflow.pipeline.scorer import score_and_persist, score_paper
    from paperflow.web.routes import settings

    cfg, repo = _context(tmp_path)
    cfg.interest_profile.exclude_keywords = ["blocked-keyword"]
    topic = _add_paper(
        repo, "topic_exempt", fetch_date=today_date().isoformat(),
        status=PaperStatus.FETCHED.value, tier="B", abstract="blocked-keyword",
        discovery_mode="topic",
    )
    venue = _add_paper(
        repo, "venue_not_exempt", fetch_date=today_date().isoformat(),
        status=PaperStatus.FETCHED.value, tier="B", abstract="blocked-keyword",
        discovery_mode="venue",
    )
    assert not any(tag.startswith("-blocked-keyword") for tag in score_paper(
        topic, cfg, exempt_exclude_keywords=True,
    ).matched_tags)
    seen = {}
    real_score = score_and_persist

    def recording_score(paper, config, repository, **kwargs):
        seen[paper.paper_uid] = kwargs["exempt_exclude_keywords"]
        return real_score(paper, config, repository, **kwargs)

    monkeypatch.setattr(settings, "reload_config", lambda manager, path: cfg)
    monkeypatch.setattr("paperflow.pipeline.scorer.score_and_persist", recording_score)
    result = settings.rescore(SimpleNamespace(config=cfg, repo=repo))
    assert result["rescored"] >= 2
    assert seen[topic.paper_uid] is True
    assert seen[venue.paper_uid] is False


def test_backfill_dry_run_does_not_write_papers_or_watermark(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from paperflow.pipeline.backfill import BackfillEngine

    cfg, repo = _context(tmp_path)
    raw = SimpleNamespace(
        doi="", arxiv_id="2603.77777", openreview_id="", title="Dry Run Paper",
        authors=["Alice"], affiliations=[], venue="CVPR", pub_year=2026,
        pub_date="2026-03-16", abstract="dry run", comment="", source="arxiv",
        paper_url="https://arxiv.org/abs/2603.77777", pdf_url="", code_url="", project_url="",
    )
    fetcher = SimpleNamespace(fetch_by_date_range=lambda *args, **kwargs: [raw])
    engine = BackfillEngine(cfg, repo, fetchers={"arxiv": fetcher})
    day = today_date()

    result = engine.run_manual(day, day, sources=["arxiv"], dry_run=True)
    assert result.new_papers == 1
    assert repo.get_all_papers() == []
    assert repo.get_watermark("arxiv", "ALL") is None

    engine.run_manual(day, day, sources=["arxiv"], dry_run=False)
    assert len(repo.get_all_papers()) == 1
    assert repo.get_watermark("arxiv", "ALL") is not None


def test_fetch_auto_exports_and_pipeline_topics_follow_steps(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from threading import Event
    from paperflow.web.routes import tasks

    cfg, repo = _context(tmp_path)
    manager = SimpleNamespace(config=cfg, repo=repo)
    result = SimpleNamespace(new_papers=1, tier_s=1, tier_a=0, slices=[])

    class FakeBackfillEngine:
        def __init__(self, config, repository):
            pass

        def run_auto(self, force=False, dry_run=False):
            return result

    calls = []
    monkeypatch.setattr("paperflow.pipeline.backfill.BackfillEngine", FakeBackfillEngine)
    monkeypatch.setattr(
        "paperflow.pipeline.downloader.download_s_papers",
        lambda config, repository: calls.append("download") or {"downloaded": 1},
    )
    monkeypatch.setattr(
        "paperflow.pipeline.queue_exporter.export_queue",
        lambda config, repository, target_date=None: calls.append("export") or {"count": 1},
    )

    def ctx(params):
        return {"manager": manager, "params": params, "emit": lambda **kwargs: None,
                "cancel_event": Event()}

    dry = tasks.run_fetch(ctx({"dry_run": True}))
    assert dry["dry_run"] is True and dry["downloaded"] == 0 and dry["queued"] == 0
    assert calls == []
    fetched = tasks.run_fetch(ctx({}))
    assert fetched["queued"] == 1 and calls == ["download", "export"]

    subscription = SimpleNamespace(
        enabled=True, query="video understanding", name="Video", limit=5,
        only_primary_year=False, top_venues_only=False,
    )
    cfg.topic_search.subscriptions = [subscription]

    class FakeTopicEngine:
        def __init__(self, config, repository):
            pass

        def search(self, *args, **kwargs):
            calls.append("topics")
            return SimpleNamespace(new_inserted_count=2)

    monkeypatch.setattr("paperflow.fetchers.topic_fetcher.TopicSearchEngine", FakeTopicEngine)
    pipelined = tasks.run_pipeline(ctx({"steps": ["topics"]}))
    assert pipelined["topics"] == {"new": 2}
    assert calls[-1] == "topics"


def test_dashboard_and_analyzer_share_pending_count(tmp_path):
    from types import SimpleNamespace
    from paperflow.web.routes.analyzer import analyzer_status
    from paperflow.web.routes.dashboard import summary

    cfg, repo = _context(tmp_path)
    day = today_date().isoformat()
    _add_paper(repo, "pending_downloaded", fetch_date=day, status=PaperStatus.DOWNLOADED.value)
    _add_paper(repo, "pending_queued", fetch_date=day, status=PaperStatus.QUEUED.value)
    _add_paper(repo, "not_pending", fetch_date=day, status=PaperStatus.PUBLISHED.value)
    manager = SimpleNamespace(config=cfg, repo=repo)
    assert summary(manager)["kpi"]["queued"] == 2
    assert analyzer_status(manager)["queue_total"] == 2


def test_aggregator_uses_runtime_year_and_mounts_nav_idempotently(tmp_path):
    from paperflow.publisher.aggregator import rebuild_all

    cfg, repo = _context(tmp_path)
    year = today_date().year
    paper = _add_paper(
        repo, "dynamic_year", fetch_date=today_date().isoformat(),
        status=PaperStatus.PUBLISHED.value, pub_year=year,
        topic_tags_json='["video understanding"]',
    )
    repo.update_status(
        paper.paper_uid, PaperStatus.PUBLISHED,
        md_blog_path=f"papers/{year}/CVPR/{paper.paper_uid}.md",
    )
    mkdocs = cfg.paper_repo_path / "mkdocs.yml"
    mkdocs.parent.mkdir(parents=True, exist_ok=True)
    mkdocs.write_text(
        "site_name: Fixture\nmarkdown_extensions:\n  - attr_list\n"
        "theme:\n  palette:\n    scheme: !!python/name:material.extensions.emoji.twemoji\n"
        "nav:\n  - 首页: index.md\n",
        encoding="utf-8",
    )
    rebuild_all(cfg, repo)
    first = mkdocs.read_text(encoding="utf-8")
    assert f"sota-{year}.md" in {p.name for p in (cfg.paper_repo_path / "docs" / "matrix").iterdir()}
    assert "研究方向:" in first and "topics/video-understanding/" in first
    assert "趋势周报:" in first and f"weekly/{year}/" in first
    assert "!!python/name:material.extensions.emoji.twemoji" in first
    rebuild_all(cfg, repo)
    assert mkdocs.read_text(encoding="utf-8") == first


def test_reload_config_refreshes_app_manager_and_mkdocs_service(tmp_path):
    import yaml
    from paperflow.web.app import create_app
    from paperflow.web.task_manager import reload_config

    cfg, repo = _context(tmp_path)
    app = create_app(cfg, repo)
    data = cfg.model_dump(mode="json")
    data["project"]["workspace_dir"] = str(tmp_path / "new-workspace")
    data["project"]["paper_repo_dir"] = str(tmp_path / "new-paper-repo")
    data["publish"]["preview_port"] = 9999
    new_path = tmp_path / "new-config.yaml"
    new_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    updated = reload_config(app.state.manager, new_path)
    assert app.state.manager.config is updated
    assert app.state.config is updated
    assert app.state.mkdocs_service.paper_repo == updated.paper_repo_path.resolve()
    assert app.state.mkdocs_service.workspace == updated.workspace_path.resolve()
    assert app.state.mkdocs_service.preview_port == 9999


def test_daily_script_exposes_auto_analyze_and_real_database_stats():
    script_bytes = Path("scripts/run_daily_fetch.ps1").read_bytes()
    assert script_bytes.startswith(b"\xef\xbb\xbf")  # Windows PowerShell 5.1 需 BOM 识别 UTF-8。
    script = script_bytes.decode("utf-8-sig")
    assert "[switch]$AutoAnalyze" in script
    assert "python -m paperflow analyze" in script
    assert "PaperRepository(cfg.db_path)" in script
    assert '"new_today"' in script and '"pending"' in script
    assert "今日拉取与队列导出已完成" not in script
