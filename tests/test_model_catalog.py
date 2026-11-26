"""Phase 14 验收：本地 DSH 模型目录读取与选择。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from paperflow.analyzers.model_catalog import load_harness_models
from paperflow.analyzers.runner import AnalyzerRunner, create_analyzer
from paperflow.config import load_example_config
from paperflow.db.repository import PaperRepository
from paperflow.web.app import create_app


def test_load_harness_models_from_fixture(tmp_path):
    """从模拟的 cordis.patch.yml 提取两类模型。"""
    patch = [
        {"id": "llm-pi-ai", "config": {"providers": {
            "kimi-code": {"displayName": "Kimi Code", "models": [
                {"id": "k3.1-pro", "name": "K3.1 Pro"}]},
        }}},
        {"id": "dsh-connect-workbuddy", "config": {"regions": {"cn": {"lastCatalog": [
            {"id": "hy4flash", "name": "Hy4 flash"}]}}}},
    ]
    p = tmp_path / "cordis.patch.yml"
    p.write_text(yaml.safe_dump(patch, allow_unicode=True), encoding="utf-8")
    r = load_harness_models(p)
    assert r["ok"] is True
    ids = {(m["provider"], m["id"]) for m in r["models"]}
    assert ("kimi-code", "k3.1-pro") in ids
    assert ("workbuddy", "hy4flash") in ids
    assert len(r["models"]) == 2


def test_load_harness_models_missing_file(tmp_path):
    r = load_harness_models(tmp_path / "none.yml")
    assert r["ok"] is False and r["models"] == []


def test_model_override_on_analyzer(tmp_path, monkeypatch):
    """model 参数覆盖配置且不污染原 config。"""
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    a = create_analyzer("claude_cli", cfg, repo, model="k3.1-pro")
    assert a.cfg.model == "k3.1-pro"
    assert cfg.analyzer.claude_cli.model == ""  # 原配置未变


def test_models_api(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    c = TestClient(create_app(cfg, repo))
    r = c.get("/api/analyzer/models")
    assert r.status_code == 200
    assert "models" in r.json()
