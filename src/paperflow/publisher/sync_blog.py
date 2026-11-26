"""博客同步与 Git 自动发布器（04 文档第 3 节）。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..config import AppConfig
from ..db.repository import PaperRepository
from ..pipeline.md_validator import validate_all_staged
from ..utils.logger import get_logger
from ..utils.timeutil import today_date
from .aggregator import rebuild_all
from .blog_articles import publish_one

logger = get_logger()


def _run_git(args: list[str], cwd: Path, *, network: bool = False) -> tuple[int, str]:
    """执行 git 命令，返回 (returncode, output)。

    Windows 规范（Phase 9）：统一 -c core.quotepath=false（中文路径不乱码），
    强制 UTF-8 / shell=False；联网命令注入非交互 SSH 环境变量防卡死。
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
    if network:
        env.update({
            "GIT_SSH_COMMAND": (
                "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
            ),
        })
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false"] + args,
            cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
            shell=False, env=env,
        )
        return result.returncode, result.stdout + result.stderr
    except FileNotFoundError:
        return 127, "git 未安装或不在 PATH"
    except subprocess.TimeoutExpired:
        return 124, "git 命令超时"
    except Exception as exc:
        return 1, str(exc)


def publish(
    config: AppConfig,
    repo: PaperRepository,
    *,
    push: bool = False,
    clean: bool = False,
    dry_run: bool = False,
    target_date: str | None = None,
    skip_build_check: bool = False,
) -> dict:
    """执行完整 publish 流程。"""
    scan_all_unpublished = target_date is None
    commit_date = target_date or today_date().isoformat()
    blog = config.paper_repo_path

    # 1. 先校验所有待发文档（dry-run 时不写库）
    validations = validate_all_staged(
        config, repo, target_date=target_date, persist=not dry_run,
        only_unpublished=scan_all_unpublished,
    )
    passed = [v for v in validations if v.ok]
    failed = [v for v in validations if not v.ok]
    for v in failed:
        logger.warning(f"[publish] 校验未通过，跳过: {v.paper_uid}: {v.errors}")

    changes: list[str] = []
    publish_errors: list[dict[str, str]] = []
    for v in passed:
        result = publish_one(
            config, repo, v.paper_uid,
            staging_path=Path(v.path), dry_run=dry_run,
        )
        if not result.get("ok"):
            error = result.get("error", "发布失败")
            publish_errors.append({"paper_uid": v.paper_uid, "error": error})
            logger.warning(f"[publish] 单篇发布跳过: {v.paper_uid}: {error}")
            continue
        changes.append(result["repo_rel"])

    # 4. 刷新知识矩阵
    agg = rebuild_all(config, repo, dry_run=dry_run)
    changes.append(f"汇总页 x{agg['pages']}")

    # 5. 发布前 MkDocs 严格构建门禁（失败拦截 git commit/push）
    build_result = None
    if (not dry_run and not skip_build_check
            and config.publish.require_mkdocs_strict_build
            and (config.publish.auto_git_commit or push)):
        from .mkdocs_service import MkDocsService
        svc = MkDocsService(blog, config.workspace_path, config.publish.preview_port)
        build_result = svc.build_strict()
        if not build_result.ok:
            logger.error("[publish] mkdocs --strict 构建失败，已拦截 git 提交与推送")
            for issue in build_result.issues:
                logger.error(f"  [{issue['level']}] {issue['file']}: {issue['message']}")
            return {
                "date": commit_date,
                "validated": len(validations),
                "passed": len(passed),
                "failed": len(failed),
                "changes": changes,
                "publish_errors": publish_errors,
                "git": {"committed": False, "pushed": False, "blocked_by_build": True},
                "clean": None,
                "dry_run": dry_run,
                "build_check": build_result.model_dump(),
            }

    # 6. Git 操作
    git_result = {"committed": False, "pushed": False}
    if not dry_run and config.publish.auto_git_commit:
        rc, status_out = _run_git(["status", "--porcelain"], cwd=blog)
        if rc == 0 and status_out.strip():
            msg = config.publish.commit_message_template.format(
                count=len(passed), date=commit_date
            )
            _run_git(["add", "-A"], cwd=blog)
            rc2, out2 = _run_git(["commit", "-m", msg], cwd=blog)
            git_result["committed"] = rc2 == 0
            if rc2 != 0:
                logger.warning(f"[publish] git commit 失败: {out2}")
            if push or config.publish.auto_git_push:
                rc3, out3 = _run_git(
                    ["push", config.publish.git_remote_name], cwd=blog, network=True
                )
                git_result["pushed"] = rc3 == 0
                if rc3 != 0:
                    logger.warning(f"[publish] git push 失败: {out3}")
        else:
            logger.info("[publish] 无变更需要提交" if rc == 0 else f"[publish] git status 失败: {status_out}")

    # 7. 自动清理
    clean_result = None
    if clean and not dry_run and config.storage.auto_clean_after_publish:
        from ..pipeline.cleaner import clean_papers
        clean_result = clean_papers(config, repo, include_staged=False)

    return {
        "date": commit_date,
        "validated": len(validations),
        "passed": len(passed),
        "failed": len(failed),
        "changes": changes,
        "publish_errors": publish_errors,
        "git": git_result,
        "clean": clean_result,
        "dry_run": dry_run,
        "build_check": build_result.model_dump() if build_result else None,
    }
