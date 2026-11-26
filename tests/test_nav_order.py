"""mkdocs nav 顺序验收：首页 → 顶会总表 → 知识矩阵 → 网站导航。"""

from __future__ import annotations

import shutil
from pathlib import Path

from paperflow.config import load_example_config
from paperflow.db.repository import PaperRepository
from paperflow.sites.blog_renderer import update_mkdocs_nav
from paperflow.web.app import create_app
from fastapi.testclient import TestClient


def test_nav_order(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    mkdocs = Path(__file__).resolve().parents[1] / "paper_repo" / "mkdocs.yml"
    target = repo_dir / "mkdocs.yml"
    # 模拟缺网站导航的旧配置
    text = mkdocs.read_text(encoding="utf-8").replace("  - 网站导航: sites/index.md\n", "")
    target.write_text(text, encoding="utf-8")
    update_mkdocs_nav(target)

    lines = target.read_text(encoding="utf-8").splitlines()
    top = [l.split(":", 1)[0].strip().lstrip("- ").strip()
           for l in lines if l.startswith("  - ") and not l.startswith("    ")]
    assert top.index("首页") < top.index("顶会总表") < top.index("知识矩阵") < top.index("网站导航")
    # 幂等
    before = target.read_text(encoding="utf-8")
    assert update_mkdocs_nav(target) is False
    assert target.read_text(encoding="utf-8") == before
