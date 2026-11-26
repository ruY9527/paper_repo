"""待审工作台与存储治理 API。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException

from ..state import get_manager
from ..task_manager import TaskManager

router = APIRouter(prefix="/api", tags=["staging"])


def _staging_files(manager: TaskManager) -> list[Path]:
    root = manager.config.workspace_path / "staging"
    if not root.exists():
        return []
    return sorted(
        p for p in root.glob("**/*.md")
        if p.name != "TODAY_DIGEST.md"
    )


def _date_of(md: Path) -> str:
    for part in md.parts:
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            return part
    return ""


@router.get("/staging")
def list_staging(
    q: str | None = None,
    status: str = "pending",  # pending(默认,未发布) | published(已发布) | all(全部)
    limit: int = 50,
    offset: int = 0,
    manager: TaskManager = Depends(get_manager),
):
    from ...pipeline.md_validator import validate_md_file

    def _is_published(md) -> bool:
        r = manager.repo.get_paper(md.stem)
        return bool(r and r.status in ("PUBLISHED", "CLEANED"))

    all_mds = _staging_files(manager)
    # 状态筛选：默认只看「真正待审」的（未发布），已发布的不再混入待审队列
    if status == "pending":
        all_mds = [md for md in all_mds if not _is_published(md)]
    elif status == "published":
        all_mds = [md for md in all_mds if _is_published(md)]
    # all: 不过滤
    if q:
        needle = q.lower()
        all_mds = [md for md in all_mds
                   if needle in md.stem.lower()
                   or needle in (manager.repo.get_paper(md.stem).title if manager.repo.get_paper(md.stem) else "").lower()]
    total = len(all_mds)
    page_mds = all_mds[offset:offset + limit]
    items = []
    for md in page_mds:
        uid = md.stem
        record = manager.repo.get_paper(uid)
        # 校验状态（不写库）
        result = validate_md_file(md, manager.repo, manager.config, persist=False)
        thumb = ""
        assets = manager.config.workspace_path / "staging" / "assets" / uid
        if assets.exists():
            figs = sorted(assets.glob("*.webp"))
            if figs:
                thumb = f"/api/staging/{uid}/figure/{figs[0].name}"
        items.append({
            "paper_uid": uid,
            "date": _date_of(md),
            "title": record.title if record else uid,
            "tier": record.tier if record else "",
            "venue": record.venue if record else "",
            "tldr": record.abstract[:100] if record and record.abstract else "",
            "valid": result.ok,
            "errors": result.errors,
            "path": str(md),
            "thumbnail": thumb,
            # 发布状态：前端据此区分「待发布」与「已发布」，避免重复点击
            "status": record.status if record else "",
            "md_blog_path": (getattr(record, "md_blog_path", "") or "") if record else "",
            "published": bool(record and record.status in ("PUBLISHED", "CLEANED")),
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset, "status_filter": status}


@router.get("/staging/{paper_uid}")
def read_staging(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    matches = [p for p in _staging_files(manager) if p.stem == paper_uid]
    if not matches:
        raise HTTPException(status_code=404, detail="Staging 文件不存在")
    return {
        "paper_uid": paper_uid,
        "content": matches[0].read_text(encoding="utf-8"),
        "path": str(matches[0]),
    }


@router.put("/staging/{paper_uid}")
def save_staging(paper_uid: str, body: dict[str, Any] = Body(...),
                 manager: TaskManager = Depends(get_manager)):
    """保存人工批注后的 Markdown 并重新校验（原子写入）。"""
    import os
    content = body.get("content")
    if not isinstance(content, str):
        raise HTTPException(status_code=422, detail="缺少 content")
    matches = [p for p in _staging_files(manager) if p.stem == paper_uid]
    if not matches:
        raise HTTPException(status_code=404, detail="Staging 文件不存在")
    target = matches[0]
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, target)

    from ...pipeline.md_validator import validate_md_file
    result = validate_md_file(target, manager.repo, manager.config, persist=True)
    return {
        "paper_uid": paper_uid, "saved": True,
        "valid": result.ok, "errors": result.errors,
    }


@router.delete("/staging/{paper_uid}")
def delete_staging(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    matches = [p for p in _staging_files(manager) if p.stem == paper_uid]
    if not matches:
        raise HTTPException(status_code=404, detail="Staging 文件不存在")
    matches[0].unlink()
    return {"paper_uid": paper_uid, "deleted": True}


@router.post("/staging/{paper_uid}/publish")
def publish_staging(paper_uid: str, manager: TaskManager = Depends(get_manager)):
    """把单篇已校验通过的待审文章发布到博客仓库。"""
    from ...publisher.blog_articles import publish_one
    r = publish_one(manager.config, manager.repo, paper_uid)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error", "发布失败"))
    return r


@router.get("/staging/{paper_uid}/figure/{filename}")
def staging_figure(paper_uid: str, filename: str,
                   manager: TaskManager = Depends(get_manager)):
    from fastapi.responses import FileResponse
    base = (manager.config.workspace_path / "staging" / "assets" / paper_uid).resolve()
    target = (base / filename).resolve()
    if not target.is_relative_to(base) or not target.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(str(target), media_type="image/webp")


@router.get("/storage/files")
def storage_files(kind: str = "pdfs", manager: TaskManager = Depends(get_manager)):
    """存储明细列表：临时 PDF / 队列目录 / 可清理预览，供卡片数字点击查看。"""
    from datetime import datetime, timezone
    from ...utils.timeutil import fmt_display
    ws = manager.config.workspace_path

    def _ts(p: Path) -> str:
        try:
            return fmt_display(datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat())
        except Exception:
            return ""

    def _size(p: Path) -> float:
        try:
            return round(p.stat().st_size / (1024 * 1024), 4)
        except Exception:
            return 0.0

    items: list[dict] = []
    if kind == "pdfs":
        root = ws / "tmp" / "pdfs"
        if root.exists():
            for f in sorted(root.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
                items.append({"name": f.name, "uid": f.stem, "size_mb": _size(f),
                              "mtime": _ts(f), "path": str(f)})
    elif kind == "queue":
        root = ws / "queue"
        if root.exists():
            for d in sorted([x for x in root.iterdir() if x.is_dir()],
                            key=lambda p: p.stat().st_mtime, reverse=True):
                files = [x for x in d.rglob("*") if x.is_file()]
                items.append({"name": d.name, "uid": "", "files": len(files),
                              "size_mb": round(sum(_size(f) for f in files), 4),
                              "mtime": _ts(d), "path": str(d)})
    elif kind == "cleanup":
        # 复用 dry-run 结果里的明细（clean_papers 返回的 removed/item 列表）
        try:
            from ...pipeline.cleaner import clean_papers
            preview = clean_papers(manager.config, manager.repo, include_staged=False, dry_run=True)
            for it in (preview.get("items") or []):
                items.append({
                    "name": it.get("title") or it.get("paper_uid", ""),
                    "uid": it.get("paper_uid", ""),
                    "size_mb": it.get("size_mb", 0.0),
                    "paths": it.get("paths", []),
                    "path": (it.get("paths") or [""])[0],
                })
        except Exception:
            items = []
    return {"kind": kind, "total": len(items), "items": items}


@router.get("/storage/summary")
def storage_summary(manager: TaskManager = Depends(get_manager)):
    ws = manager.config.workspace_path

    def stat(path: Path) -> dict:
        if not path.exists():
            return {"files": 0, "dirs": 0, "size_mb": 0.0}
        files = [f for f in path.rglob("*") if f.is_file()]
        dirs = [d for d in path.rglob("*") if d.is_dir()]
        return {
            "files": len(files),
            "dirs": len(dirs),
            "size_mb": round(sum(f.stat().st_size for f in files) / (1024 * 1024), 3),
        }

    # 可清理预览（dry-run 逻辑，无副作用）
    from ...pipeline.cleaner import clean_papers
    preview = None
    try:
        preview = clean_papers(manager.config, manager.repo, include_staged=False, dry_run=True)
    except Exception:
        preview = {"cleaned": 0, "freed_mb": 0}

    return {
        "pdfs": stat(ws / "tmp" / "pdfs"),
        "queue": stat(ws / "queue"),
        "state_db": {
            "size_mb": round(ws.joinpath("state.db").stat().st_size / (1024 * 1024), 3)
            if (ws / "state.db").exists() else 0.0,
            "protected": True,
        },
        "cleanup_preview": preview,
    }
