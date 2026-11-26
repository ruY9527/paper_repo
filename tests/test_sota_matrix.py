"""SOTA 矩阵可读性重构验收。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.publisher.aggregator import build_sota_matrix


def test_sota_matrix_readable(tmp_path):
    """混合类型 metrics 渲染为可读卡片，无逐字符拆分/裸 JSON。"""
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(PaperRecord(
        paper_uid="arxiv_s1", title="SOTA Paper", normalized_title="sota paper",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-11-22",
        source="arxiv", tier="S", status=PaperStatus.PUBLISHED.value,
        md_blog_path="papers/2026/CVPR/arxiv_s1.md",
    ))
    repo.upsert_metrics("arxiv_s1", {
        "task": "问题A的高效求解",
        "backbone": {"encoder": "ViT-L", "head": "MLP"},
        "datasets": ["ImageNet", "COCO"],
        "sota_summary": "acc 90.1%，比 baseline +3.2pp",
        "innovation_tags": ["tag1", "tag2"],
    })
    out = build_sota_matrix(cfg, repo)
    assert "跨论文能力对照" in out
    assert "怎么读这一页" in out
    assert "研究任务" in out and "核心结论" in out
    assert "**encoder**: ViT-L" in out  # dict 结构化而非裸 JSON
    assert "ImageNet · COCO" in out     # list 正确 join
    assert "b, r, o, w" not in out      # 无逐字符拆分
    # 链接带 ../ 前缀（从 matrix/ 出发）
    assert "../papers/2026/CVPR/arxiv_s1.md" in out


def test_sota_empty(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    out = build_sota_matrix(cfg, repo)
    assert "暂无指标数据" in out
