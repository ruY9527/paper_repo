"""首页 Venue 年份统计表验收：数字对得上、三年分列、数字可点击。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.publisher.aggregator import build_index, build_venue_tables


def _paper(uid, venue, year, status=PaperStatus.PUBLISHED.value):
    return PaperRecord(paper_uid=uid, title=uid, normalized_title=uid,
        authors_json="[]", venue=venue, pub_year=year,
        pub_date=f"{year}-05-01", fetch_date=f"{year}-05-01",
        source="arxiv", tier="S", status=status,
        md_blog_path=f"papers/{year}/{venue}/{uid}.md")


def test_venue_table_three_years_and_links(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    for uid, venue, year in [("p1","CVPR",2026),("p2","CVPR",2026),
                             ("p3","CVPR",2025),("p4","TPAMI",2024),
                             ("p5","ARXIV",2026)]:
        repo.upsert_paper(_paper(uid, venue, year))
    out = build_index(cfg, repo)
    assert "今年 2026" in out and "去年 2025" in out and "往期" in out
    # CVPR: 2026=2, 2025=1, 往期=0, 合计=3 → 数字可点
    cvpr = [l for l in out.splitlines() if l.startswith("| CVPR |")][0]
    assert "[2](venues/CVPR-2026.md)" in cvpr
    assert "[1](venues/CVPR-2025.md)" not in cvpr  # 2025页不存在→纯数字
    assert "| 1 | 0 |" in cvpr
    # 其它来源 ARXIV 纳入统计且合计对得上
    arxiv = [l for l in out.splitlines() if "ARXIV（其它来源）" in l][0]
    assert "[1](venues/ARXIV-2026.md)" in arxiv
    # 全部论文数 = 5，表格合计应覆盖
    assert "已收录论文：**5**" in out


def test_venue_tables_include_other_sources(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(_paper("p5","ARXIV",2026))
    tables = build_venue_tables(cfg, repo)
    assert "ARXIV" in tables
    assert "p5" in tables["ARXIV"]
