"""批量解析失败日志可见性：失败不能再静默。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.analyzers.runner import AnalyzerRunner


def test_failed_paper_emits_error_log(tmp_path, monkeypatch):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    for uid in ("ok1", "fail1"):
        repo.upsert_paper(PaperRecord(paper_uid=uid, title=uid, normalized_title=uid,
            authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-23",
            source="arxiv", tier="S", status=PaperStatus.QUEUED.value))

    class FakeAnalyzer:
        backend = "fake"; model = "m"
        def build_prompt(self, uid, prev=None): return "p"
        def generate(self, prompt, **kw):
            if kw.get("paper_uid") == "fail1":
                raise RuntimeError("模拟模型调用失败")
            return ("---\npaper_uid: ok1\ntitle: T\nvenue: CVPR\nyear: 2026\ntier: S\ntldr: t\n---\n"
                    + "x" * 500), "m"
        def health_check(self, probe=False): return {"ok": True}

    monkeypatch.setattr("paperflow.analyzers.runner.create_analyzer",
                        lambda *a, **k: FakeAnalyzer())
    events = []
    AnalyzerRunner(cfg, repo, backend="fake").run_batch(
        ["ok1", "fail1"], progress_cb=lambda **kw: events.append(kw))

    # 失败论文必须有 ERROR 级日志，且带原因
    err_logs = [e for e in events
                if "fail1" in (e.get("message") or "") and e.get("level") == "ERROR"]
    assert err_logs, "失败论文没有 ERROR 日志"
    assert any("模拟模型调用失败" in e["message"] for e in err_logs)
    # 每篇都有明确终态结果
    results = [e for e in events if e.get("stage") == "paper_result"]
    assert len(results) == 2
    assert any(e.get("level") == "ERROR" and "fail1" in e["message"] for e in results)
    assert any(e.get("level") == "INFO" and "✓ ok1" in e["message"] for e in results)
