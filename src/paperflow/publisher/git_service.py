"""博客仓库专用 Git/SSH 免密服务（Phase 9，06 文档第 3 节）。

安全红线：
- 所有 git 命令 cwd 强校验为 blog_repo_dir，且必须是独立 .git 仓库。
- 联网命令注入 GIT_TERMINAL_PROMPT=0 + GIT_SSH_COMMAND 非交互参数，绝不阻塞线程。
- 所有涉及文件名的命令附加 -c core.quotepath=false，subprocess 强制 UTF-8。
- commit_hash 正则校验；file_path 越界校验；shell=False。
- 所有写操作审计落库到 git_push_logs（成功失败均留痕）。
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..db.repository import PaperRepository
from ..utils.logger import get_logger

logger = get_logger()

_COMMIT_HASH_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

# Phase 9 规范：SSH 免密非交互，异常快速失败
GIT_ENV: dict[str, str] = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_SSH_COMMAND": (
        "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
    ),
    "GIT_CONFIG_NOSYSTEM": "1",
}

# git 命令统一前缀：中文路径不转义
_GIT_BASE = ["git", "-c", "core.quotepath=false"]


class GitServiceError(Exception):
    """Git 操作失败。"""


class UnsafePathError(GitServiceError):
    """路径越界或非法 commit hash。"""


@dataclass
class GitFileChange:
    path: str
    status_code: str
    category: str  # added | modified | deleted | untracked | renamed | other


@dataclass
class GitCommitSummary:
    short_hash: str
    message: str
    date_iso: str


@dataclass
class GitRepoStatus:
    is_git_repo: bool
    branch: str = ""
    remote_url: str = ""
    is_ssh_remote: bool = False
    ahead_count: int = 0
    behind_count: int = 0
    changes: list[GitFileChange] = field(default_factory=list)
    has_changes: bool = False
    last_commit: GitCommitSummary | None = None


class BlogGitService:
    """封装博客仓库的 Git 操作，所有命令严格锁定在 blog_repo_dir 内。"""

    def __init__(self, blog_repo_dir: str | Path, remote_name: str = "origin",
                 repo: PaperRepository | None = None,
                 trigger_source: str = "web"):
        self.blog_repo = Path(blog_repo_dir).resolve()
        self.remote_name = remote_name
        self.repo = repo
        self.trigger_source = trigger_source

    # ---- 安全与基础执行 ----

    def _validate_repo(self) -> None:
        """校验 blog_repo 是独立 git 仓库（.git 存在且不与外层同仓）。"""
        if not self.blog_repo.exists():
            raise GitServiceError(f"博客仓库目录不存在: {self.blog_repo}")
        git_dir = self.blog_repo / ".git"
        if not git_dir.exists():
            raise GitServiceError(f"博客仓库未初始化 Git: {self.blog_repo}")

    def _run(
        self,
        args: list[str],
        *,
        network: bool = False,
        timeout: int = 30,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        """执行 git 命令，cwd 锁定 blog_repo，强制 UTF-8、shell=False。"""
        self._validate_repo()
        cmd = _GIT_BASE + args
        run_env = GIT_ENV if network else {**os.environ, "GIT_TERMINAL_PROMPT": "0",
                                            "GIT_CONFIG_NOSYSTEM": "1"}
        if env:
            run_env = {**run_env, **env}
        try:
            return subprocess.run(
                cmd, cwd=str(self.blog_repo), capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                shell=False, timeout=timeout, env=run_env,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitServiceError(f"Git 命令超时: {' '.join(args)}") from exc
        except FileNotFoundError as exc:
            raise GitServiceError("git 可执行文件未找到") from exc

    @staticmethod
    def _validate_commit_hash(commit_hash: str) -> str:
        if not _COMMIT_HASH_RE.match(commit_hash or ""):
            raise UnsafePathError(f"非法 commit hash: {commit_hash!r}")
        return commit_hash

    def _validate_file_path(self, file_path: str) -> str:
        """文件路径必须在 blog_repo 内，返回仓库相对路径。"""
        target = (self.blog_repo / file_path).resolve()
        if not target.is_relative_to(self.blog_repo):
            raise UnsafePathError(f"文件路径越界: {file_path}")
        return str(target.relative_to(self.blog_repo).as_posix())

    @staticmethod
    def _category(code: str) -> str:
        c = code.upper()
        if "A" in c or "?" in c:
            return "untracked" if "?" in c else "added"
        if "M" in c:
            return "modified"
        if "D" in c:
            return "deleted"
        if "R" in c:
            return "renamed"
        return "other"

    # ---- 3.1 仓库与工作区状态 ----

    def get_status(self) -> GitRepoStatus:
        try:
            self._validate_repo()
        except GitServiceError:
            return GitRepoStatus(is_git_repo=False)

        branch_r = self._run(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch_r.stdout.strip() if branch_r.returncode == 0 else ""

        remote_r = self._run(["remote", "get-url", self.remote_name])
        remote_url = remote_r.stdout.strip() if remote_r.returncode == 0 else ""
        is_ssh = remote_url.startswith("git@") or remote_url.startswith("ssh://")

        ahead = behind = 0
        if remote_url and branch:
            # 无 upstream 时该命令返回非 0，优雅降级为 0,0
            cnt = self._run(
                ["rev-list", "--left-right", "--count",
                 f"HEAD...{self.remote_name}/{branch}"],
            )
            if cnt.returncode == 0:
                parts = cnt.stdout.split()
                if len(parts) == 2:
                    ahead, behind = int(parts[0]), int(parts[1])

        st = self._run(["status", "--porcelain=v1", "-uall"])
        changes: list[GitFileChange] = []
        if st.returncode == 0:
            for line in st.stdout.splitlines():
                if len(line) < 4:
                    continue
                code = line[:2]
                path = line[3:]
                # 重命名格式 "R  old -> new"，取新路径
                if " -> " in path:
                    path = path.split(" -> ", 1)[1]
                changes.append(GitFileChange(path=path, status_code=code,
                                             category=self._category(code)))

        last_commit = None
        log_r = self._run(["log", "-1", "--date=iso-strict",
                           "--format=%h%x1f%s%x1f%aI"])
        if log_r.returncode == 0 and log_r.stdout.strip():
            parts = log_r.stdout.strip().split("\x1f")
            if len(parts) >= 3:
                last_commit = GitCommitSummary(
                    short_hash=parts[0], message=parts[1], date_iso=parts[2]
                )

        return GitRepoStatus(
            is_git_repo=True, branch=branch, remote_url=remote_url,
            is_ssh_remote=is_ssh, ahead_count=ahead, behind_count=behind,
            changes=changes, has_changes=bool(changes), last_commit=last_commit,
        )

    # ---- 3.2 SSH 连通性 ----

    def test_ssh_connection(self) -> dict[str, Any]:
        status = self.get_status()
        if not status.is_git_repo or not status.remote_url:
            return {"ok": False, "remote_url": "", "latency_ms": 0,
                    "message": "未配置 origin 远端，无法检测 SSH 连接"}
        t0 = int(time.time() * 1000)
        try:
            r = self._run(["ls-remote", "--heads", self.remote_name],
                          network=True, timeout=12)
        except GitServiceError as exc:
            return {"ok": False, "remote_url": status.remote_url,
                    "latency_ms": int(time.time() * 1000) - t0,
                    "message": f"网络连接超时或命令执行失败: {exc}"}
        latency = int(time.time() * 1000) - t0
        if r.returncode == 0:
            return {"ok": True, "remote_url": status.remote_url,
                    "latency_ms": latency, "message": "SSH 连接正常"}
        err = (r.stderr or r.stdout or "").strip()
        if "Permission denied" in err or "permission" in err.lower():
            msg = "SSH 密钥未加载或权限被拒绝，请检查 ~/.ssh 密钥与 GitHub 部署密钥"
        elif "timed out" in err.lower() or "Could not resolve" in err:
            msg = "网络连接超时或域名解析失败"
        else:
            msg = f"SSH 连接失败: {err[:200]}"
        return {"ok": False, "remote_url": status.remote_url,
                "latency_ms": latency, "message": msg}

    # ---- 3.3 Diff 预览 ----

    def get_diff(self, file_path: str | None = None) -> dict[str, Any]:
        status = self.get_status()
        if not status.is_git_repo:
            raise GitServiceError("不是有效的 Git 仓库")

        if file_path is None:
            stat = self._run(["diff", "--stat"])
            untracked = [c.path for c in status.changes if c.category == "untracked"]
            return {
                "file_path": None,
                "stat": stat.stdout if stat.returncode == 0 else "",
                "untracked": untracked,
                "changes": [{"path": c.path, "status": c.status_code,
                             "category": c.category} for c in status.changes],
            }

        rel = self._validate_file_path(file_path)
        target = self.blog_repo / rel
        is_tracked = any(c.path == rel and c.category != "untracked"
                         for c in status.changes)
        if is_tracked:
            r = self._run(["diff", "--", rel])
            content = r.stdout if r.returncode == 0 else r.stderr
        elif target.exists():
            if target.suffix.lower() in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
                kb = round(target.stat().st_size / 1024, 1)
                content = f"[Binary image file: {kb} KB]"
            else:
                lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
                content = "\n".join(lines[:300])
                if len(lines) > 300:
                    content += f"\n... (已截断，共 {len(lines)} 行)"
        else:
            r = self._run(["diff", "--", rel])
            content = r.stdout if r.returncode == 0 else "(文件不存在或无变更)"

        lines = content.splitlines()
        truncated = len(lines) > 500
        return {"file_path": rel, "content": "\n".join(lines[:500]),
                "truncated": truncated, "total_lines": len(lines)}

    # ---- 3.4 一键提交与推送 ----

    def commit_and_push(
        self,
        message: str,
        push: bool = True,
        pull_rebase_first: bool = False,
        progress_cb: Callable[[dict], None] | None = None,
        task_id: str | None = None,
        cancel_event=None,
    ) -> dict[str, Any]:
        started = time.time()
        branch = ""
        commit_hash = ""
        status_value = "SUCCESS"
        error_msg = None
        remote_url = ""
        files_changed = 0
        pushed = False

        def emit(pct: int, stage: str, msg: str, level: str = "INFO") -> None:
            if progress_cb:
                progress_cb(stage=stage, percent=pct, message=msg, level=level)

        def cancelled() -> bool:
            return bool(cancel_event and cancel_event.is_set())

        try:
            self._validate_repo()
            if not message or not message.strip():
                raise GitServiceError("提交信息不能为空")
            emit(10, "precheck", "前置检查：仓库合法，提交信息有效")

            st = self.get_status()
            branch = st.branch or "main"
            remote_url = st.remote_url
            files_changed = len(st.changes)

            if not st.has_changes and st.ahead_count == 0:
                emit(100, "done", "无待提交变更")
                return {"no_changes": True, "branch": branch,
                        "commit_hash": "", "pushed": False, "files_changed": 0}

            # 可选 pull --rebase
            if pull_rebase_first and st.behind_count > 0 and remote_url:
                emit(25, "pull", f"远端领先 {st.behind_count} 条，执行 pull --rebase")
                pr = self._run(["pull", "--rebase", self.remote_name, branch],
                               network=True, timeout=60)
                if pr.returncode != 0:
                    self._run(["rebase", "--abort"])
                    raise GitServiceError(
                        f"拉取变基发生冲突，已自动 abort 恢复现场: {pr.stderr.strip()[:200]}"
                    )
            if cancelled():
                raise GitServiceError("任务已取消")

            # git add -A
            if st.has_changes:
                emit(45, "stage", f"暂存 {files_changed} 个变更文件")
                add_r = self._run(["add", "-A"])
                if add_r.returncode != 0:
                    raise GitServiceError(f"git add 失败: {add_r.stderr.strip()[:200]}")

            # git commit
            staged = self._run(["diff", "--cached", "--quiet"])
            has_staged = staged.returncode != 0
            if has_staged:
                emit(65, "commit", "本地提交中")
                cr = self._run(["commit", "-m", message])
                if cr.returncode != 0:
                    raise GitServiceError(f"git commit 失败: {cr.stderr.strip()[:200]}")
                hr = self._run(["rev-parse", "HEAD"])
                commit_hash = hr.stdout.strip() if hr.returncode == 0 else ""

            # git push
            if push and remote_url:
                if cancelled():
                    raise GitServiceError("任务已取消")
                emit(85, "push", f"SSH 免密推送至 {self.remote_name}/{branch}")
                push_r = self._run(["push", self.remote_name, branch],
                                   network=True, timeout=60)
                if (push_r.stderr or "").strip():
                    emit(95, "push", (push_r.stderr or "").strip()[:300])
                if push_r.returncode != 0:
                    raise GitServiceError(f"git push 失败: {push_r.stderr.strip()[:200]}")
                pushed = True

            emit(100, "done", "提交与推送完成")
            return {
                "no_changes": False, "branch": branch, "commit_hash": commit_hash,
                "pushed": pushed, "files_changed": files_changed,
                "message": message,
            }
        except Exception as exc:
            status_value = "FAILED"
            error_msg = str(exc)
            emit(100, "error", error_msg, level="ERROR")
            raise
        finally:
            duration_ms = int((time.time() - started) * 1000)
            if self.repo is not None:
                try:
                    self.repo.add_git_push_log(
                        task_id=task_id, trigger_source=self.trigger_source,
                        branch=branch, remote_url=remote_url,
                        commit_hash=commit_hash, commit_message=message,
                        files_changed=files_changed, pushed=pushed,
                        status=status_value, duration_ms=duration_ms,
                        error_message=error_msg,
                    )
                except Exception as log_exc:
                    logger.warning(f"[git_service] 审计落库失败: {log_exc}")

    # ---- 3.5 提交历史 ----

    def get_commits(self, limit: int = 30, offset: int = 0,
                    search: str | None = None) -> list[dict[str, Any]]:
        # 先确定未推送 hash 集合（upstream..HEAD）
        unpushed: set[str] = set()
        up = self._run(["rev-list", "@{upstream}..HEAD"])
        if up.returncode == 0:
            unpushed = {h.strip() for h in up.stdout.splitlines() if h.strip()}

        fmt = "%H%x1f%h%x1f%s%x1f%an%x1f%aI"
        args = ["log", f"--format={fmt}", "--shortstat",
                f"--skip={offset}", f"--max-count={limit}"]
        if search:
            args.append(f"--grep={search}")
        r = self._run(args)
        if r.returncode != 0 or not r.stdout.strip():
            return []

        commits: list[dict[str, Any]] = []
        cur: dict[str, Any] | None = None
        for raw in r.stdout.splitlines():
            line = raw.rstrip()
            if "\x1f" in line:
                if cur:
                    commits.append(cur)
                parts = line.split("\x1f")
                if len(parts) >= 5:
                    full, short, msg, author, date_iso = parts[:5]
                    cur = {
                        "hash": full, "short_hash": short, "message": msg,
                        "author": author, "date_iso": date_iso,
                        "relative_time": self._relative_time(date_iso),
                        "files_changed": 0, "insertions": 0, "deletions": 0,
                        "is_pushed": full not in unpushed,
                    }
            elif cur and line.strip():
                m = re.search(r"(\d+) files? changed", line)
                if m:
                    cur["files_changed"] = int(m.group(1))
                mi = re.search(r"(\d+) insertions?", line)
                if mi:
                    cur["insertions"] = int(mi.group(1))
                md = re.search(r"(\d+) deletions?", line)
                if md:
                    cur["deletions"] = int(md.group(1))
        if cur:
            commits.append(cur)
        return commits

    @staticmethod
    def _relative_time(date_iso: str) -> str:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(date_iso)
            from datetime import datetime as _dt
            delta = (_dt.now(dt.tzinfo) - dt).total_seconds()
            if delta < 60:
                return "刚刚"
            if delta < 3600:
                return f"{int(delta / 60)} 分钟前"
            if delta < 86400:
                return f"{int(delta / 3600)} 小时前"
            return f"{int(delta / 86400)} 天前"
        except Exception:
            return date_iso

    # ---- 3.6 单条提交详情 ----

    def get_commit_detail(self, commit_hash: str) -> dict[str, Any]:
        h = self._validate_commit_hash(commit_hash)
        fmt = "%H%x1f%h%x1f%s%x1f%an%x1f%aI"
        r = self._run(["show", "--name-status", f"--format={fmt}", h])
        if r.returncode != 0:
            raise GitServiceError(f"获取提交详情失败: {r.stderr.strip()[:200]}")

        lines = r.stdout.splitlines()
        meta: dict[str, Any] = {}
        files: list[dict[str, str]] = []
        in_files = False
        for line in lines:
            if "\x1f" in line and not in_files:
                parts = line.split("\x1f")
                if len(parts) >= 5:
                    meta = {"hash": parts[0], "short_hash": parts[1],
                            "message": parts[2], "author": parts[3],
                            "date_iso": parts[4]}
                    in_files = True
            elif in_files and line.strip():
                bits = line.split("\t")
                if len(bits) >= 2:
                    code = bits[0]
                    cat = self._category(code)
                    files.append({"status": code, "category": cat,
                                  "path": bits[-1]})
        meta["files"] = files
        return meta

    # ---- pull（冲突自动 abort） ----

    def pull_rebase(self) -> dict[str, Any]:
        st = self.get_status()
        if not st.remote_url:
            raise GitServiceError("未配置 origin 远端")
        r = self._run(["pull", "--rebase", self.remote_name, st.branch or "main"],
                      network=True, timeout=60)
        if r.returncode != 0:
            self._run(["rebase", "--abort"])
            raise GitServiceError(f"拉取变基冲突，已自动 abort: {r.stderr.strip()[:200]}")
        return {"ok": True, "branch": st.branch, "message": "远端更新已同步"}
