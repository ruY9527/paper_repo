"""Phase 1 验收：SQLite 账本幂等建表、合并去重、状态流转、水位线（01 文档第 5 节 2/3/4 项）。"""

import json

from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.dedup import (
    generate_paper_uid,
    normalize_title,
    strip_arxiv_version,
)


def _make_arxiv_paper() -> PaperRecord:
    return PaperRecord(
        paper_uid=generate_paper_uid(arxiv_id="2603.12345", title="A Great Vision Paper"),
        title="A Great Vision Paper",
        normalized_title=normalize_title("A Great Vision Paper"),
        authors_json=json.dumps(["Alice", "Bob"]),
        venue="CVPR",
        pub_year=2026,
        pub_date="2026-03-15",
        fetch_date="2026-03-16",
        source="arxiv",
        arxiv_id="2603.12345",
        abstract="An early preprint abstract.",
        paper_url="https://arxiv.org/abs/2603.12345",
        pdf_url="https://arxiv.org/pdf/2603.12345.pdf",
    )


def test_repository_init_idempotent(tmp_path):
    """重复初始化建表不报错。"""
    db = tmp_path / "state.db"
    repo1 = PaperRepository(db)
    repo1.start_run("fetch")
    repo2 = PaperRepository(db)  # 再次初始化
    assert repo2.count_papers() == 0
    # 表仍可正常使用
    repo2.set_watermark("arxiv", "ALL", "2026-03-20")
    assert repo1.get_watermark("arxiv", "ALL").last_success_date == "2026-03-20"


def test_upsert_merge_arxiv_then_openalex(tmp_path):
    """先 arxiv 无 DOI 入库，再 openalex 带 DOI 同标题入库，应合并为一条且不重置状态。"""
    repo = PaperRepository(tmp_path / "state.db")

    arxiv_paper = _make_arxiv_paper()
    saved1, is_new1 = repo.upsert_paper(arxiv_paper)
    assert is_new1 is True
    assert saved1.paper_uid == "arxiv_2603.12345"

    # 模拟已进入 QUEUED 状态并下载了 PDF
    repo.update_status(
        saved1.paper_uid,
        PaperStatus.QUEUED,
        pdf_local_path="workspace/tmp/pdfs/arxiv_2603.12345.pdf",
    )

    # OpenAlex 补齐 DOI 与正式期刊信息，标题相同
    openalex_paper = PaperRecord(
        paper_uid=generate_paper_uid(doi="10.1109/TPAMI.2026.9999999", title="A Great Vision Paper"),
        title="A Great Vision Paper",
        normalized_title=normalize_title("A Great Vision Paper"),
        authors_json=json.dumps(["Alice", "Bob"]),
        venue="TPAMI",
        pub_year=2026,
        pub_date="2026-06-01",
        fetch_date="2026-06-02",
        source="openalex",
        doi="10.1109/TPAMI.2026.9999999",
        arxiv_id="2603.12345",
        abstract="An early preprint abstract. A richer published abstract with more details.",
        paper_url="https://doi.org/10.1109/TPAMI.2026.9999999",
    )
    saved2, is_new2 = repo.upsert_paper(openalex_paper)
    assert is_new2 is False
    assert saved2.paper_uid == "arxiv_2603.12345"  # 保留原 UID
    assert saved2.doi == "10.1109/TPAMI.2026.9999999"  # DOI 被补全
    assert saved2.status == PaperStatus.QUEUED.value  # 状态未被重置
    assert saved2.pdf_local_path == "workspace/tmp/pdfs/arxiv_2603.12345.pdf"

    # 仍只有一条记录
    assert repo.count_papers() == 1


def test_upsert_does_not_overwrite_existing_fields(tmp_path):
    """已存在的非空字段不被空值覆盖。"""
    repo = PaperRepository(tmp_path / "state.db")
    p = _make_arxiv_paper()
    repo.upsert_paper(p)

    # 第二次入库，abstract 为空，不应清空已有摘要
    p2 = PaperRecord(
        paper_uid=p.paper_uid,
        title=p.title,
        normalized_title=p.normalized_title,
        authors_json=p.authors_json,
        venue=p.venue,
        pub_year=p.pub_year,
        fetch_date=p.fetch_date,
        source="openalex",
        arxiv_id=p.arxiv_id,
        abstract="",
    )
    saved, is_new = repo.upsert_paper(p2)
    assert is_new is False
    assert saved.abstract == "An early preprint abstract."


def test_unique_doi_arxiv_indexes(tmp_path):
    """DOI / arXiv 唯一索引防止重复。"""
    repo = PaperRepository(tmp_path / "state.db")
    p = _make_arxiv_paper()
    repo.upsert_paper(p)
    # 同一 arxiv_id 不同标题：通过 arxiv_id 查到已存在，仍合并
    p2 = PaperRecord(
        paper_uid="title_abc",
        title="Completely Different Title",
        normalized_title=normalize_title("Completely Different Title"),
        authors_json="[]",
        venue="ICLR",
        pub_year=2026,
        fetch_date="2026-03-16",
        source="manual",
        arxiv_id="2603.12345",
    )
    saved, is_new = repo.upsert_paper(p2)
    assert is_new is False
    assert saved.paper_uid == p.paper_uid


def test_watermark_read_write(tmp_path):
    repo = PaperRepository(tmp_path / "state.db")
    assert repo.get_watermark("arxiv", "ALL") is None

    repo.set_watermark("arxiv", "ALL", "2026-03-20")
    wm = repo.get_watermark("arxiv", "ALL")
    assert wm is not None
    assert wm.last_success_date == "2026-03-20"
    assert wm.last_status == "SUCCESS"

    # 覆盖写入
    repo.set_watermark("arxiv", "ALL", "2026-03-21", last_status="PARTIAL", last_error="network")
    wm = repo.get_watermark("arxiv", "ALL")
    assert wm.last_success_date == "2026-03-21"
    assert wm.last_status == "PARTIAL"
    assert wm.last_error == "network"
    assert len(repo.get_all_watermarks()) == 1


def test_status_transition_and_timestamp(tmp_path):
    repo = PaperRepository(tmp_path / "state.db")
    p = _make_arxiv_paper()
    saved, _ = repo.upsert_paper(p)
    old_updated = saved.updated_at

    repo.update_status(saved.paper_uid, PaperStatus.SCORED, score=55.0, tier="S")
    updated = repo.get_paper(saved.paper_uid)
    assert updated.status == "SCORED"
    assert updated.score == 55.0
    assert updated.tier == "S"
    assert updated.updated_at >= old_updated

    import pytest
    with pytest.raises(ValueError, match="非法状态"):
        repo.update_status(saved.paper_uid, "BOGUS")


def test_dedup_helpers():
    assert normalize_title("{A} Great, Vision---Paper!") == "a great vision paper"
    assert strip_arxiv_version("2603.12345v2") == "2603.12345"
    assert strip_arxiv_version("cs/0601001v3") == "cs/0601001"
    assert generate_paper_uid(doi="10.1/X", title="ignored").startswith("doi_")
    assert generate_paper_uid(arxiv_id="2603.1v1", title="ignored") == "arxiv_2603.1"
    assert generate_paper_uid(title="Alpha Beta") == generate_paper_uid(title="alpha  beta")
