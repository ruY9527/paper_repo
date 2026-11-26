"""年度总览统计准确性验收。"""

from __future__ import annotations

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.md_validator import validate_md_file
from paperflow.publisher.aggregator import build_index


def test_index_overview_counts_match_db(tmp_path):
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    for uid, tier, code in [("p1","S","https://github.com/a/b"),
                            ("p2","S",""), ("p3","A","https://github.com/c/d"), ("p4","B","")]:
        repo.upsert_paper(PaperRecord(paper_uid=uid, title=uid, normalized_title=uid,
            authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-05-01",
            source="arxiv", tier=tier, status=PaperStatus.PUBLISHED.value, code_url=code))
    out = build_index(cfg, repo)
    assert "已收录论文：**4**" in out
    assert "S 级精读：**2**" in out
    assert "A 级速览：**1**" in out
    assert "带开源代码：**2**" in out


def test_validator_backfills_code_url(tmp_path):
    """校验通过时把 frontmatter 的有效 code_url 回写 DB；否定文案跳过。"""
    cfg = load_example_config(); cfg.project.workspace_dir = str(tmp_path / "ws")
    repo = PaperRepository(cfg.db_path)
    repo.upsert_paper(PaperRecord(paper_uid="p1", title="P", normalized_title="p",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-05-01",
        source="arxiv", tier="S", status=PaperStatus.STAGED.value))
    md = tmp_path / "p1.md"
    md.write_text('---\npaper_uid: "p1"\ntitle: "P"\nvenue: CVPR\nyear: 2026\ntier: S\ntldr: t\n'
                  'code_url: "https://github.com/real/repo"\n---\n' + "# Body\n" + "x"*400,
                  encoding="utf-8")
    validate_md_file(md, repo, cfg, persist=True)
    assert repo.get_paper("p1").code_url == "https://github.com/real/repo"

    # 否定文案不回写
    repo.upsert_paper(PaperRecord(paper_uid="p2", title="P2", normalized_title="p2",
        authors_json="[]", venue="CVPR", pub_year=2026, fetch_date="2026-05-01",
        source="arxiv", tier="S", status=PaperStatus.STAGED.value))
    md2 = tmp_path / "p2.md"
    md2.write_text('---\npaper_uid: "p2"\ntitle: "P2"\nvenue: CVPR\nyear: 2026\ntier: S\ntldr: t\n'
                   'code_url: "https://arxiv.org/abs/xxx （未列出代码链接）"\n---\n' + "# Body\n" + "x"*400,
                   encoding="utf-8")
    validate_md_file(md2, repo, cfg, persist=True)
    assert not repo.get_paper("p2").code_url
