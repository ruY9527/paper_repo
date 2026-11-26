"""Phase 12 验收：构建门禁 + Prompt 工作室（模块 D）。

基于 09_BLOG_PREVIEW_GATE_AND_PROMPT_STUDIO.md 模块 D 全部场景，离线可测。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.prompt_manager import PromptManager, render_prompt
from paperflow.publisher.mkdocs_service import MkDocsService
from paperflow.web.app import create_app


# ---------------- fixtures ----------------

@pytest.fixture
def cfg(tmp_path):
    c = load_example_config()
    c.project.workspace_dir = str(tmp_path / "workspace")
    c.project.paper_repo_dir = str(tmp_path / "paper_repo")
    return c


@pytest.fixture
def repo(cfg):
    return PaperRepository(cfg.db_path)


def _make_paper(repo, uid="arxiv_2603.00001", tier="S", topics=None, title="Test", abstract="test"):
    repo.upsert_paper(PaperRecord(
        paper_uid=uid, title=title, normalized_title=uid.lower(),
        authors_json='["Alice"]', venue="CVPR", pub_year=2026,
        pub_date="2026-11-21", fetch_date="2026-11-21", source="arxiv",
        tier=tier, status=PaperStatus.QUEUED.value, abstract=abstract,
        topic_tags_json=json.dumps(topics or [], ensure_ascii=False),
    ))


def _make_real_repo(repo_dir: Path):
    """构造一个最小可构建的 mkdocs 仓库。"""
    (repo_dir / "docs").mkdir(parents=True, exist_ok=True)
    (repo_dir / "mkdocs.yml").write_text(
        "site_name: Test\nsite_dir: site\ntheme:\n  name: material\n", encoding="utf-8"
    )
    (repo_dir / "docs" / "index.md").write_text("# Home\n", encoding="utf-8")


# ---------------- 1. MkDocs 构建门禁 ----------------

def test_build_strict_ok_no_site_residue(cfg):
    _make_real_repo(cfg.paper_repo_path)
    svc = MkDocsService(cfg.paper_repo_path, cfg.workspace_path, cfg.publish.preview_port)
    result = svc.build_strict()
    assert result.ok is True
    # 关键：不得在 paper_repo 内残留 site
    assert not (cfg.paper_repo_path / "site").exists()


def test_build_strict_broken_link(cfg):
    _make_real_repo(cfg.paper_repo_path)
    (cfg.paper_repo_path / "docs" / "broken.md").write_text(
        "# Broken\n\n![x](non_existent.webp)\n", encoding="utf-8"
    )
    svc = MkDocsService(cfg.paper_repo_path, cfg.workspace_path, cfg.publish.preview_port)
    result = svc.build_strict()
    # 断链在 mkdocs --strict 下可能为 WARNING 或 ERROR，取决于版本；只要 ok=False 或 issues 非空即可
    assert (result.ok is False) or (result.warning_count > 0 or result.error_count > 0)
    assert not (cfg.paper_repo_path / "site").exists()


def test_publish_gate_blocks_on_broken_link(cfg, repo, monkeypatch):
    """门禁开启 + 断链 -> publish 拦截 git 提交。"""
    _make_real_repo(cfg.paper_repo_path)
    (cfg.paper_repo_path / "docs" / "broken.md").write_text("# B\n![x](no.webp)\n", encoding="utf-8")
    # 直接 patch MkDocsService.build_strict（sync_blog 在函数内 import 该类）
    from paperflow.publisher.mkdocs_service import BuildCheckResult, MkDocsService
    monkeypatch.setattr(
        MkDocsService, "build_strict",
        lambda self: BuildCheckResult(
            ok=False, duration_ms=1, error_count=1, warning_count=0,
            issues=[{"level": "ERROR", "file": "broken.md", "message": "broken link"}], raw_output=""
        ),
    )
    cfg.publish.require_mkdocs_strict_build = True
    cfg.publish.auto_git_commit = True
    from paperflow.publisher import sync_blog
    result = sync_blog.publish(cfg, repo, push=False, dry_run=False)
    assert result["git"]["blocked_by_build"] is True
    assert result["git"]["committed"] is False


# ---------------- 2. Prompt 自动路由 ----------------

def test_prompt_routing_topics(cfg, repo):
    pm = PromptManager()
    pm.ensure_builtin_templates()
    _make_paper(repo, "p1", tier="S", topics=["HSI-MSI 图像融合"], title="HSI fusion")
    _make_paper(repo, "p2", tier="S", topics=["Agent"], title="Agent paper")
    _make_paper(repo, "p3", tier="S", title="generic")
    _make_paper(repo, "p4", tier="A", title="generic a")

    # S 级统一使用用户指定的深度分析模板（含 PDF 路径），不再被方向模板覆盖
    assert pm.select_template(repo.get_paper("p1"))[0] == "tier_s_default"
    assert pm.select_template(repo.get_paper("p2"))[0] == "tier_s_default"
    assert pm.select_template(repo.get_paper("p3"))[0] == "tier_s_default"
    assert pm.select_template(repo.get_paper("p4"))[0] == "tier_a_default"


# ---------------- 3. LaTeX / JSON 花括号渲染安全 ----------------

def test_render_latex_json_safe():
    template = "# {{title}}\n{{content}}\n{{bibtex}}"
    ctx = {
        "title": "Fusion",
        "content": r"\mathcal{L}_{fusion} = \frac{1}{N}\sum_{i=1}^N \|x_i-y_i\|^2 and metrics = " + '{"psnr": 42.1}',
        "bibtex": "@article{x}",
    }
    out = render_prompt(template, ctx)
    assert "Fusion" in out
    assert r"\frac{1}{N}" in out
    assert '{"psnr": 42.1}' in out  # JSON 花括号原样保留
    # 未定义的 {{unknown}} 保留原样，不抛异常
    assert render_prompt("{{unknown_var}}", ctx) == "{{unknown_var}}"


# ---------------- 4. 模板备份与恢复 ----------------

def test_template_backup_and_reset(tmp_path, monkeypatch):
    # 用临时 prompts 目录隔离（避免污染真实 config/prompts 与 backups）
    tmp_prompts = tmp_path / "prompts"
    pm = PromptManager(tmp_prompts)
    pm.backups_dir = tmp_path / "backups"  # 隔离备份目录
    pm.ensure_builtin_templates()

    t = pm.get_template("topic_agent")
    original = t["body"]
    modified = original + "\n# 自定义修改\n"
    result = pm.save_template("topic_agent", modified)
    assert result["ok"] is True
    # 备份生成
    backups = list(pm.backups_dir.glob("topic_agent_*.md"))
    assert len(backups) == 1
    assert "自定义修改" not in backups[0].read_text(encoding="utf-8")

    # 恢复默认
    pm.reset_to_default("topic_agent")
    assert pm.get_template("topic_agent")["body"] == original

    # 删除内置 -> 返回失败
    assert pm.delete_template("topic_agent")["ok"] is False


# ---------------- 5. Web API ----------------

@pytest.fixture
def web_ctx(cfg, repo, tmp_path, monkeypatch):
    pm = PromptManager(tmp_path / "prompts")
    pm.backups_dir = cfg.workspace_path / "backups" / "prompts"
    pm.ensure_builtin_templates()
    monkeypatch.setattr("paperflow.web.routes.prompts._pm", lambda: pm)
    app = create_app(cfg, repo)
    return {"client": TestClient(app), "cfg": cfg, "repo": repo}


def test_web_prompts_and_build_check(web_ctx):
    c = web_ctx["client"]
    # prompts list / get
    r = c.get("/api/prompts")
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 5
    r = c.get("/api/prompts/topic_agent")
    assert r.status_code == 200
    assert "body" in r.json()

    # 试渲染
    _make_paper(web_ctx["repo"], "arxiv_2603.00001", tier="S", topics=["Agent"], title="Agent Fusion")
    r = c.post("/api/prompts/topic_agent/preview", json={"paper_uid": "arxiv_2603.00001"})
    assert r.status_code == 200
    data = r.json()
    assert "Agent Fusion" in data["prompt"]
    assert data["chars"] > 0

    # 修改 + 恢复
    r = c.put("/api/prompts/topic_agent", json={"body": "# 测试修改\n"})
    assert r.status_code == 200
    r = c.post("/api/prompts/topic_agent/reset")
    assert r.status_code == 200

    # build-check（用真实 repo）
    _make_real_repo(web_ctx["cfg"].paper_repo_path)
    r = c.post("/api/blog/build-check")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # preview status
    r = c.get("/api/blog/preview/status")
    assert r.status_code == 200
    assert "running" in r.json()
