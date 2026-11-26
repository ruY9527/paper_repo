"""Phase 6 验收：博客同步（dry-run 不写盘、正常模式复制 MD/图片并更新状态）。"""

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus
from paperflow.db.repository import PaperRepository
from paperflow.publisher.sync_blog import publish
from paperflow.utils.figure_links import normalize_blog_image_paths

VALID_MD = (
    "---\npaper_uid: \"arxiv_2603.12345\"\ntitle: \"Test Paper\"\n"
    "venue: \"CVPR\"\nyear: 2026\ntier: \"S\"\ntldr: \"一句话总结。\"\n---\n\n"
    + "正文内容。" * 100 + "\n"
    "![架构图](../../assets/arxiv_2603.12345/fig_1.webp)\n"
)


def _setup(tmp_path):
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp_path / "workspace")
    cfg.project.paper_repo_dir = str(tmp_path / "paper_repo")
    cfg.publish.auto_git_commit = False  # 测试中关闭 git
    repo = PaperRepository(tmp_path / "state.db")
    p = PaperRecord(
        paper_uid="arxiv_2603.12345", title="Test Paper",
        normalized_title="test paper", authors_json="[]",
        venue="CVPR", pub_year=2026, fetch_date="2026-03-16", source="arxiv",
        tier="S", status=PaperStatus.QUEUED.value,
    )
    repo.upsert_paper(p)
    staging = cfg.workspace_path / "staging" / "2026-03-16"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "arxiv_2603.12345.md").write_text(VALID_MD, encoding="utf-8")
    # 模拟架构图
    assets = cfg.workspace_path / "staging" / "assets" / "arxiv_2603.12345"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "fig_1.webp").write_bytes(b"fake webp")
    return cfg, repo


def test_fix_image_paths():
    assert normalize_blog_image_paths("![x](../../assets/uid/fig_1.webp)", "uid") == "![x](../../../assets/uid/fig_1.webp)"


def test_publish_dry_run(tmp_path):
    cfg, repo = _setup(tmp_path)
    result = publish(cfg, repo, dry_run=True, target_date="2026-03-16")
    assert result["dry_run"] is True
    assert result["passed"] == 1
    # 不写盘
    assert not (cfg.paper_repo_path / "docs" / "papers" / "2026" / "CVPR" / "arxiv_2603.12345.md").exists()
    assert repo.get_paper("arxiv_2603.12345").status == PaperStatus.QUEUED.value


def test_publish_real(tmp_path):
    cfg, repo = _setup(tmp_path)
    result = publish(cfg, repo, dry_run=False, target_date="2026-03-16")
    assert result["passed"] == 1
    dest = cfg.paper_repo_path / "docs" / "papers" / "2026" / "CVPR" / "arxiv_2603.12345.md"
    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    assert "../../../assets/arxiv_2603.12345/fig_1.webp" in content
    assert (cfg.paper_repo_path / "docs" / "assets" / "arxiv_2603.12345" / "fig_1.webp").exists()
    assert (cfg.paper_repo_path / "docs" / "index.md").exists()
    assert repo.get_paper("arxiv_2603.12345").status == PaperStatus.PUBLISHED.value
