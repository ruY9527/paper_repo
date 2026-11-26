"""验证 publish 不再因嵌套 dict 类型的 metrics 失败（原 sqlite binding 错误）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository


def test_upsert_metrics_nested_dict(tmp_path):
    """metrics 的 task/backbone/sota_summary 是嵌套 dict 时也能安全落库。"""
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(PaperRecord(
        paper_uid="arxiv_m1", title="M", normalized_title="m", authors_json="[]",
        venue="CVPR", pub_year=2026, fetch_date="2026-11-22", source="arxiv", tier="S",
    ))
    repo.upsert_metrics("arxiv_m1", {
        "task": {"goal": "nested task"},
        "backbone": {"agent": "gpt", "planner": "x"},
        "datasets": {"games": 10, "names": ["a", "b"]},
        "sota_summary": {"metric": {"low": 1.2}},
        "innovation_tags": ["tag1"],
        "user_rating": {"score": 5},
    })
    row = repo._connect().execute(
        "SELECT backbone, datasets_json FROM paper_metrics WHERE paper_uid='arxiv_m1'"
    ).fetchone()
    assert "agent" in row["backbone"]  # dict 已序列化
    assert "games" in row["datasets_json"]


def test_publish_with_nested_metrics(tmp_path):
    """端到端：staging 含嵌套 dict metrics 时，publish 不抛异常。"""
    import json
    from paperflow.publisher.sync_blog import publish
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo_dir = tmp_path / "paper_repo"
    (repo_dir / "docs").mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy(Path(__file__).resolve().parents[1] / "paper_repo" / "mkdocs.yml", repo_dir / "mkdocs.yml")
    cfg.project.paper_repo_dir = str(repo_dir)
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(PaperRecord(
        paper_uid="arxiv_m2", title="M2", normalized_title="m2", authors_json="[]",
        venue="CVPR", pub_year=2026, fetch_date="2026-11-22", source="arxiv", tier="S",
        status=PaperStatus.QUEUED.value,
    ))
    from paperflow.utils.timeutil import today_date
    sd = cfg.workspace_path / "staging" / today_date().isoformat()
    sd.mkdir(parents=True, exist_ok=True)
    metrics = {"task": {"goal": "x"}, "backbone": {"name": "ViT"}, "sota_summary": {"m": 1}}
    (sd / "arxiv_m2.md").write_text(
        "---\npaper_uid: \"arxiv_m2\"\ntitle: \"M2\"\nvenue: CVPR\nyear: 2026\ntier: S\ntldr: test\n---\n"
        + "# Body\n" + "x" * 400 + "\n\n<!-- PAPERFLOW_METRICS_JSON\n"
        + json.dumps(metrics, ensure_ascii=False) + "\n-->\n",
        encoding="utf-8",
    )
    result = publish(cfg, repo, push=False, clean=False, dry_run=False, skip_build_check=True)
    assert result["passed"] >= 1
