"""Phase 6 验收：知识矩阵聚合（首页/Venue 总表/SOTA/开源库/周报）。"""

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord
from paperflow.db.repository import PaperRepository
from paperflow.publisher.aggregator import (
    build_index,
    build_open_source,
    build_sota_matrix,
    build_venue_tables,
    build_weeklies,
    rebuild_all,
)


def _setup(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    cfg.project.paper_repo_dir = str(tmp_path / "paper_repo")
    repo = PaperRepository(tmp_path / "state.db")
    p = PaperRecord(
        paper_uid="arxiv_2603.12345", title="Video Action Recognition with ViT",
        normalized_title="video action recognition with vit",
        authors_json='["Alice"]', venue="CVPR", pub_year=2026,
        pub_date="2026-03-16", fetch_date="2026-03-16", source="arxiv",
        tier="S", abstract="We propose a novel video understanding approach.",
        code_url="https://github.com/foo/bar", code_stars=42,
        matched_tags_json='["action recognition", "multimodal"]',
    )
    repo.upsert_paper(p)
    repo.upsert_metrics("arxiv_2603.12345", {
        "task": "Video Action Recognition", "backbone": "ViT-L",
        "datasets": ["Kinetics-400"], "sota_summary": "mAP 75.0%",
        "innovation_tags": ["Zero-Shot"],
    })
    return cfg, repo


def test_build_index(tmp_path):
    cfg, repo = _setup(tmp_path)
    # 未发布时：论文不应出现在「最近发布」表（避免 strict build 断链）
    idx = build_index(cfg, repo)
    assert "已收录论文：**1**" in idx
    assert "S 级精读：**1**" in idx
    assert "CVPR" in idx
    assert "暂无已发布论文" in idx
    # 标记为已发布后：才出现在首页并带正确链接
    repo.update_status("arxiv_2603.12345", "PUBLISHED",
                       md_blog_path="papers/2026/CVPR/arxiv_2603.12345.md")
    idx2 = build_index(cfg, repo)
    assert "Video Action Recognition" in idx2
    assert "](papers/2026/CVPR/arxiv_2603.12345.md)" in idx2


def test_venue_tables(tmp_path):
    cfg, repo = _setup(tmp_path)
    tables = build_venue_tables(cfg, repo)
    assert len(tables) == 9  # 9 个 venue 都有总表
    assert "Video Action Recognition" in tables["CVPR"]
    assert "收录 **1** 篇" in tables["CVPR"]


def test_sota_and_open_source(tmp_path):
    cfg, repo = _setup(tmp_path)
    sota = build_sota_matrix(cfg, repo)
    assert "Video Action Recognition" in sota
    assert "ViT-L" in sota
    assert "mAP 75.0%" in sota
    oss = build_open_source(cfg, repo)
    assert "github.com/foo/bar" in oss
    assert "| 42 |" in oss


def test_weeklies(tmp_path):
    cfg, repo = _setup(tmp_path)
    weeks = build_weeklies(cfg, repo)
    assert len(weeks) >= 1
    content = list(weeks.values())[0]
    assert "趋势周报" in content
    assert "action recognition" in content


def test_rebuild_all_writes_files(tmp_path):
    cfg, repo = _setup(tmp_path)
    stats = rebuild_all(cfg, repo)
    assert stats["pages"] >= 9
    docs = cfg.paper_repo_path / "docs"
    assert (docs / "index.md").exists()
    assert (docs / "venues" / "CVPR-2026.md").exists()
    assert (docs / "matrix" / "sota-2026.md").exists()
    assert (docs / "matrix" / "open-source-2026.md").exists()
