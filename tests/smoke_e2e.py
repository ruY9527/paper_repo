"""04 文档第 6 节端到端冒烟测试：S/A/B 三篇论文全流水线。

用隔离的临时工作区运行，避免污染真实数据。可直接 python tests/smoke_e2e.py。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paperflow.config import load_example_config
from paperflow.db.models import PaperRecord, PaperStatus, PaperTier
from paperflow.db.repository import PaperRepository
from paperflow.pipeline.cleaner import clean_papers
from paperflow.pipeline.md_validator import validate_all_staged
from paperflow.pipeline.queue_exporter import export_queue
from paperflow.publisher.aggregator import rebuild_all
from paperflow.publisher.digest import generate_digest
from paperflow.publisher.sync_blog import publish


TARGET_DATE = "2026-03-16"

VALID_MD_TEMPLATE = (
    "---\npaper_uid: \"{uid}\"\ntitle: \"{title}\"\nvenue: \"CVPR\"\n"
    "year: 2026\ntier: \"{tier}\"\ntldr: \"一句话总结本文核心方法与性能突破。\"\n---\n\n"
    "# {title}\n\n## 1. 一句话总结\n" + "本文提出新方法并取得最先进结果。" * 20 + "\n\n"
    "## 2. 核心方法\n" + "详细方法描述与方法细节。" * 30 + "\n\n"
    "<!-- PAPERFLOW_METRICS_JSON\n{{\"task\": \"Video Understanding\", \"backbone\": \"ViT-L\", "
    "\"datasets\": [\"Kinetics-400\"], \"sota_summary\": \"mAP 75%\", "
    "\"innovation_tags\": [\"Zero-Shot\"]}}\n-->\n"
)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="paperflow_e2e_"))
    print(f"[E2E] 临时工作区: {tmp}")
    cfg = load_example_config()
    cfg.project.workspace_dir = str(tmp / "workspace")
    cfg.project.paper_repo_dir = str(tmp / "paper_repo")
    cfg.publish.auto_git_commit = False
    repo = PaperRepository(cfg.db_path)

    # --- 构造 S/A/B 三篇论文 ---
    def mk(uid, tier, status, abstract, pdf=False):
        p = PaperRecord(
            paper_uid=uid, title=f"Paper {uid} on Video Understanding",
            normalized_title=f"paper {uid} on video understanding",
            authors_json='["Alice"]', venue="CVPR", pub_year=2026,
            pub_date=TARGET_DATE, fetch_date=TARGET_DATE, source="arxiv",
            tier=tier, status=status, abstract=abstract,
            paper_url=f"https://arxiv.org/abs/{uid}",
            code_url="https://github.com/demo/repo" if tier == "S" else "",
        )
        repo.upsert_paper(p)
        return p

    s_paper = mk("arxiv_2603.s0001", "S", PaperStatus.DOWNLOADED.value,
                 "A novel approach for video understanding.", pdf=True)
    a_paper = mk("arxiv_2603.a0002", "A", PaperStatus.SCORED.value,
                 "A concise study of temporal action.", pdf=False)
    mk("arxiv_2603.b0003", "B", PaperStatus.SKIPPED.value,
       "A low priority archival paper.", pdf=False)
    assert repo.count_papers() == 3
    print("[E2E] ✓ 已构造 S/A/B 三篇论文")

    # --- export-queue ---
    q = export_queue(cfg, repo, target_date=TARGET_DATE)
    assert q["count"] == 2, q  # S + A 入队
    queue_root = Path(q["queue_root"])
    assert (queue_root / "queue_manifest.json").exists()
    for uid in ("arxiv_2603.s0001", "arxiv_2603.a0002"):
        d = queue_root / uid
        assert (d / "meta.json").exists()
        assert (d / "extracted_text.md").exists()
        assert (d / "prompt.md").exists()
    print("[E2E] ✓ export-queue 生成完整任务包")

    # --- 模拟 Harness 写入 staging MD ---
    staging = cfg.workspace_path / "staging" / TARGET_DATE
    staging.mkdir(parents=True, exist_ok=True)
    for p in (s_paper, a_paper):
        (staging / f"{p.paper_uid}.md").write_text(
            VALID_MD_TEMPLATE.format(uid=p.paper_uid, title=p.title, tier=p.tier),
            encoding="utf-8",
        )

    # --- validate ---
    results = validate_all_staged(cfg, repo, target_date=TARGET_DATE)
    assert all(r.ok for r in results), [(r.paper_uid, r.errors) for r in results]
    assert len(repo.get_all_metrics()) == 2
    digest = generate_digest(cfg, repo, target_date=TARGET_DATE)
    assert digest.exists()
    print("[E2E] ✓ validate 通过，metrics 入库，TODAY_DIGEST 生成")

    # --- 模拟 S 级 PDF 存在 ---
    pdf_dir = cfg.workspace_path / "tmp" / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    s_pdf = pdf_dir / "arxiv_2603.s0001.pdf"
    s_pdf.write_bytes(b"%PDF-1.4 fake pdf content" * 20)
    repo.update_status("arxiv_2603.s0001", PaperStatus.PUBLISHED.value,
                       pdf_local_path=str(s_pdf))

    # --- publish --clean（不走 git，因为 paper_repo 非 git 仓库）---
    rebuild_all(cfg, repo)
    pub = publish(cfg, repo, clean=True, dry_run=False, target_date=TARGET_DATE)
    assert pub["passed"] == 2, pub
    docs = cfg.paper_repo_path / "docs"
    assert (docs / "papers" / "2026" / "CVPR" / "arxiv_2603.s0001.md").exists()
    assert (docs / "index.md").exists()
    assert (docs / "venues" / "CVPR-2026.md").exists()
    assert (docs / "matrix" / "sota-2026.md").exists()
    assert (docs / "matrix" / "open-source-2026.md").exists()
    print("[E2E] ✓ publish 生成文章、首页、Venue 总表、SOTA 矩阵、开源库")

    # --- 验证清理效果（B 级从未下载 PDF，仅验证 S 级账本字段）---
    s_updated = repo.get_paper("arxiv_2603.s0001")
    assert s_updated.pdf_deleted == 1, "S 级发布后应已清理"
    assert s_updated.status == PaperStatus.CLEANED.value
    print("[E2E] ✓ S 级 PDF 已删除，status=CLEANED, pdf_deleted=1")

    # --- 清理临时工作区 ---
    shutil.rmtree(tmp, ignore_errors=True)
    print("[E2E] 全部端到端验收通过 ✓")


if __name__ == "__main__":
    main()
