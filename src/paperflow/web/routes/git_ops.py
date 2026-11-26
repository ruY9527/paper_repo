"""Git 发布中心 REST API（Phase 9，06 文档第 4 节）。

写操作（commit-push / publish-and-push / pull）统一走 TaskManager 互斥锁 + SSE。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from ...publisher.git_service import (
    BlogGitService,
    GitServiceError,
    UnsafePathError,
)
from ..state import get_manager
from ..task_manager import TaskBusyError, TaskManager, TaskCancelledError
from ...utils.timeutil import today_date

router = APIRouter(prefix="/api/git", tags=["git"])


def _service(manager: TaskManager) -> BlogGitService:
    return BlogGitService(
        manager.config.paper_repo_path,
        remote_name=manager.config.publish.git_remote_name,
        repo=manager.repo,
        trigger_source="web",
    )


def _status_dict(status) -> dict[str, Any]:
    return {
        "is_git_repo": status.is_git_repo,
        "branch": status.branch,
        "remote_url": status.remote_url,
        "is_ssh_remote": status.is_ssh_remote,
        "ahead_count": status.ahead_count,
        "behind_count": status.behind_count,
        "has_changes": status.has_changes,
        "changes": [
            {"path": c.path, "status": c.status_code, "category": c.category}
            for c in status.changes
        ],
        "added": sum(1 for c in status.changes if c.category in ("added", "untracked")),
        "modified": sum(1 for c in status.changes if c.category == "modified"),
        "deleted": sum(1 for c in status.changes if c.category == "deleted"),
        "last_commit": (
            {"short_hash": status.last_commit.short_hash,
             "message": status.last_commit.message,
             "date_iso": status.last_commit.date_iso}
            if status.last_commit else None
        ),
        "blog_site_url": None,  # 由路由注入
    }


# ---------- 只读 API ----------

@router.get("/status")
def git_status(manager: TaskManager = Depends(get_manager)):
    try:
        status = _service(manager).get_status()
    except GitServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    data = _status_dict(status)
    data["blog_site_url"] = manager.config.publish.blog_site_url
    return data


@router.post("/test-ssh")
def test_ssh(manager: TaskManager = Depends(get_manager)):
    try:
        return _service(manager).test_ssh_connection()
    except GitServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/diff")
def git_diff(path: str | None = Query(default=None),
             manager: TaskManager = Depends(get_manager)):
    try:
        return _service(manager).get_diff(path)
    except UnsafePathError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except GitServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/commits")
def git_commits(limit: int = Query(30, ge=1, le=200),
                offset: int = Query(0, ge=0),
                q: str | None = Query(None),
                manager: TaskManager = Depends(get_manager)):
    try:
        commits = _service(manager).get_commits(limit=limit, offset=offset, search=q)
    except GitServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"items": commits, "limit": limit, "offset": offset}


@router.get("/commits/{commit_hash}")
def git_commit_detail(commit_hash: str,
                      manager: TaskManager = Depends(get_manager)):
    try:
        return _service(manager).get_commit_detail(commit_hash)
    except UnsafePathError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except GitServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/push-logs")
def git_push_logs(limit: int = Query(50, ge=1, le=200),
                  offset: int = Query(0, ge=0),
                  manager: TaskManager = Depends(get_manager)):
    return {"items": manager.repo.get_git_push_logs(limit=limit, offset=offset)}


@router.get("/pages-status")
def pages_status(manager: TaskManager = Depends(get_manager)):
    """检查 gh-pages 部署状态，辅助判断「在线博客」404 的根因。"""
    svc = _service(manager)
    try:
        svc._validate_repo()
    except GitServiceError:
        return {"deployed": False, "gh_pages_exists": False,
                "message": "博客仓库未初始化 Git"}
    # 检查本地是否有 gh-pages 分支（已部署过 gh-deploy 的痕迹）
    local_gh_pages = False
    r = svc._run(["rev-parse", "--verify", "gh-pages"])
    local_gh_pages = r.returncode == 0
    # 检查远端 gh-pages 分支
    remote_gh_pages = False
    try:
        lr = svc._run(["ls-remote", "--heads", svc.remote_name, "gh-pages"], network=True, timeout=12)
        remote_gh_pages = lr.returncode == 0 and bool(lr.stdout.strip())
    except Exception:
        remote_gh_pages = False

    deployed = remote_gh_pages
    site_url = manager.config.publish.blog_site_url
    return {
        "deployed": deployed,
        "gh_pages_local": local_gh_pages,
        "gh_pages_remote": remote_gh_pages,
        "site_url": site_url,
        "message": (
            "gh-pages 分支已存在，但请注意：GitHub Pages 需在仓库 Settings 里启用，"
            "否则访问仍会 404。开启方法见 scripts/enable_pages.ps1"
            if deployed else "尚未推送 gh-pages 分支，请先执行「发布并推送」"
        ),
    }


# ---------- 写操作 runner（接入 TaskManager） ----------

def run_commit_push(ctx: dict):
    manager: TaskManager = ctx["manager"]
    params = ctx["params"]
    emit = ctx["emit"]
    svc = _service(manager)
    emit(stage="preparing", percent=5, message="准备 Git 提交推送")
    try:
        result = svc.commit_and_push(
            message=params.get("message", "docs: update"),
            push=bool(params.get("push", True)),
            pull_rebase_first=bool(params.get("pull_rebase_first", False)),
            progress_cb=lambda **kw: emit(**kw),
            task_id=ctx["task_id"],
            cancel_event=ctx["cancel_event"],
        )
        emit(stage="done", percent=100,
             message=("无待提交变更" if result.get("no_changes") else "Git 提交推送完成"))
        return result
    except TaskCancelledError:
        raise
    except GitServiceError as exc:
        emit(stage="error", percent=100, message=str(exc), level="ERROR")
        raise


def run_publish_and_push(ctx: dict):
    """全流程一键发布：sync_blog(publish) -> build 门禁 -> git commit & push -> clean。"""
    manager: TaskManager = ctx["manager"]
    params = ctx["params"]
    emit = ctx["emit"]
    from ...publisher.sync_blog import publish as do_publish

    emit(stage="syncing", percent=10, message="同步 Staging 到博客仓库并刷新聚合页")
    pub = do_publish(
        manager.config, manager.repo,
        push=False, clean=False, dry_run=False,  # Git 由本 runner 统一处理
        target_date=params.get("date"),
        skip_build_check=True,  # 门禁在本 runner 内显式执行，避免重复
    )
    emit(stage="validated", percent=40,
         message=f"校验通过 {pub['passed']} 篇，开始构建门禁")

    # 发布前 MkDocs 严格构建门禁
    skip_build = bool(params.get("skip_build_check", False))
    if manager.config.publish.require_mkdocs_strict_build and not skip_build:
        from ...publisher.mkdocs_service import MkDocsService
        msvc = MkDocsService(
            manager.config.paper_repo_path, manager.config.workspace_path,
            manager.config.publish.preview_port,
        )
        build = msvc.build_strict()
        if not build.ok:
            emit(stage="build_blocked", percent=100,
                 message=f"mkdocs --strict 构建失败（{build.error_count} 错误 / {build.warning_count} 警告），已拦截推送",
                 level="ERROR")
            for issue in build.issues:
                emit(stage="build_issue", percent=100,
                     message=f"[{issue['level']}] {issue['file']}: {issue['message']}", level="ERROR")
            return {"publish": pub, "git": {"committed": False, "pushed": False, "blocked_by_build": True},
                    "build_check": build.model_dump()}
        emit(stage="build_ok", percent=55, message="mkdocs --strict 构建通过")
        build_result = build.model_dump()
    else:
        build_result = None

    svc = _service(manager)
    message = params.get("message") or manager.config.publish.commit_message_template.format(
        count=pub["passed"], date=params.get("date") or today_date().isoformat()
    )
    result = svc.commit_and_push(
        message=message,
        push=bool(params.get("push", True)),
        pull_rebase_first=bool(params.get("pull_rebase_first", False)),
        progress_cb=lambda **kw: emit(**kw),
        task_id=ctx["task_id"],
        cancel_event=ctx["cancel_event"],
    )

    clean_result = None
    if params.get("clean", True) and manager.config.storage.auto_clean_after_publish:
        from ...pipeline.cleaner import clean_papers
        emit(stage="cleaning", percent=95, message="发布完成，清理临时 PDF")
        clean_result = clean_papers(manager.config, manager.repo, include_staged=False)

    return {"publish": pub, "git": result, "clean": clean_result, "build_check": build_result}


def run_pull(ctx: dict):
    manager: TaskManager = ctx["manager"]
    emit = ctx["emit"]
    emit(stage="pulling", percent=20, message="拉取远端更新（rebase）")
    result = _service(manager).pull_rebase()
    emit(stage="done", percent=100, message="远端更新已同步")
    return result


WRITE_RUNNERS = {
    "git-commit-push": run_commit_push,
    "git-publish-and-push": run_publish_and_push,
    "git-pull": run_pull,
}


def _submit(manager: TaskManager, command: str, params: dict):
    def runner(ctx):
        ctx["manager"] = manager
        return WRITE_RUNNERS[command](ctx)

    try:
        task = manager.submit(command, runner, params)
    except TaskBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"task_id": task.task_id, "command": command, "status": task.status}


@router.post("/commit-push")
def commit_push(body: dict[str, Any] = Body(default={}),
                manager: TaskManager = Depends(get_manager)):
    return _submit(manager, "git-commit-push", body)


@router.post("/publish-and-push")
def publish_and_push(body: dict[str, Any] = Body(default={}),
                     manager: TaskManager = Depends(get_manager)):
    return _submit(manager, "git-publish-and-push", body)


@router.post("/pull")
def pull(body: dict[str, Any] = Body(default={}),
         manager: TaskManager = Depends(get_manager)):
    return _submit(manager, "git-pull", body)
