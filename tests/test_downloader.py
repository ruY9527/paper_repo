"""Phase 4 验收：PDF 原子下载、文件头校验、失败降级为 A 级。"""

import httpx
import respx

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus, PaperTier
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.downloader import download_s_papers


def _s_paper(uid="arxiv_2603.12345", url="https://arxiv.org/pdf/x.pdf") -> PaperRecord:
    return PaperRecord(
        paper_uid=uid, title="S Tier Paper", normalized_title="s tier paper",
        authors_json="[]", venue="CVPR", pub_year=2026,
        fetch_date="2026-03-16", source="arxiv",
        tier=PaperTier.S.value, status=PaperStatus.SCORED.value, pdf_url=url,
    )


def test_download_valid_pdf(tmp_path):
    cfg = load_example_config()
    # 覆盖 workspace_dir 到 tmp
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    repo = PaperRepository(tmp_path / "state.db")
    paper = _s_paper()
    repo.upsert_paper(paper)

    pdf_bytes = b"%PDF-1.4\n" + b"x" * 100
    with respx.mock(assert_all_called=False) as router:
        router.get("https://arxiv.org/pdf/x.pdf").mock(
            return_value=httpx.Response(200, content=pdf_bytes)
        )
        client = httpx.Client(trust_env=False)
        stats = download_s_papers(cfg, repo, client=client)
    assert stats["downloaded"] == 1
    updated = repo.get_paper(paper.paper_uid)
    assert updated.status == PaperStatus.DOWNLOADED.value
    saved = cfg.workspace_path / "tmp" / "pdfs" / f"{paper.paper_uid}.pdf"
    assert saved.exists()
    assert saved.read_bytes()[:4] == b"%PDF"
    # 无残留 .part
    assert not list(saved.parent.glob("*.part"))


def test_download_html_fallback_to_a(tmp_path):
    """下载到的不是 PDF（HTML 页面）时降级为 A 级。"""
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    repo = PaperRepository(tmp_path / "state.db")
    paper = _s_paper()
    repo.upsert_paper(paper)

    with respx.mock(assert_all_called=False) as router:
        router.get("https://arxiv.org/pdf/x.pdf").mock(
            return_value=httpx.Response(200, content=b"<html>login page</html>")
        )
        client = httpx.Client(trust_env=False)
        stats = download_s_papers(cfg, repo, client=client)
    assert stats["fallback"] == 1
    updated = repo.get_paper(paper.paper_uid)
    assert updated.tier == PaperTier.A.value
    assert updated.status == PaperStatus.SCORED.value  # 仍可进入队列
    assert not (cfg.workspace_path / "tmp" / "pdfs" / f"{paper.paper_uid}.pdf").exists()
