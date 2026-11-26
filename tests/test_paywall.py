"""Phase 13 验收：受限出版商过滤与手动补传（模块 7）。

基于 10_PAYWALL_FILTER_AND_MANUAL_PDF_HUB.md 第 7 节全部场景，离线可测。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus, PaperTier
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.downloader import download_s_papers
from paperflow.pipeline.manual_pdf import attach_local_pdf, scan_inbox_pdfs
from paperflow.pipeline.paywall_filter import PaywallFilter
from paperflow.web.app import create_app


@pytest.fixture
def cfg(tmp_path):
    c = load_example_config()
    c.project.workspace_dir = str(tmp_path / "workspace")
    c.project.paper_repo_dir = str(tmp_path / "paper_repo")
    c.download_policy.manual_inbox_dir = str(tmp_path / "workspace" / "inbox_pdfs")
    return c


@pytest.fixture
def repo(cfg):
    return PaperRepository(cfg.db_path)


def _ieee_paper(uid="arxiv_ieee_1", arxiv_id=None, pdf_url="https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=12345",
                paper_url="https://ieeexplore.ieee.org/document/12345"):
    return PaperRecord(
        paper_uid=uid, title="IEEE Paywall Test Paper", normalized_title="ieee paywall test paper",
        authors_json='["Alice"]', venue="TPAMI", pub_year=2026,
        pub_date="2026-03-01", fetch_date="2026-03-02", source="openalex",
        tier=PaperTier.S.value, status=PaperStatus.SCORED.value,
        arxiv_id=arxiv_id, pdf_url=pdf_url, paper_url=paper_url,
        doi="10.1109/TPAMI.2026.12345",
    )


def _make_pdf_bytes(title="Test Paper", doi="10.1109/TPAMI.2026.12345") -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), title, fontsize=14)
    page.insert_text((72, 100), f"doi: {doi}", fontsize=11)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------------- 1. 域名过滤拦截 ----------------

def test_paywall_domain_blocks_no_http(cfg, repo, monkeypatch):
    """命中 IEEE 域名 -> 不发起 HTTP 下载，登记 paywall_papers。"""
    monkeypatch.setattr("paperflow.pipeline.paywall_filter.time.sleep", lambda *_: None)
    repo.upsert_paper(_ieee_paper())
    # patch arXiv 抢救返回 None（避免真实网络）
    monkeypatch.setattr(PaywallFilter, "_arxiv_rescue", lambda self, p: None)

    with respx.mock(assert_all_called=False) as router:
        # 关键：若代码误发起下载，这条路由会被调用；拦截成功后它应保持未调用
        ieee_route = router.get("https://ieeexplore.ieee.org/stamp/stamp.jsp").mock(
            return_value=httpx.Response(200, content=b"%PDF")
        )
        stats = download_s_papers(cfg, repo)

    assert stats["paywall_blocked"] == 1
    assert stats["downloaded"] == 0
    # 断言零 HTTP 下载请求
    assert ieee_route.called is False
    p = repo.get_paper("arxiv_ieee_1")
    assert p.access_type == "paywall_blocked"
    assert p.status == PaperStatus.SCORED.value  # 绝不是 FAILED
    pw = repo.get_paywall_paper("arxiv_ieee_1")
    assert pw["publisher"] == "IEEE Xplore"
    assert pw["manual_status"] == "PENDING_MANUAL"
    assert pw["block_reason"] == "domain_blacklist"


# ---------------- 2. arXiv 抢救 ----------------

def test_arxiv_rescue_fills_arxiv_id(cfg, repo, monkeypatch):
    monkeypatch.setattr("paperflow.pipeline.paywall_filter.time.sleep", lambda *_: None)
    paper = _ieee_paper()
    repo.upsert_paper(paper)
    monkeypatch.setattr(
        PaywallFilter, "_arxiv_rescue",
        lambda self, p: ("2603.12345", "https://arxiv.org/pdf/2603.12345.pdf"),
    )
    # 抢救后 pdf_url 变成 arxiv.org，放行下载需 mock
    with respx.mock(assert_all_called=False) as router:
        router.get("https://arxiv.org/pdf/2603.12345.pdf").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.4 test")
        )
        stats = download_s_papers(cfg, repo)

    assert stats["downloaded"] == 1
    p = repo.get_paper("arxiv_ieee_1")
    assert p.arxiv_id == "2603.12345"
    assert p.access_type == "open"  # 未登记 paywall
    assert repo.get_paywall_paper("arxiv_ieee_1") is None


# ---------------- 3. 动态 403/HTML 登录墙兜底 ----------------

def test_unknown_domain_403_classified_as_paywall(cfg, repo):
    """未知域名返回 403 -> 自动归入 paywall。"""
    paper = PaperRecord(
        paper_uid="arxiv_unknown_1", title="Unknown Domain Paper",
        normalized_title="unknown domain paper", authors_json="[]",
        venue="IJCV", pub_year=2026, fetch_date="2026-03-02", source="openalex",
        tier="S", status="SCORED", pdf_url="https://unknown-publisher.com/paper.pdf",
        paper_url="https://unknown-publisher.com/paper",
    )
    repo.upsert_paper(paper)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://unknown-publisher.com/paper.pdf").mock(
            return_value=httpx.Response(403, text="forbidden")
        )
        stats = download_s_papers(cfg, repo)

    assert stats["paywall_blocked"] == 1
    p = repo.get_paper("arxiv_unknown_1")
    assert p.access_type == "paywall_blocked"
    assert p.status != "FAILED"
    pw = repo.get_paywall_paper("arxiv_unknown_1")
    assert pw["block_reason"] == "http_403_login_wall"


def test_unknown_domain_html_login_wall(cfg, repo):
    paper = PaperRecord(
        paper_uid="arxiv_unknown_2", title="HTML Login Wall", normalized_title="html login wall",
        authors_json="[]", venue="TIP", pub_year=2026, fetch_date="2026-03-02",
        source="openalex", tier="S", status="SCORED",
        pdf_url="https://publisher-x.com/dl.pdf", paper_url="https://publisher-x.com/dl",
    )
    repo.upsert_paper(paper)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://publisher-x.com/dl.pdf").mock(
            return_value=httpx.Response(200, headers={"Content-Type": "text/html"},
                                        content=b"<html>login required</html>")
        )
        stats = download_s_papers(cfg, repo)
    assert stats["paywall_blocked"] == 1
    assert repo.get_paywall_paper("arxiv_unknown_2")["block_reason"] == "http_403_login_wall"


# ---------------- 4. 手动补传 + 收件箱 ----------------

def test_attach_local_pdf(cfg, repo):
    repo.upsert_paper(_ieee_paper("arxiv_up_1"))
    repo.add_paywall_paper(paper_uid="arxiv_up_1", title="IEEE Paywall Test Paper",
                           venue="TPAMI", pub_year=2026, publisher="IEEE Xplore",
                           domain="ieeexplore.ieee.org", block_reason="domain_blacklist")
    result = attach_local_pdf(cfg, repo, "arxiv_up_1", _make_pdf_bytes())
    assert result["ok"] is True
    assert result["status"] == "QUEUED"
    p = repo.get_paper("arxiv_up_1")
    assert p.status == PaperStatus.QUEUED.value
    assert p.access_type == "manual_uploaded"
    assert repo.get_paywall_paper("arxiv_up_1")["manual_status"] == "PDF_UPLOADED"


def test_attach_rejects_non_pdf(cfg, repo):
    repo.upsert_paper(_ieee_paper("arxiv_up_2"))
    with pytest.raises(ValueError, match="非 %PDF|文件头"):
        attach_local_pdf(cfg, repo, "arxiv_up_2", b"<html>not a pdf</html>")


def test_scan_inbox_auto_match(cfg, repo):
    # 登记一篇 pending 论文（文件名含 UID）
    repo.upsert_paper(_ieee_paper("doi_abc123"))
    repo.add_paywall_paper(paper_uid="doi_abc123", title="IEEE Paywall Test Paper",
                           venue="TPAMI", pub_year=2026, publisher="IEEE Xplore",
                           domain="ieeexplore.ieee.org", block_reason="domain_blacklist")
    inbox = cfg.inbox_pdfs_path
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "doi_abc123.pdf").write_bytes(_make_pdf_bytes())

    result = scan_inbox_pdfs(cfg, repo)
    assert result["matched"] == 1
    assert repo.get_paywall_paper("doi_abc123")["manual_status"] == "PDF_UPLOADED"


# ---------------- 5. Web API ----------------

@pytest.fixture
def web_ctx(cfg, repo, monkeypatch):
    import paperflow.web.routes.paywall as paywall_mod
    # 隔离 config 路径：用 example 内容创建临时 config，避免 domains PUT 污染真实配置
    from paperflow.config import PROJECT_ROOT
    tmp_cfg = __import__("pathlib").Path(cfg.project.workspace_dir) / "_paywall_config.yaml"
    tmp_cfg.write_text(
        (PROJECT_ROOT / "config" / "config.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(paywall_mod, "CONFIG_PATH", tmp_cfg)
    return {"client": TestClient(create_app(cfg, repo)), "cfg": cfg, "repo": repo}


def test_web_paywall_apis(web_ctx):
    c = web_ctx["client"]
    # papers / domains / export
    assert c.get("/api/paywall/papers").status_code == 200
    assert c.get("/api/paywall/domains").status_code == 200
    assert c.get("/api/paywall/export?format=csv").status_code == 200
    assert c.get("/api/paywall/export?format=md").status_code == 200

    # 登记 + fallback-abstract
    repo = web_ctx["repo"]
    repo.upsert_paper(_ieee_paper("arxiv_web_1"))
    repo.add_paywall_paper(paper_uid="arxiv_web_1", title="IEEE Paywall Test Paper",
                           venue="TPAMI", pub_year=2026, publisher="IEEE Xplore",
                           domain="ieeexplore.ieee.org", block_reason="domain_blacklist")
    r = c.post("/api/paywall/papers/arxiv_web_1/fallback-abstract")
    assert r.status_code == 200
    assert repo.get_paywall_paper("arxiv_web_1")["manual_status"] == "ABSTRACT_ONLY"

    # upload-pdf（合法）
    r = c.post("/api/paywall/papers/arxiv_web_1/upload-pdf",
               files={"file": ("p.pdf", _make_pdf_bytes(), "application/pdf")})
    assert r.status_code == 200

    # upload-pdf（非法）
    r = c.post("/api/paywall/papers/arxiv_web_1/upload-pdf",
               files={"file": ("bad.txt", b"<html></html>", "text/html")})
    assert r.status_code == 400

    # domains PUT（web_ctx 已隔离 CONFIG_PATH）
    r = c.put("/api/paywall/domains", json={"domains": [
        {"domain": "ieeexplore.ieee.org", "publisher": "IEEE Xplore", "note": ""},
        {"domain": "link.springer.com", "publisher": "Springer", "note": ""},
    ]})
    assert r.status_code == 200
    assert r.json()["count"] == 2
