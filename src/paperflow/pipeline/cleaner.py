"""用完即焚安全清理引擎（03 文档第 6 节）。

绝对禁区：待删路径必须严格位于 workspace/tmp/ 或 workspace/queue/ 内。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import AppConfig
from ..db.models import PaperStatus, RunStatus
from ..db.repository import PaperRepository
from ..utils.logger import get_logger

logger = get_logger()


class UnsafeDeleteError(Exception):
    """待删路径越界时抛出，拒绝删除。"""


def _assert_safe_delete(path: Path, workspace: Path) -> None:
    """硬编码校验：路径必须位于 workspace/tmp 或 workspace/queue 内。"""
    resolved = path.resolve()
    allowed_roots = [workspace.resolve() / "tmp", workspace.resolve() / "queue"]
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise UnsafeDeleteError(
            f"拒绝删除越界路径: {resolved}（仅允许 workspace/tmp 或 workspace/queue）"
        )


def _has_valid_markdown(config: AppConfig, paper) -> bool:
    """分别按 workspace 与 paper_repo/docs 解析相对 MD 路径。"""
    candidates = (
        (paper.md_staging_path, config.workspace_path),
        (paper.md_blog_path, config.paper_repo_path / "docs"),
    )
    for raw, base in candidates:
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = base / path
        if path.is_file() and path.stat().st_size > 0:
            return True
    return False


def _remove_from_queue_manifests(workspace: Path, paper_uid: str) -> None:
    """任务包删除后，同步移除所有日期 manifest 中的该论文条目。"""
    queue_root = workspace / "queue"
    if not queue_root.exists():
        return
    for manifest_path in queue_root.glob("*/queue_manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            key = "items" if "items" in manifest else "papers"
            papers = manifest.get(key, [])
            kept = [p for p in papers if p.get("paper_uid") != paper_uid]
            if len(kept) == len(papers):
                continue
            manifest[key] = kept
            if key == "items":
                manifest["count"] = len(kept)
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            logger.warning(f"[clean] manifest 更新失败 {manifest_path}: {exc}")


def clean_papers(
    config: AppConfig,
    repo: PaperRepository,
    *,
    include_staged: bool = False,
    dry_run: bool = False,
) -> dict:
    """清理已发布（可选含 STAGED）论文的临时 PDF 与队列目录。"""
    workspace = config.workspace_path
    statuses = [PaperStatus.PUBLISHED.value]
    if include_staged:
        statuses += [PaperStatus.STAGED.value, PaperStatus.ANALYZED.value]

    candidates = [
        p for p in repo.get_papers_by_status(*statuses)
        if p.pdf_deleted == 0
    ]
    cleaned = 0
    freed_bytes = 0
    clean_items: list[dict] = []  # 明细（供存储治理点击数字查看）

    for paper in candidates:
        # 前置条件：staging 或博客 MD 真实存在且非空（支持相对博客路径）。
        if not _has_valid_markdown(config, paper):
            logger.warning(f"[clean] {paper.paper_uid} 无有效 MD，拒绝清理")
            continue

        to_delete: list[Path] = []
        if paper.pdf_local_path:
            pdf = Path(paper.pdf_local_path)
            if pdf.exists():
                _assert_safe_delete(pdf, workspace)
                to_delete.append(pdf)
        # 队列目录：workspace/queue/*/<paper_uid>/
        for queue_dir in (workspace / "queue").glob("**/" + paper.paper_uid):
            if queue_dir.is_dir():
                _assert_safe_delete(queue_dir, workspace)
                to_delete.append(queue_dir)

        clean_items.append({
            "paper_uid": paper.paper_uid,
            "title": paper.title or "",
            "paths": [str(p) for p in to_delete],
            "size_mb": round(sum(
                (sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir()
                 else p.stat().st_size)
                for p in to_delete if p.exists()
            ) / (1024 * 1024), 4),
        })
        if dry_run:
            logger.info(f"[clean][dry-run] 将删除 {paper.paper_uid}: {[str(p) for p in to_delete]}")
            cleaned += 1
            continue

        for path in to_delete:
            _assert_safe_delete(path, workspace)  # 删除前二次校验
            if path.is_dir():
                import shutil
                freed_bytes += sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                shutil.rmtree(path)
            else:
                freed_bytes += path.stat().st_size
                path.unlink()

        _remove_from_queue_manifests(workspace, paper.paper_uid)

        # 清理空日期目录
        for date_dir in (workspace / "queue").iterdir() if (workspace / "queue").exists() else []:
            if date_dir.is_dir() and not any(date_dir.iterdir()):
                date_dir.rmdir()

        repo.update_status(
            paper.paper_uid,
            PaperStatus.CLEANED.value if paper.status == PaperStatus.PUBLISHED.value else paper.status,
            pdf_local_path=None,
            pdf_deleted=1,
        )
        cleaned += 1
        logger.info(f"[clean] {paper.paper_uid} 清理完成，状态更新")

    freed_mb = round(freed_bytes / (1024 * 1024), 3)
    run_id = repo.start_run("clean")
    repo.finish_run(
        run_id, RunStatus.SUCCESS,
        cleaned_count=cleaned,
        message=f"释放 {freed_mb} MB，清理 {cleaned} 篇" + (" (dry-run)" if dry_run else ""),
    )
    return {"cleaned": cleaned, "freed_mb": freed_mb, "dry_run": dry_run, "items": clean_items}
