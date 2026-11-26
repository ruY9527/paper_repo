"""分析结果严格校验器（03 文档第 4 节）。

- 校验 staging/<date>/<paper_uid>.md 的 UTF-8 可读性、Frontmatter 必填字段、
  正文长度、paper_uid 一致性。
- 解析 PAPERFLOW_METRICS_JSON 注释块写入 paper_metrics（失败仅 WARNING）。
- 通过 -> STAGED；失败 -> 保持 QUEUED 并给出精确错误，严禁删 PDF。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from ..config import AppConfig
from ..db.models import PaperStatus, PaperTier
from ..db.repository import PaperRepository
from ..utils.logger import get_logger

logger = get_logger()

_REQUIRED_FIELDS = ("paper_uid", "title", "venue", "year", "tier", "tldr")
_METRICS_RE = re.compile(
    r"<!--\s*PAPERFLOW_METRICS_JSON\s*(.*?)\s*-->", re.DOTALL
)


@dataclass
class ValidationResult:
    paper_uid: str
    path: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    metrics: dict | None = None


def validate_md_file(
    md_path: str | Path,
    repo: PaperRepository,
    config: AppConfig,
    *,
    persist: bool = True,
) -> ValidationResult:
    """校验单个 staging Markdown 文件。

    persist=False 时不写库（供 dry-run 使用）。
    """
    md_path = Path(md_path)
    paper_uid = md_path.stem
    errors: list[str] = []

    # 1. 可读 UTF-8 且非空
    try:
        raw = md_path.read_text(encoding="utf-8")
    except Exception as exc:
        return ValidationResult(paper_uid, str(md_path), False, [f"文件不可读: {exc}"])
    if not raw.strip():
        return ValidationResult(paper_uid, str(md_path), False, ["文件为空"])

    # 2. Frontmatter 合法
    try:
        post = frontmatter.loads(raw)
    except Exception as exc:
        return ValidationResult(paper_uid, str(md_path), False, [f"Frontmatter 解析失败: {exc}"])

    meta = post.metadata
    for key in _REQUIRED_FIELDS:
        if key not in meta or meta[key] in (None, ""):
            errors.append(f"缺少 {key} 字段")

    fm_uid = str(meta.get("paper_uid", ""))
    if fm_uid and fm_uid != paper_uid:
        errors.append(f"Frontmatter paper_uid({fm_uid}) 与文件名({paper_uid}) 不一致")

    record = repo.get_paper(paper_uid)
    if record is None:
        errors.append(f"数据库中无此论文记录: {paper_uid}")
    elif fm_uid and fm_uid != record.paper_uid:
        errors.append(f"Frontmatter paper_uid 与数据库记录不一致")

    # 3. 正文长度（S 300 / A 120）
    body = post.content
    min_chars = (
        config.storage.min_valid_md_chars
        if meta.get("tier", "S") == PaperTier.S.value
        else 120
    )
    if len(body.strip()) < min_chars:
        errors.append(f"正文过短: {len(body.strip())} < {min_chars}")

    # 4. 解析 metrics JSON（失败仅 WARNING）
    metrics: dict | None = None
    match = _METRICS_RE.search(raw)
    if match:
        try:
            metrics = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            logger.warning(f"[validator] {paper_uid} metrics JSON 解析失败（不阻断）: {exc}")

    if metrics and record and persist:
        repo.upsert_metrics(paper_uid, metrics)

    ok = len(errors) == 0
    if ok and record and persist:
        # 回写 frontmatter 的 code_url：AI 在精读里发现的代码链接可能比采集阶段更全，
        # 不回写会导致首页「带开源代码」统计恒为 0（DB 里 code_url 为空）。
        code_url = str(meta.get("code_url", "") or "").strip()
        no_code_markers = ("未列出代码", "无代码", "没有代码", "not listed", "no code")
        if (code_url and code_url.lower() not in ("n/a", "none", "null", "-")
                and not any(m in code_url for m in no_code_markers)):
            # 去掉「（arXiv 页面未列出代码链接）」这类说明性后缀，只保留 URL
            url_match = __import__("re").search(r"https?://[^\s（）()]+", code_url)
            clean_code = url_match.group(0).rstrip("）)") if url_match else ""
            if clean_code and clean_code != record.code_url:
                repo.update_fields(paper_uid, code_url=clean_code)
        repo.update_status(
            paper_uid, PaperStatus.STAGED, md_staging_path=str(md_path)
        )
        logger.info(f"[validator] {paper_uid} 校验通过 -> STAGED")
    elif not ok:
        logger.warning(f"[validator] {paper_uid} 校验失败: {errors}")

    return ValidationResult(paper_uid, str(md_path), ok, errors, metrics)


def validate_all_staged(
    config: AppConfig,
    repo: PaperRepository,
    target_date: str | None = None,
    *,
    persist: bool = True,
    only_unpublished: bool = False,
) -> list[ValidationResult]:
    """扫描 staging 下所有 <paper_uid>.md 并校验，可跳过已发布旧文件。"""
    staging_root = config.workspace_path / "staging"
    if not staging_root.exists():
        return []
    results: list[ValidationResult] = []
    for md_path in sorted(staging_root.glob("**/*.md")):
        if md_path.name == "TODAY_DIGEST.md":
            continue
        if target_date and target_date not in md_path.parts:
            continue
        if only_unpublished:
            paper = repo.get_paper(md_path.stem)
            if paper and paper.status in (
                PaperStatus.PUBLISHED.value, PaperStatus.CLEANED.value,
            ):
                continue
        results.append(validate_md_file(md_path, repo, config, persist=persist))
    return results
