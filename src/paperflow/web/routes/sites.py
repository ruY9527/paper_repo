"""Phase 14：网站收录中心 REST API + SSE 批量任务路由。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from ..state import get_manager
from ..task_manager import TaskBusyError, TaskManager
from ...sites.blog_renderer import sync_sites_blog
from ...sites.bookmark_importer import parse_bookmarks_html, parse_url_lines
from ...sites.health_checker import check_many
from ...sites.metadata_fetcher import fetch_metadata, normalize_url

router = APIRouter(prefix="/api/sites", tags=["sites"])


# ---------- 只读 ----------

@router.get("")
def list_sites(
    category_id: int | None = None, is_public: int | None = None,
    is_pinned: int | None = None, health_status: str | None = None,
    tag: str | None = None, q: str | None = None, sort: str = "recent",
    limit: int = 100, offset: int = 0,
    manager: TaskManager = Depends(get_manager),
):
    items = manager.repo.get_sites(
        category_id=category_id, is_public=is_public, is_pinned=is_pinned,
        health_status=health_status, tag=tag, q=q, sort=sort,
        limit=limit, offset=offset,
    )
    return {"items": items, "stats": manager.repo.count_sites(),
            "limit": limit, "offset": offset}


@router.get("/categories")
def get_categories(manager: TaskManager = Depends(get_manager)):
    return {"items": manager.repo.get_site_categories()}


# ---------- 元信息抓取 ----------

@router.post("/fetch-meta")
def fetch_meta(body: dict[str, Any] = Body(...)):
    url = body.get("url", "")
    if not url:
        raise HTTPException(status_code=422, detail="url 不能为空")
    return fetch_metadata(url, timeout=10.0)


# ---------- CRUD ----------

@router.post("")
def create_site(body: dict[str, Any] = Body(...), manager: TaskManager = Depends(get_manager)):
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="url 不能为空")
    try:
        norm, domain = normalize_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if manager.repo.get_site_by_normalized_url(norm):
        raise HTTPException(status_code=409, detail="该网站已收录（标准化 URL 重复）")
    cat_id = body.get("category_id") or body.get("category")
    if isinstance(cat_id, str):
        cats = {c["slug"]: c["id"] for c in manager.repo.get_site_categories()}
        cat_id = cats.get(cat_id)
    if not cat_id:
        raise HTTPException(status_code=422, detail="category_id 无效")
    try:
        sid = manager.repo.add_site(
            url=url, normalized_url=norm, domain=domain,
            title=body.get("title") or domain,
            description=body.get("description", ""),
            personal_note=body.get("personal_note", ""),
            category_id=int(cat_id), tags=body.get("tags") or [],
            favicon_url=body.get("favicon_url", ""),
            rating=int(body.get("rating", 0)),
            is_pinned=int(bool(body.get("is_pinned", False))),
            is_public=int(body.get("is_public", True)),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"保存失败: {exc}")
    return {"id": sid, "ok": True, "site": manager.repo.get_site(sid)}


@router.put("/{site_id}")
def update_site(site_id: int, body: dict[str, Any] = Body(...),
                manager: TaskManager = Depends(get_manager)):
    if manager.repo.get_site(site_id) is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    fields = {k: v for k, v in body.items() if k in (
        "title", "description", "personal_note", "category_id", "favicon_url",
        "rating", "is_pinned", "is_public")}
    if "tags" in body:
        import json
        fields["tags_json"] = json.dumps(body["tags"] or [], ensure_ascii=False)
    for k in ("is_pinned", "is_public"):
        if k in fields:
            fields[k] = int(bool(fields[k]))
    # 允许改地址：重新标准化去重并更新 domain/normalized_url
    if "url" in body and str(body["url"]).strip():
        try:
            norm, domain = normalize_url(body["url"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        other = manager.repo.get_site_by_normalized_url(norm)
        if other and other["id"] != site_id:
            raise HTTPException(status_code=409, detail="该地址已被其它收藏占用")
        fields.update(url=str(body["url"]).strip(), normalized_url=norm, domain=domain)
    manager.repo.update_site(site_id, **fields)
    return {"ok": True, "site": manager.repo.get_site(site_id)}


@router.post("/{site_id}/visit")
def visit_site(site_id: int, manager: TaskManager = Depends(get_manager)):
    """记录一次打开（用于按使用频率排序）。"""
    if manager.repo.get_site(site_id) is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    manager.repo.mark_site_visited(site_id)
    return {"ok": True, "site": manager.repo.get_site(site_id)}


@router.delete("/{site_id}")
def delete_site(site_id: int, manager: TaskManager = Depends(get_manager)):
    if manager.repo.get_site(site_id) is None:
        raise HTTPException(status_code=404, detail="网站不存在")
    manager.repo.delete_site(site_id)
    return {"ok": True, "deleted": site_id}


# ---------- 分类 CRUD ----------

@router.post("/categories")
def add_category(body: dict[str, Any] = Body(...), manager: TaskManager = Depends(get_manager)):
    if not body.get("name") or not body.get("slug"):
        raise HTTPException(status_code=422, detail="name 与 slug 必填")
    try:
        cid = manager.repo.add_site_category(
            name=body["name"], slug=body["slug"], icon=body.get("icon", "🔗"),
            description=body.get("description", ""), sort_order=int(body.get("sort_order", 100)),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"分类创建失败: {exc}")
    return {"id": cid, "ok": True}


@router.put("/categories/{cat_id}")
def edit_category(cat_id: int, body: dict[str, Any] = Body(...),
                  manager: TaskManager = Depends(get_manager)):
    manager.repo.update_site_category(cat_id, **{k: v for k, v in body.items()
        if k in ("name", "slug", "icon", "description", "sort_order")})
    return {"ok": True}


@router.delete("/categories/{cat_id}")
def remove_category(cat_id: int, manager: TaskManager = Depends(get_manager)):
    # 若分类下还有网站，拒绝删除
    if manager.repo.get_sites(category_id=cat_id, limit=1):
        raise HTTPException(status_code=422, detail="分类下仍有网站，请先移动或删除")
    manager.repo.delete_site_category(cat_id)
    return {"ok": True}


# ---------- 批量任务（SSE） ----------

def _run_batch_import(ctx: dict):
    manager: TaskManager = ctx["manager"]
    params = ctx["params"]
    emit = ctx["emit"]
    from ...sites.metadata_fetcher import normalize_url
    urls = params.get("urls") or []
    records = {r["url"]: r for r in (params.get("records") or [])}
    default_cat = params.get("category_id") or manager.repo.get_site_categories()[0]["id"]
    ok = dup = fail = 0
    for i, url in enumerate(urls, 1):
        try:
            norm, domain = normalize_url(url)
            if manager.repo.get_site_by_normalized_url(norm):
                dup += 1
                emit(stage="batch_import", current=i, total=len(urls),
                     message=f"{i}/{len(urls)} 跳过重复: {url}")
                continue
            # 纯收录：只登记地址与来源自带的标题，不抓取网页内容
            rec = records.get(url, {})
            manager.repo.add_site(
                url=url, normalized_url=norm, domain=domain,
                title=rec.get("title") or domain,
                description="", favicon_url="",
                category_id=int(rec.get("category_id") or default_cat),
            )
            ok += 1
            emit(stage="batch_import", current=i, total=len(urls),
                 message=f"{i}/{len(urls)} 已收藏: {domain}")
        except Exception as exc:
            fail += 1
            emit(stage="batch_import", level="WARNING", current=i, total=len(urls),
                 message=f"{i}/{len(urls)} 失败: {url} ({exc})")
    result = {"imported": ok, "duplicates": dup, "failed": fail, "total": len(urls)}
    emit(stage="result", percent=100, message=f"批量导入完成：{ok} 新增 / {dup} 重复 / {fail} 失败",
         result=result)
    return result


@router.post("/batch-import-urls")
def batch_import_urls(body: dict[str, Any] = Body(...), manager: TaskManager = Depends(get_manager)):
    urls = parse_url_lines(body.get("text", ""))
    if not urls:
        raise HTTPException(status_code=422, detail="没有可导入的 URL")
    try:
        task = manager.submit("site-import", _run_batch_import,
                              {"urls": urls, "category_id": body.get("category_id")})
    except TaskBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"task_id": task.task_id, "count": len(urls)}


@router.post("/import-bookmarks")
async def import_bookmarks(
    file: UploadFile = File(...), category_id: int | None = None,
    manager: TaskManager = Depends(get_manager),
):
    data = await file.read()
    items = parse_bookmarks_html(data.decode("utf-8", errors="replace"))
    if not items:
        raise HTTPException(status_code=422, detail="未解析到书签")
    # 文件夹名 -> 分类 id 映射
    cats = manager.repo.get_site_categories()
    cat_by_name = {c["name"]: c["id"] for c in cats}
    default_cat = category_id or cats[0]["id"]
    records = []
    for it in items:
        records.append({"url": it["url"], "title": it.get("title", ""),
                        "category_id": cat_by_name.get(it.get("folder", ""), default_cat)})
    try:
        task = manager.submit("site-import", _run_batch_import,
                              {"urls": [r["url"] for r in records], "category_id": default_cat,
                               "records": records})
    except TaskBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"task_id": task.task_id, "count": len(records)}


def _run_health(ctx: dict):
    manager: TaskManager = ctx["manager"]
    emit = ctx["emit"]
    sites = manager.repo.get_sites(limit=100000)
    results = check_many(sites, timeout=manager.config.sites.health_check_timeout_seconds,
                         concurrency=manager.config.sites.health_check_concurrency,
                         progress_cb=lambda **kw: emit(**kw))
    for r in results:
        manager.repo.update_site_health(r["id"], status=r["status"],
                                        http_status=r.get("http_status"), checked_at=r["checked_at"])
    from collections import Counter
    counts = dict(Counter(r["status"] for r in results))
    result = {"checked": len(results), "counts": counts}
    emit(stage="result", percent=100, message=f"巡检完成：{counts}", result=result)
    return result


@router.post("/health-check")
def health_check(manager: TaskManager = Depends(get_manager)):
    try:
        task = manager.submit("site-health", _run_health, {})
    except TaskBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"task_id": task.task_id}


@router.get("/publish-status")
def publish_status(manager: TaskManager = Depends(get_manager)):
    """网站收录的发布状态：导航页是否已同步、是否有未发布变更、Git 是否有未推送提交。

    用于网站收录中心提示用户「收藏的网站还没发布到 GitHub Pages」，
    与 Git 发布中心形成闭环。
    """
    import subprocess
    from datetime import datetime, timezone
    index = manager.config.paper_repo_path / "docs" / "sites" / "index.md"
    sites = manager.repo.get_sites(is_public=1, limit=100000)
    # 网站最新变更时间 vs 导航页生成时间
    latest_site = max((s.get("updated_at") or s.get("created_at") or "" for s in sites), default="")
    index_mtime = index.stat().st_mtime if index.exists() else 0
    nav_stale = bool(sites) and (not index.exists() or _iso_to_ts(latest_site) > index_mtime + 1)
    # Git 未推送 / 未提交
    unpushed = 0; dirty = False
    try:
        repo_path = str(manager.config.paper_repo_path)
        r = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path,
                           capture_output=True, text=True, timeout=8)
        dirty = bool(r.stdout.strip()) if r.returncode == 0 else False
        r2 = subprocess.run(["git", "rev-list", "--count", "origin/main..HEAD"], cwd=repo_path,
                            capture_output=True, text=True, timeout=8)
        if r2.returncode == 0:
            unpushed = int(r2.stdout.strip() or 0)
    except Exception:
        pass
    return {
        "public_count": len(sites),
        "nav_exists": index.exists(),
        "nav_stale": nav_stale,
        "git_dirty": dirty,
        "unpushed_commits": unpushed,
        "needs_publish": nav_stale or dirty or unpushed > 0,
    }


def _iso_to_ts(s: str) -> float:
    """把仓储里 ISO 时间串转时间戳；解析失败返回 0。"""
    if not s:
        return 0
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0


@router.post("/sync-blog")
def sync_blog(body: dict[str, Any] = Body(default={}),
              manager: TaskManager = Depends(get_manager)):
    r = sync_sites_blog(manager.config, manager.repo, layout=body.get("layout"))
    return r


# ---------- 导航页内容预览（本地查看） ----------

@router.get("/blog-content")
def blog_content(manager: TaskManager = Depends(get_manager)):
    path = manager.config.paper_repo_path / "docs" / "sites" / "index.md"
    if not path.exists():
        return {"exists": False, "content": ""}
    return {"exists": True, "content": path.read_text(encoding="utf-8"), "path": str(path)}
