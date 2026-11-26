"""兴趣打分、学者/机构雷达、代码嗅探与 S/A/B 分级（02 文档第 4 节）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from ..config import AppConfig
from ..db.models import PaperRecord, PaperTier
from ..utils.logger import get_logger

logger = get_logger()

_CODE_RE = re.compile(r"https?://(?:www\.)?(?:github\.com|gitlab\.com|huggingface\.co)/[^\s)\]}'\",]+", re.IGNORECASE)
_PROJECT_RE = re.compile(r"https?://[^\s)\]}'\",]*\.github\.io/[^\s)\]}'\",]*", re.IGNORECASE)
_GITHUB_REPO_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)", re.IGNORECASE)
_ORAL_RE = re.compile(r"oral|spotlight|best paper|highlight", re.IGNORECASE)


@dataclass
class ScoreResult:
    score: float
    tier: str
    is_radar_hit: int
    matched_tags: list[str]
    code_url: str
    project_url: str
    code_stars: int | None


def sniff_code_links(text: str) -> tuple[str, str]:
    """从文本中提取代码仓库链接与项目主页链接。"""
    code_match = _CODE_RE.search(text)
    code_url = code_match.group(0).rstrip(".,;") if code_match else ""
    project_match = _PROJECT_RE.search(text)
    project_url = project_match.group(0) if project_match else ""
    return code_url, project_url


def query_github_stars(code_url: str, timeout: float = 5.0) -> int | None:
    """查询 GitHub star 数；403 限流或任何异常静默返回 None。"""
    match = _GITHUB_REPO_RE.search(code_url)
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    repo = re.sub(r"\.git$", "", repo)
    try:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "PaperFlow2026/1.0"}
        token = __import__("os").environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=headers, timeout=timeout, trust_env=False,
        )
        if resp.status_code != 200:
            return None
        return int(resp.json().get("stargazers_count", 0))
    except Exception:
        return None


def score_paper(
    paper: PaperRecord,
    config: AppConfig,
    *,
    force_tier_s: bool = False,
    query_stars: bool = False,
    exempt_exclude_keywords: bool = False,
) -> ScoreResult:
    """对一篇论文计算总分并返回分级结果（不直接改库）。"""
    profile = config.interest_profile
    text = f"{paper.title} {paper.abstract} {paper.comment}".lower()
    score = 0.0
    matched: list[str] = []
    radar = 0

    # 1. 高优先级关键词（累计上限 60）
    hit_high = [kw for kw in profile.high_priority_keywords if kw.lower() in text]
    high_points = min(len(hit_high) * 30, 60)
    score += high_points
    matched.extend(hit_high)

    # 2. 中优先级关键词（累计上限 30）
    hit_med = [kw for kw in profile.medium_priority_keywords if kw.lower() in text]
    med_points = min(len(hit_med) * 15, 30)
    score += med_points
    matched.extend(hit_med)

    # 3. 排除词（-50/词）
    hit_excl = [] if exempt_exclude_keywords else [
        kw for kw in profile.exclude_keywords if kw.lower() in text
    ]
    score -= len(hit_excl) * 50
    matched.extend(f"-{kw}" for kw in hit_excl)

    # 4. 学者/机构雷达
    authors_lower = [a.lower() for a in json.loads(paper.authors_json or "[]")]
    affils_lower = [a.lower() for a in json.loads(paper.affiliations_json or "[]")]
    for author in profile.tracked_authors:
        if any(author.lower() in a or a in author.lower() for a in authors_lower if a):
            score += 25
            radar = 1
            matched.append(f"author:{author}")
    for affil in profile.tracked_affiliations:
        if any(affil.lower() in a or a in affil.lower() for a in affils_lower if a):
            score += 15
            radar = 1
            matched.append(f"affil:{affil}")

    # 5. 代码嗅探
    code_url, project_url = sniff_code_links(f"{paper.abstract} {paper.comment}")
    if not code_url and paper.code_url:
        code_url = paper.code_url
    if not project_url and paper.project_url:
        project_url = paper.project_url
    code_stars = None
    if code_url:
        score += profile.bonuses.has_code
        if query_stars:
            code_stars = query_github_stars(code_url)

    # 6. Oral / Spotlight
    if _ORAL_RE.search(paper.comment or ""):
        score += profile.bonuses.oral_or_spotlight
        radar = 1
        matched.append("oral/spotlight")

    score = max(0.0, score)  # 负分截断为 0

    # 分级
    if force_tier_s:
        tier = PaperTier.S.value
    elif score >= profile.thresholds.tier_s:
        tier = PaperTier.S.value
    elif score >= profile.thresholds.tier_a:
        tier = PaperTier.A.value
    else:
        tier = PaperTier.B.value

    return ScoreResult(
        score=score, tier=tier, is_radar_hit=radar,
        matched_tags=matched, code_url=code_url,
        project_url=project_url, code_stars=code_stars,
    )


def score_and_persist(
    paper: PaperRecord,
    config: AppConfig,
    repository,
    *,
    force_tier_s: bool = False,
    query_stars: bool = False,
    exempt_exclude_keywords: bool = False,
) -> ScoreResult:
    """计算打分并写回数据库；B 级直接置 SKIPPED，其余置 SCORED。"""
    result = score_paper(
        paper, config, force_tier_s=force_tier_s, query_stars=query_stars,
        exempt_exclude_keywords=exempt_exclude_keywords,
    )
    from ..db.models import PaperStatus

    new_status = PaperStatus.SKIPPED.value if result.tier == PaperTier.B.value else PaperStatus.SCORED.value
    repository.update_fields(
        paper.paper_uid,
        score=result.score,
        tier=result.tier,
        is_radar_hit=result.is_radar_hit,
        matched_tags_json=json.dumps(result.matched_tags, ensure_ascii=False),
        code_url=result.code_url,
        project_url=result.project_url,
        code_stars=result.code_stars,
    )
    repository.update_status(paper.paper_uid, new_status)
    logger.info(f"[scorer] {paper.paper_uid} score={result.score:.0f} tier={result.tier} -> {new_status}")
    return result
