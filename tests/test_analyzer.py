"""Phase 11 验收：AI 解析引擎（全部 Mock 离线，不消耗真实 Token）。

基于 08_AI_ANALYZER_CLAUDE_AND_HARNESS.md 第 7 节全部场景。
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from paperflow.analyzers.base import (
    AnalysisResult,
    BaseAnalyzer,
    sanitize_markdown_output,
    smart_truncate,
)
from paperflow.analyzers.claude_cli_analyzer import (
    ClaudeCliAnalyzer,
    resolve_claude_executable,
)
from paperflow.analyzers.runner import AnalyzerRunner
from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.web.app import create_app


VALID_MD = (
    "---\n"
    'paper_uid: "arxiv_2603.00001"\n'
    'title: "AI Analyzer Test Paper"\n'
    'venue: "CVPR"\n'
    "year: 2026\n"
    'tier: "S"\n'
    'tldr: "一句话总结本文核心贡献，足够长度。"\n'
    "---\n\n"
    "# AI Analyzer Test Paper\n\n"
    + "这是一段用于满足最小正文长度要求的测试正文内容。" * 30 + "\n\n"
    "<!-- PAPERFLOW_METRICS_JSON\n"
    '{"task":"Video Understanding","backbone":"ViT-L","datasets":["K400"],'
    '"sota_summary":"mAP 70%","innovation_tags":["Zero-Shot"]}\n'
    "-->\n"
)
INVALID_MD_NO_TLDR = VALID_MD.replace('tldr: "一句话总结本文核心贡献，足够长度。"\n', "")


@pytest.fixture
def ctx(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    cfg.project.paper_repo_dir = str(tmp_path / "paper_repo")
    cfg.analyzer.max_retries = 2
    cfg.analyzer.cooldown_seconds = 0
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(PaperRecord(
        paper_uid="arxiv_2603.00001", title="AI Analyzer Test Paper",
        normalized_title="ai analyzer test paper", authors_json="[]",
        venue="CVPR", pub_year=2026, pub_date="2026-11-21",
        fetch_date="2026-11-21", source="arxiv", tier="S",
        status=PaperStatus.QUEUED.value, abstract="A test abstract about video understanding.",
    ))
    # 构造队列任务包
    qdir = cfg.workspace_path / "queue" / "2026-11-21" / "arxiv_2603.00001"
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "prompt.md").write_text("# Prompt\n请分析这篇论文。", encoding="utf-8")
    (qdir / "extracted_text.md").write_text("Full extracted text of the paper.", encoding="utf-8")
    return {"cfg": cfg, "repo": repo, "qdir": qdir}


class FakeProc:
    """模拟 subprocess.Popen：按 outputs 序列返回 stdout。"""

    instances: list["FakeProc"] = []

    def __init__(self, outputs, **kwargs):
        self.outputs = list(outputs)
        self.calls = 0
        self.returncode = 0
        self.terminated = False
        self.kwargs = kwargs
        FakeProc.instances.append(self)

    def communicate(self, input=None, timeout=None):
        out = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return out, ""

    def poll(self):
        return self.returncode if self.terminated else None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture(autouse=True)
def reset_fake():
    FakeProc.instances.clear()


def _patch_popen(monkeypatch, outputs):
    """Patch Popen：所有实例共享同一个输出序列（模拟多轮重试返回不同内容）。"""
    import paperflow.analyzers.claude_cli_analyzer as mod

    shared = {"index": 0}

    class SharedFakeProc(FakeProc):
        def communicate(self, input=None, timeout=None):
            out = outputs[min(shared["index"], len(outputs) - 1)]
            shared["index"] += 1
            self.last_input = input
            self.calls += 1
            return out, ""

    def factory(*args, **kwargs):
        return SharedFakeProc(outputs, **kwargs)

    monkeypatch.setattr(mod.subprocess, "Popen", factory)
    monkeypatch.setattr(mod, "resolve_claude_executable", lambda exe: "/fake/claude")


# ---------------- 1. 清洗器 ----------------

def test_sanitize_markdown_output():
    raw = "Sure! Here is the result:\n```markdown\n" + VALID_MD + "\n```\n"
    cleaned = sanitize_markdown_output(raw)
    assert cleaned.startswith("---")
    assert "Sure!" not in cleaned
    assert "```" not in cleaned


def test_smart_truncate():
    long = "A" * 120000
    result = smart_truncate(long, 60000)
    assert len(result) <= 60000
    assert "省略" in result
    assert result.startswith("A") and result.endswith("A")


# ---------------- 2. Claude CLI Mock ----------------

def test_claude_cli_success_pipeline(ctx, monkeypatch):
    _patch_popen(monkeypatch, [VALID_MD])
    runner = AnalyzerRunner(ctx["cfg"], ctx["repo"], backend="claude_cli")
    result = runner.analyze_one("arxiv_2603.00001")

    assert result.ok is True
    assert result.status == "SUCCESS"
    assert Path(result.staging_path).exists()
    assert result.staging_path.endswith("arxiv_2603.00001.md")
    saved = ctx["repo"].get_paper("arxiv_2603.00001")
    assert saved.status == PaperStatus.STAGED.value
    assert ctx["repo"].get_metrics("arxiv_2603.00001")["backbone"] == "ViT-L"
    runs = ctx["repo"].get_analysis_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "SUCCESS" and runs[0]["backend"] == "claude_cli"
    # 非交互 UTF-8 参数
    proc = FakeProc.instances[0]
    assert proc.kwargs["shell"] is False
    assert proc.kwargs["encoding"] == "utf-8"
    assert proc.kwargs["errors"] == "replace"


def test_self_healing_retry(ctx, monkeypatch):
    _patch_popen(monkeypatch, [INVALID_MD_NO_TLDR, VALID_MD])
    runner = AnalyzerRunner(ctx["cfg"], ctx["repo"], backend="claude_cli")
    result = runner.analyze_one("arxiv_2603.00001")

    assert result.ok is True
    assert result.attempt == 2
    runs = ctx["repo"].get_analysis_runs()  # id DESC：最新在前
    assert len(runs) == 2
    assert runs[0]["status"] == "SUCCESS" and runs[0]["attempt"] == 2
    assert runs[1]["status"] == "VALIDATION_FAILED" and runs[1]["attempt"] == 1
    # 第 2 次 communicate 的 stdin 应包含上次报错信息
    second_proc = FakeProc.instances[1]
    assert "缺少 tldr" in second_proc.last_input


def test_retry_prompt_contains_errors(ctx, monkeypatch):
    """直接验证 build_prompt 在带 previous_errors 时拼接了错误原因。"""
    _patch_popen(monkeypatch, [VALID_MD])
    analyzer = ClaudeCliAnalyzer(ctx["cfg"], ctx["repo"])
    prompt = analyzer.build_prompt("arxiv_2603.00001", ["缺少 tldr 字段"])
    assert "缺少 tldr 字段" in prompt
    assert "上次输出未通过格式校验" in prompt
    assert "必须以 `---`" in prompt


def test_cancel_event_terminates_process(ctx, monkeypatch):
    event = threading.Event()
    event.set()  # 预先置位：runner 在第一次尝试前直接取消

    runner = AnalyzerRunner(ctx["cfg"], ctx["repo"], backend="claude_cli")
    result = runner.analyze_one("arxiv_2603.00001", cancel_event=event)
    assert result.status == "CANCELLED"
    assert not Path(ctx["cfg"].workspace_path / "staging" / "2026-11-21" / "arxiv_2603.00001.md").exists()


def test_timeout_cleans_up(ctx, monkeypatch):
    import paperflow.analyzers.claude_cli_analyzer as mod

    def timeout_call(self, prompt, **kwargs):
        raise TimeoutError("模拟超时")

    monkeypatch.setattr(ClaudeCliAnalyzer, "_call", timeout_call)
    runner = AnalyzerRunner(ctx["cfg"], ctx["repo"], backend="claude_cli")
    result = runner.analyze_one("arxiv_2603.00001")
    assert result.status == "TIMEOUT"
    assert result.ok is False
    assert ctx["repo"].get_analysis_runs()[0]["status"] == "TIMEOUT"


# ---------------- 3. Harness Web 协作接口 ----------------

@pytest.fixture
def web_ctx(ctx):
    app = create_app(ctx["cfg"], ctx["repo"])
    return {"client": TestClient(app), **ctx}


def test_harness_prompt_api(web_ctx):
    r = web_ctx["client"].get("/api/analyzer/prompt/arxiv_2603.00001")
    assert r.status_code == 200
    data = r.json()
    assert "请分析这篇论文" in data["prompt"]
    assert "Full extracted text" in data["prompt"]
    assert data["chars"] > 0


def test_harness_import_md_api(web_ctx):
    raw = "Here you go:\n```markdown\n" + VALID_MD + "\n```"
    r = web_ctx["client"].post(
        "/api/analyzer/import-md/arxiv_2603.00001", json={"markdown": raw}
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    staging = Path(r.json()["staging_path"])
    assert staging.exists()
    assert staging.read_text(encoding="utf-8").startswith("---")
    run = web_ctx["repo"].get_analysis_runs()[0]
    assert run["backend"] == "harness_web"
    assert run["status"] == "SUCCESS"
    assert web_ctx["repo"].get_paper("arxiv_2603.00001").status == PaperStatus.STAGED.value


def test_analyzer_read_apis(web_ctx):
    c = web_ctx["client"]
    assert c.get("/api/analyzer/status").status_code == 200
    assert c.get("/api/analyzer/queue").status_code == 200
    assert c.get("/api/analyzer/history").status_code == 200
    assert c.get("/api/analyzer/batch-instruction").status_code == 200


# ---------------- 4. resolve executable ----------------

def test_resolve_executable_windows_extensions(monkeypatch):
    import paperflow.analyzers.claude_cli_analyzer as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/fake/claude.cmd" if name == "claude.cmd" else None)
    assert resolve_claude_executable("claude") == "/fake/claude.cmd"


# ---------------- 5. 本地已下载论文直接解析 ----------------

def test_downloaded_paper_appears_in_queue(web_ctx):
    """DOWNLOADED 论文（本地PDF已下载）应出现在解析中心队列。"""
    from paperflow.db.models import PaperRecord, PaperStatus
    repo = web_ctx["repo"]
    repo.upsert_paper(PaperRecord(
        paper_uid="arxiv_dl_test", title="Downloaded Local Paper",
        normalized_title="downloaded local paper", authors_json="[]",
        venue="CVPR", pub_year=2026, fetch_date="2026-11-22", source="arxiv",
        tier="S", status=PaperStatus.DOWNLOADED.value,
    ))
    items = web_ctx["client"].get("/api/analyzer/queue").json()["items"]
    hit = next((x for x in items if x["paper_uid"] == "arxiv_dl_test"), None)
    assert hit is not None
    assert hit["status"] == "DOWNLOADED"


def test_ensure_package_from_local_pdf(ctx):
    """DOWNLOADED 论文从本地 PDF 即时生成 prompt + extracted_text。"""
    import fitz
    from paperflow.analyzers.base import ensure_analysis_package
    cfg, repo = ctx["cfg"], ctx["repo"]
    repo.upsert_paper(PaperRecord(
        paper_uid="arxiv_pkg_1", title="Local Package Paper",
        normalized_title="local package paper", authors_json="[]",
        venue="CVPR", pub_year=2026, fetch_date="2026-11-22", source="arxiv",
        tier="S", status=PaperStatus.DOWNLOADED.value,
        topic_tags_json='["Agent"]',
    ))
    pdfs = cfg.workspace_path / "tmp" / "pdfs"
    pdfs.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(); pg = doc.new_page()
    pg.insert_text((72, 72), "Local Package Paper about agent reasoning")
    doc.save(str(pdfs / "arxiv_pkg_1.pdf")); doc.close()

    d = ensure_analysis_package(cfg, repo, "arxiv_pkg_1")
    prompt = (d / "prompt.md").read_text(encoding="utf-8")
    assert (d / "extracted_text.md").exists()
    assert "13. 调研、思考" in prompt  # 用户原版 13 节深度分析提示词
    assert "你可以借助本地的skills来完成" in prompt
    assert "{{" not in prompt  # 占位符已全部渲染


def test_import_local_pdf_api(web_ctx):
    """上传本地 PDF 直接导入解析队列；非 PDF 拒绝。"""
    import io
    import fitz
    c = web_ctx["client"]
    doc = fitz.open(); pg = doc.new_page()
    pg.insert_text((72, 72), "Imported Paper Title About Vision")
    buf = io.BytesIO(); doc.save(buf); doc.close()
    r = c.post("/api/analyzer/import-local-pdf",
               files={"file": ("paper.pdf", buf.getvalue(), "application/pdf")},
               data={"title": "Imported Paper Title", "venue": "CVPR", "tier": "S"})
    assert r.status_code == 200
    assert r.json()["text_chars"] > 0
    assert r.json()["status"] == "QUEUED"
    bad = c.post("/api/analyzer/import-local-pdf",
                 files={"file": ("bad.txt", b"<html>no pdf</html>", "text/html")})
    assert bad.status_code == 400


# ---------------- 6. Harness CLI 协作 + 结果查看/同步 ----------------

def test_harness_cli_health_and_patch(tmp_path):
    """HarnessCliAnalyzer 生成 model patch，健康检测优雅返回。"""
    from paperflow.analyzers.harness_cli_analyzer import HarnessCliAnalyzer
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    # headless 不支持 kimi-code，应自动回退到 workbuddy/hy4flash
    a = HarnessCliAnalyzer(cfg, repo, model="k3.1-pro", provider="kimi-code")
    patch = a._write_model_patch()
    assert patch is not None
    body = patch.read_text(encoding="utf-8")
    assert "hy4flash" in body and "workbuddy" in body
    # 支持的 provider 则原样使用
    a2 = HarnessCliAnalyzer(cfg, repo, model="hy4flash", provider="workbuddy")
    assert "hy4flash" in a2._write_model_patch().read_text(encoding="utf-8")
    h = a.health_check()
    assert "ok" in h and "backend" in h


def test_result_and_sync_to_blog(web_ctx):
    """解析结果可本地查看，并可同步到博客仓库。"""
    from paperflow.db.models import PaperRecord, PaperStatus
    cfg, repo, c = web_ctx["cfg"], web_ctx["repo"], web_ctx["client"]
    repo.upsert_paper(PaperRecord(
        paper_uid="arxiv_result_1", title="Result Paper", normalized_title="result paper",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-22",
        source="arxiv", tier="S", status=PaperStatus.STAGED.value,
    ))
    md_dir = cfg.workspace_path / "staging" / "2026-11-22"
    md_dir.mkdir(parents=True, exist_ok=True)
    md = md_dir / "arxiv_result_1.md"
    md.write_text("---\npaper_uid: \"arxiv_result_1\"\n---\n# Result\n\ncontent", encoding="utf-8")

    r = c.get("/api/analyzer/result/arxiv_result_1")
    assert r.status_code == 200 and "Result Paper" not in r.json()["content"]
    assert "# Result" in r.json()["content"]

    r = c.post("/api/analyzer/sync-to-blog/arxiv_result_1")
    assert r.status_code == 200, r.text
    dest = Path(r.json()["blog_path"])
    assert dest.exists()
    assert repo.get_paper("arxiv_result_1").status == PaperStatus.PUBLISHED.value


# ---------------- 7. 解析进度追踪与断点 ----------------

def test_analysis_run_lifecycle(ctx):
    """解析开始 RUNNING、结束删除并写终态审计，阶段可追踪。"""
    from paperflow.db.models import PaperRecord
    repo = ctx["repo"]
    repo.upsert_paper(PaperRecord(paper_uid="arxiv_prog_1", title="P1", normalized_title="p1",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-22", source="arxiv", tier="S"))
    rid = repo.start_analysis_run(paper_uid="arxiv_prog_1", backend="claude_cli", task_id="t1")
    assert any(r["id"] == rid and r["status"] == "RUNNING"
               for r in repo.get_analysis_runs(paper_uid="arxiv_prog_1"))
    repo.update_analysis_run(rid, stage="generating")
    row = next(r for r in repo.get_analysis_runs(paper_uid="arxiv_prog_1") if r["id"] == rid)
    assert row["stage"] == "generating"
    repo.delete_analysis_run(rid)
    assert not any(r["id"] == rid for r in repo.get_analysis_runs(paper_uid="arxiv_prog_1"))


def test_mark_interrupted_runs(ctx):
    """重启时把遗留 RUNNING 标记为 INTERRUPTED。"""
    from paperflow.db.models import PaperRecord
    repo = ctx["repo"]
    repo.upsert_paper(PaperRecord(paper_uid="arxiv_prog_2", title="P2", normalized_title="p2",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-22", source="arxiv", tier="S"))
    rid = repo.start_analysis_run(paper_uid="arxiv_prog_2", backend="claude_cli")
    n = repo.mark_interrupted_runs()
    assert n >= 1
    row = next(r for r in repo.get_analysis_runs(paper_uid="arxiv_prog_2") if r["id"] == rid)
    assert row["status"] == "INTERRUPTED"
    assert row["finished_at"]


def test_progress_and_resume_api(web_ctx):
    repo, c = web_ctx["repo"], web_ctx["client"]
    r = c.get("/api/analyzer/progress")
    assert r.status_code == 200
    assert "running" in r.json() and "papers" in r.json()
    r = c.post("/api/analyzer/resume-check", json={"paper_uids": ["arxiv_x"]})
    assert r.status_code == 200 and "arxiv_x" in r.json()["resume"]


# ---------------- 8. 引擎能力注册表（Phase 15 可插拔） ----------------

def test_engine_registry():
    """引擎注册表提供数据驱动的下拉清单，含 mode/model/check 能力。"""
    from paperflow.analyzers.engine_registry import list_engines
    engines = list_engines()
    ids = {e["id"] for e in engines}
    assert {"claude_cli", "harness_cli", "harness_web"} <= ids
    by_id = {e["id"]: e for e in engines}
    assert by_id["claude_cli"]["mode"] == "auto"
    assert by_id["harness_cli"]["mode"] == "auto"
    assert by_id["harness_web"]["mode"] == "auto"
    assert all("supports_model" in e and "supports_check" in e for e in engines)


def test_engines_api(web_ctx):
    c = web_ctx["client"]
    r = c.get("/api/analyzer/engines")
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 3


# ---------------- 9. 一键全自动流水线 + HTTP 环境修复 ----------------

def test_pipeline_endpoint_empty_steps(web_ctx):
    """pipeline 端点可提交；空 steps 直接完成，不触碰真实数据。"""
    c = web_ctx["client"]
    r = c.post("/api/tasks/pipeline", json={"steps": [], "engine": "harness_cli"})
    assert r.status_code == 200 and r.json()["command"] == "pipeline"


def test_no_proxy_sanitize(monkeypatch):
    """畸形 NO_PROXY [::1] 被清理，其余项保留。"""
    from paperflow.utils.http_env import sanitize_no_proxy
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1,[::1]")
    sanitize_no_proxy()
    val = __import__("os").environ["NO_PROXY"]
    assert "[::1]" not in val
    assert "localhost" in val and "127.0.0.1" in val


# ---------------- 10. 提示词完整送达下游 ----------------

def test_prompt_never_truncated_even_with_tiny_budget(ctx):
    """提示词本体（13 节要求）在任何预算下都完整，只截断论文正文。"""
    from paperflow.analyzers.base import BaseAnalyzer, ensure_analysis_package
    cfg, repo = ctx["cfg"], ctx["repo"]
    # 极小预算：正文会被截断，但提示词不能缺
    cfg.analyzer.max_input_chars = 800
    repo.upsert_paper(PaperRecord(
        paper_uid="arxiv_prompt_1", title="Prompt Paper", normalized_title="prompt paper",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-22",
        source="arxiv", tier="S", status=PaperStatus.DOWNLOADED.value,
        abstract="abstract", topic_tags_json='["Agent"]',
    ))
    d = ensure_analysis_package(cfg, repo, "arxiv_prompt_1")
    # 写一个很长的正文
    (d / "extracted_text.md").write_text("BODY " * 5000, encoding="utf-8")

    class _Dummy(BaseAnalyzer):
        backend = "dummy"
        def generate(self, prompt, **kw):
            return "", "dummy"
        def health_check(self, probe=False):
            return {"ok": True}

    p = _Dummy(cfg, repo).build_prompt("arxiv_prompt_1")
    # 13 节深度分析的关键标记必须全部在最终 prompt 中
    for marker in ("13. 调研、思考", "follow up的idea", "Andrej Karpathy", "明确声称",
                   "take aways", "Intuition", "最脆弱的假设", "最小复现实验"):
        assert marker in p, f"提示词被截断，缺失: {marker}"
    # 正文确实被截断（有省略标记）
    assert "中间部分因长度限制已省略" in p


def test_communicate_once_writes_prompt_once():
    """communicate_once 只向 stdin 写入一次 prompt（防重复拼接乱码）。"""
    from paperflow.analyzers.base import communicate_once
    script = (
        "import sys\n"
        "data = sys.stdin.read()\n"
        "sys.stdout.write('LEN=' + str(len(data)))\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", script],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    prompt = "SECTION1\nSECTION2\nSECTION3\n" * 100  # 明确长度
    out, err = communicate_once(proc, prompt, timeout=10)
    assert f"LEN={len(prompt)}" in out, out[:200]


# ---------------- 11. 下游解析错误详单 ----------------

def test_analysis_error_to_detail():
    """AnalysisError 携带 stderr/http_status/exit_code 等结构化字段。"""
    import json
    from paperflow.analyzers.base import AnalysisError
    e = AnalysisError("CLI failed", error_type="cli_nonzero_exit",
                      stderr="traceback here", exit_code=2)
    d = e.to_detail()
    assert d["error_type"] == "cli_nonzero_exit"
    assert d["stderr"] == "traceback here" and d["exit_code"] == 2
    assert json.loads(json.dumps(d, ensure_ascii=False))["exit_code"] == 2


def test_cli_nonzero_exit_records_detail(ctx, monkeypatch):
    """下游 CLI 非零退出时，错误详单落库到 error_detail。"""
    import json
    from paperflow.analyzers.base import AnalysisError
    from paperflow.analyzers.runner import AnalyzerRunner
    cfg, repo = ctx["cfg"], ctx["repo"]

    class _FailAnalyzer:
        backend = "dummy"
        def __init__(self, *a, **kw): self.model = "test-model"
        def build_prompt(self, uid, prev=None): return "prompt"
        def generate(self, prompt, **kw):
            raise AnalysisError("engine exploded", error_type="cli_nonzero_exit",
                                stderr="FATAL STACK", exit_code=3)
        def health_check(self, probe=False): return {"ok": True}

    monkeypatch.setattr("paperflow.analyzers.runner.create_analyzer",
                        lambda *a, **kw: _FailAnalyzer())
    runner = AnalyzerRunner(cfg, repo, backend="dummy")
    # 造一篇 SCORED 论文，runner 需要它存在
    from paperflow.db.models import PaperRecord, PaperStatus
    repo.upsert_paper(PaperRecord(paper_uid="arxiv_err_1", title="Err", normalized_title="err",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-22",
        source="arxiv", tier="S", status=PaperStatus.QUEUED.value))
    r = runner.analyze_one("arxiv_err_1", task_id="t_err")
    assert r.status == "ERROR"
    runs = repo.get_analysis_runs(paper_uid="arxiv_err_1")
    assert runs
    detail = json.loads(runs[0]["error_detail"])
    assert detail["error_type"] == "cli_nonzero_exit"
    assert detail["stderr"] == "FATAL STACK" and detail["exit_code"] == 3
