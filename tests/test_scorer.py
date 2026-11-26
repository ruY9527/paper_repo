"""Phase 3 验收：关键词打分、排除词、radar、GitHub 提取、S/A/B 边界。"""

import json

from paperflow.config import AppConfig, load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.dedup import generate_paper_uid, normalize_title
from paperflow.pipeline.scorer import (
    score_and_persist,
    score_paper,
    sniff_code_links,
)


def _paper(title="A Paper", abstract="", comment="", authors=None, affils=None) -> PaperRecord:
    return PaperRecord(
        paper_uid=generate_paper_uid(title=title),
        title=title,
        normalized_title=normalize_title(title),
        authors_json=json.dumps(authors or []),
        affiliations_json=json.dumps(affils or []),
        venue="CVPR", pub_year=2026, fetch_date="2026-03-16", source="arxiv",
        abstract=abstract, comment=comment,
    )


def test_high_keywords_accumulate_with_cap():
    cfg = load_example_config()
    # 两个高优先级词 -> 60（上限）
    p = _paper(abstract="We study action recognition and video understanding.")
    r = score_paper(p, cfg)
    assert r.score == 60
    assert r.tier == "S"
    # 单个高优先级词 -> 30
    p2 = _paper(abstract="A multimodal approach.")
    assert score_paper(p2, cfg).score == 30


def test_medium_keywords_cap():
    cfg = load_example_config()
    p = _paper(abstract="diffusion and 3d gaussian and world model")
    r = score_paper(p, cfg)
    # 3 个中优先级词 -> min(45,30)=30
    assert r.score == 30
    assert r.tier == "A"


def test_exclude_keywords_and_floor():
    cfg = load_example_config()
    # 1 个高优先级 + 1 个排除词 -> 30 - 50 = -20 -> 截断 0
    p = _paper(abstract="video understanding for retinal analysis")
    r = score_paper(p, cfg)
    assert r.score == 0
    assert r.tier == "B"
    assert any("retinal" in t for t in r.matched_tags)


def test_radar_author_and_affiliation():
    cfg = load_example_config()
    p = _paper(authors=["Kaiming He"], affils=["Google DeepMind"])
    r = score_paper(p, cfg)
    assert r.is_radar_hit == 1
    assert r.score == 25 + 15  # 40
    assert r.tier == "A"


def test_oral_bonus_radar():
    cfg = load_example_config()
    p = _paper(abstract="video understanding", comment="CVPR 2026 Oral")
    r = score_paper(p, cfg)
    # 单个高优先级词 video understanding = 30，oral = 20，合计 50
    assert r.score == 50
    assert r.tier == "S"
    assert r.is_radar_hit == 1


def test_github_sniff():
    text = "Code available at https://github.com/foo/bar, project https://foo.github.io/demo"
    code, project = sniff_code_links(text)
    assert code == "https://github.com/foo/bar"
    assert project == "https://foo.github.io/demo"

    cfg = load_example_config()
    p = _paper(abstract="Code: https://github.com/foo/bar")
    r = score_paper(p, cfg)
    assert r.code_url == "https://github.com/foo/bar"
    assert r.score >= 15


def test_tier_boundaries():
    cfg = load_example_config()
    # 恰好 S: 30(high)+20(oral) = 50
    assert score_paper(_paper(abstract="multimodal", comment="Oral"), cfg).tier == "S"
    # 恰好 A: 30 (single high) -> A (25<=30<50)
    assert score_paper(_paper(abstract="multimodal"), cfg).tier == "A"
    # 恰好 <25: 15 (single medium) -> B
    assert score_paper(_paper(abstract="diffusion"), cfg).tier == "B"


def test_force_tier_s_for_manual_add():
    cfg = load_example_config()
    p = _paper(abstract="nothing relevant")
    assert score_paper(p, cfg).tier == "B"
    assert score_paper(p, cfg, force_tier_s=True).tier == "S"


def test_score_and_persist_b_becomes_skipped(tmp_path):
    cfg = load_example_config()
    repo = PaperRepository(tmp_path / "state.db")
    p = _paper(abstract="nothing relevant")
    repo.upsert_paper(p)
    r = score_and_persist(p, cfg, repo)
    assert r.tier == "B"
    updated = repo.get_paper(p.paper_uid)
    assert updated.status == PaperStatus.SKIPPED.value
    assert updated.score == 0
