"""解析进度条验收：阶段驱动 percent，单调推进、不再瞬间 100%。"""

from __future__ import annotations

import os
from pathlib import Path

from paperflow.config import AppConfig, load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.analyzers.runner import AnalyzerRunner


def test_progress_stage_driven(tmp_path, monkeypatch):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(PaperRecord(paper_uid="p1", title="P", normalized_title="p",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-05-01",
        source="arxiv", tier="S", status=PaperStatus.DOWNLOADED.value))

    class FakeAnalyzer:
        backend = "fake"; model = "m"
        def build_prompt(self, uid, prev=None): return "prompt"
        def generate(self, prompt, **kw):
            return ("---\npaper_uid: p1\ntitle: P\nvenue: CVPR\nyear: 2026\ntier: S\ntldr: t\n---\n"
                    + "x" * 500), "m"
        def health_check(self, probe=False): return {"ok": True}

    monkeypatch.setattr("paperflow.analyzers.runner.create_analyzer", lambda *a, **k: FakeAnalyzer())
    events = []
    AnalyzerRunner(cfg, repo, backend="fake").run_batch(
        ["p1"], progress_cb=lambda **kw: events.append(kw))
    stages = [(e.get("stage"), e.get("percent")) for e in events if e.get("percent") is not None]
    assert ("building_prompt", 10.0) in stages
    assert ("generating", 45.0) in stages
    assert ("validating", 85.0) in stages
    # 中间阶段不超过 95%；完成事件（paper_result）才 100%
    done_stages = {"paper_result", "paper_done"}
    before_done = [p for s, p in stages if s not in done_stages]
    assert max(before_done) <= 95.0
    assert any(s in done_stages and p == 100.0 for s, p in stages)


def test_batch_progress_scaled(tmp_path, monkeypatch):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    for uid in ("p1", "p2"):
        repo.upsert_paper(PaperRecord(paper_uid=uid, title=uid, normalized_title=uid,
            authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-05-01",
            source="arxiv", tier="S", status=PaperStatus.DOWNLOADED.value))

    class FakeAnalyzer:
        backend = "fake"; model = "m"
        def build_prompt(self, uid, prev=None): return "prompt"
        def generate(self, prompt, **kw):
            uid = "p1"  # 简化：校验器按文件名取 UID，两个文件都写 p1 内容
            return ("---\npaper_uid: p2\ntitle: P\nvenue: CVPR\nyear: 2026\ntier: S\ntldr: t\n---\n"
                    + "x" * 500), "m"
        def health_check(self, probe=False): return {"ok": True}

    monkeypatch.setattr("paperflow.analyzers.runner.create_analyzer", lambda *a, **k: FakeAnalyzer())
    events = []
    AnalyzerRunner(cfg, repo, backend="fake").run_batch(
        ["p1", "p2"], progress_cb=lambda **kw: events.append(kw))
    # 两篇时每篇 span=50：generating 第一篇=50*0.45=22.5，第二篇=50+22.5=72.5
    gens = [e["percent"] for e in events if e.get("stage") == "generating"]
    assert 22.5 in gens and 72.5 in gens
