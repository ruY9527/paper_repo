"""存储治理明细列表验收：卡片数字可点击查看文件清单。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.repository import PaperRepository
from paperflow.web.app import create_app
from fastapi.testclient import TestClient


def test_storage_files_detail(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    # 造两个临时 PDF
    pdf_dir = cfg.workspace_path / "tmp" / "pdfs"; pdf_dir.mkdir(parents=True)
    for uid in ("p1", "p2"):
        (pdf_dir / f"{uid}.pdf").write_bytes(b"%PDF" + b"x" * 100)
    # 造一个队列目录
    qdir = cfg.workspace_path / "queue" / "2026-11-23" / "p1"; qdir.mkdir(parents=True)
    (qdir / "prompt.md").write_text("x" * 50, encoding="utf-8")
    c = TestClient(create_app(cfg, repo))

    pdfs = c.get("/api/storage/files?kind=pdfs").json()
    assert pdfs["total"] == 2
    assert {i["uid"] for i in pdfs["items"]} == {"p1", "p2"}
    assert all(i["size_mb"] >= 0 for i in pdfs["items"])

    queue = c.get("/api/storage/files?kind=queue").json()
    assert queue["total"] == 1
    assert queue["items"][0]["name"] == "2026-11-23"


def test_storage_files_clean_empty(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    c = TestClient(create_app(cfg, PaperRepository(cfg.db_path)))
    d = c.get("/api/storage/files?kind=cleanup").json()
    assert d["kind"] == "cleanup" and d["total"] == 0
