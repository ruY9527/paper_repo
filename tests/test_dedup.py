"""Phase 2 验收：去重优先级与标题标准化。"""

from paperflow.pipeline.dedup import (
    generate_paper_uid,
    normalize_title,
    strip_arxiv_version,
)


def test_uid_priority_doi_over_all():
    uid = generate_paper_uid(
        doi="10.1109/CVPR.2026.123", arxiv_id="2603.1", openreview_id="abc", title="X"
    )
    assert uid.startswith("doi_")


def test_uid_priority_arxiv_over_openreview_and_title():
    uid = generate_paper_uid(arxiv_id="2603.12345v2", openreview_id="abc", title="X")
    assert uid == "arxiv_2603.12345"


def test_uid_arxiv_slash_replaced():
    uid = generate_paper_uid(arxiv_id="cs/0601001v3")
    assert uid == "arxiv_cs_0601001"


def test_uid_openreview():
    assert generate_paper_uid(openreview_id="abcDEF123") == "or_abcDEF123"


def test_uid_title_hash_fallback():
    uid1 = generate_paper_uid(title="A Great, {Vision} Paper!")
    uid2 = generate_paper_uid(title="a great vision paper")
    assert uid1 == uid2
    assert uid1.startswith("title_")


def test_normalize_title():
    assert normalize_title("{Attention} Is All You --- Need!") == "attention is all you need"
    assert normalize_title("") == ""


def test_strip_version():
    assert strip_arxiv_version("2603.12345") == "2603.12345"
    assert strip_arxiv_version("2603.12345v10") == "2603.12345"
