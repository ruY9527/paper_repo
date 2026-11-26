"""博客文章视图（Phase 16）：以 paper_repo 博客仓库文件为真相源。

发布记录不由本地 DB 单方面决定，而以博客仓库 docs/papers/ 下实际存在的文章
为准；同时结合 git 状态标注「未提交 / 已提交未推送 / 已推送」。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..db.repository import PaperRepository
from ..utils.timeutil import fmt_display, LOCAL_TZ
from ..utils.figure_links import normalize_blog_image_paths
from datetime import datetime as _dt


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def _frontmatter(text: str) -> dict[str, str]:
    m = _FM_RE.match(text or "")
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _git_state(repo_dir: Path) -> dict[str, str]:
    """返回 {relative_path: state}，state ∈ untracked/modified/committed/pushed。"""
    states: dict[str, str] = {}
    try:
        env = {**__import__("os").environ, "GIT_TERMINAL_PROMPT": "0"}
        # 未提交（含未跟踪与修改）
        r = subprocess.run(["git", "-c", "core.quotepath=false", "status", "--porcelain"],
                           cwd=str(repo_dir), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20, shell=False, env=env)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if len(line) < 4:
                    continue
                code, path = line[:2], line[3:].strip().strip('"')
                if path:
                    states[path] = "modified" if "?" not in code else "untracked"
        # 已提交但未推送
        u = subprocess.run(["git", "-c", "core.quotepath=false", "log", "origin/main..HEAD",
                            "--name-only", "--pretty=format:"],
                           cwd=str(repo_dir), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20, shell=False, env=env)
        if u.returncode == 0:
            for line in u.stdout.splitlines():
                p = line.strip()
                if p and p not in states:
                    states[p] = "committed"
    except Exception:
        pass
    return states


def list_blog_articles(config: AppConfig, repo: PaperRepository,
                       q: str | None = None, limit: int | None = None,
                       offset: int = 0) -> dict[str, Any]:
    """扫描博客仓库文章，返回清单（以博客文件为主）。

    q/limit/offset 可选：Web 列表传分页；内部 read_blog_article 不传则取全量。
    """
    docs = config.paper_repo_path / "docs" / "papers"
    git_states = _git_state(config.paper_repo_path)
    items: list[dict[str, Any]] = []
    if docs.exists():
        for md in sorted(docs.rglob("*.md")):
            rel = str(md.relative_to(config.paper_repo_path)).replace("\\", "/")
            text = md.read_text(encoding="utf-8", errors="replace")
            fm = _frontmatter(text)
            uid = md.stem
            record = repo.get_paper(uid)
            items.append({
                "paper_uid": uid,
                "title": fm.get("title") or (record.title if record else uid),
                "venue": fm.get("venue") or (record.venue if record else ""),
                "year": fm.get("year") or (record.pub_year if record else ""),
                "path": rel,
                "chars": len(text),
                "git_state": git_states.get(rel, "pushed"),
                "in_ledger": record is not None,
                "db_status": record.status if record else "",
                "mtime": fmt_display(_dt.fromtimestamp(md.stat().st_mtime, tz=LOCAL_TZ).isoformat()),
            })
    if q:
        needle = q.lower()
        items = [x for x in items
                 if needle in x["title"].lower() or needle in x["paper_uid"].lower()
                 or needle in x["venue"].lower()]
    total = len(items)
    page_items = items[offset:offset + limit] if limit else items
    return {
        "items": page_items,
        "total": total,
        "limit": limit, "offset": offset,
        "by_state": {
            s: sum(1 for x in items if x["git_state"] == s)
            for s in ("pushed", "committed", "modified", "untracked")
        },
    }


def read_blog_article(config: AppConfig, rel_path: str) -> str | None:
    """读取博客文章原文（限制在 docs/papers 内，防越界）。"""
    base = (config.paper_repo_path / "docs" / "papers").resolve()
    target = (base / rel_path).resolve()
    if not target.is_relative_to(base) or not target.exists() or target.suffix.lower() != ".md":
        return None
    return target.read_text(encoding="utf-8", errors="replace")


def publish_one(
    config: AppConfig,
    repo: PaperRepository,
    paper_uid: str,
    *,
    staging_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """唯一单篇发布内核：复制文章与资源，并同步账本状态。

    待审工作台、AI 解析中心和批量发布均复用本函数；dry_run 只计算目标路径。
    """
    import shutil
    from pathlib import Path
    from ..db.models import PaperStatus

    record = repo.get_paper(paper_uid)
    if record is None:
        return {"ok": False, "error": "论文不存在"}
    # 幂等：已发布且博客文件存在时直接返回，避免重复点击造成覆盖/误判
    existing_rel = getattr(record, "md_blog_path", "") or ""
    if record.status in (PaperStatus.PUBLISHED.value, PaperStatus.CLEANED.value) and existing_rel:
        existing_file = config.paper_repo_path / "docs" / existing_rel
        if existing_file.exists():
            return {"ok": True, "paper_uid": paper_uid, "blog_path": str(existing_file),
                    "repo_rel": str(existing_rel).replace("\\", "/"), "already_published": True}
    staging_root = config.workspace_path / "staging"
    if staging_path is not None:
        mds = [Path(staging_path)]
    else:
        mds = sorted(staging_root.glob(f"*/{paper_uid}.md"), reverse=True)
    if not mds or not mds[0].is_file() or mds[0].stat().st_size == 0:
        return {"ok": False, "error": "解析结果不存在或为空"}
    md = mds[0]
    year = config.target_year
    rel = Path("papers") / str(year) / record.venue / f"{paper_uid}.md"
    dest = config.paper_repo_path / "docs" / rel
    rel_str = str(rel).replace("\\", "/")  # 博客路径统一用正斜杠
    if dry_run:
        return {"ok": True, "paper_uid": paper_uid, "blog_path": str(dest),
                "repo_rel": rel_str, "dry_run": True}
    dest.parent.mkdir(parents=True, exist_ok=True)
    from .ai_notice import append_ai_notice
    from .back_link import append_back_link
    from ..pipeline.math_fix import fix_bare_math
    content = normalize_blog_image_paths(md.read_text(encoding="utf-8"), paper_uid)
    dest.write_text(append_back_link(append_ai_notice(fix_bare_math(content))), encoding="utf-8")
    src_assets = staging_root / "assets" / paper_uid
    if src_assets.exists():
        dst_assets = config.paper_repo_path / "docs" / "assets" / paper_uid
        if dst_assets.exists():
            shutil.rmtree(dst_assets)
        shutil.copytree(src_assets, dst_assets)
    repo.update_status(paper_uid, PaperStatus.PUBLISHED, md_blog_path=rel_str)
    return {"ok": True, "paper_uid": paper_uid, "blog_path": str(dest),
            "repo_rel": rel_str}
