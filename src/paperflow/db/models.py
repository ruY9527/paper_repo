"""数据类与状态枚举。

与 SQLite 表结构一一对应，供 repository / 流水线各模块共享。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from ..utils.timeutil import now_iso


class PaperStatus(str, Enum):
    """论文生命周期状态机（见 01 文档第 3 节）。"""

    FETCHED = "FETCHED"
    SCORED = "SCORED"
    RESCUED_ARXIV = "RESCUED_ARXIV"
    DOWNLOADED = "DOWNLOADED"
    QUEUED = "QUEUED"
    ANALYZED = "ANALYZED"
    STAGED = "STAGED"
    PUBLISHED = "PUBLISHED"
    CLEANED = "CLEANED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


PENDING_ANALYSIS_STATUSES = (
    PaperStatus.QUEUED.value,
    PaperStatus.DOWNLOADED.value,
)


class PaperTier(str, Enum):
    S = "S"
    A = "A"
    B = "B"


class WatermarkStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


def utc_now_iso() -> str:
    """ISO 8601 当前时间戳（GMT+8，+08:00）。

    保留函数名以兼容历史 import；语义已统一为 GMT+8，不再返回 UTC(Z)。
    """
    return now_iso()


@dataclass
class PaperRecord:
    """papers 表的一条记录（内存表示）。"""

    paper_uid: str
    title: str
    normalized_title: str
    authors_json: str
    venue: str
    pub_year: int
    fetch_date: str
    source: str
    affiliations_json: str = "[]"
    pub_date: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    openreview_id: str | None = None
    abstract: str = ""
    comment: str = ""
    paper_url: str = ""
    pdf_url: str = ""
    code_url: str = ""
    code_stars: int | None = None
    project_url: str = ""
    score: float = 0.0
    tier: str = "B"
    is_radar_hit: int = 0
    matched_tags_json: str = "[]"
    status: str = PaperStatus.FETCHED.value
    pdf_local_path: str | None = None
    downloaded_at: str | None = None
    pdf_deleted: int = 0
    md_staging_path: str | None = None
    md_blog_path: str | None = None
    retry_count: int = 0
    last_error: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    # Phase 10：来源模式与方向标签（旧库经 ALTER TABLE 平滑补列，默认值兼容）
    discovery_mode: str = "venue"  # venue | topic | manual
    topic_tags_json: str = "[]"
    # Phase 13：访问类型
    access_type: str = "open"  # open | paywall_blocked | manual_uploaded


@dataclass
class WatermarkRecord:
    """job_watermarks 表的一条记录。"""

    source_name: str
    venue: str
    last_success_date: str
    last_run_at: str
    last_status: str
    last_error: str | None = None


@dataclass
class PaperMetricsRecord:
    """paper_metrics 表的一条记录。"""

    paper_uid: str
    task: str = ""
    backbone: str = ""
    datasets_json: str = "[]"
    sota_summary: str = ""
    tldr: str = ""
    innovation_tags_json: str = "[]"
    user_rating: str = ""
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class RunLogRecord:
    """run_logs 表的一条记录。"""

    command: str
    started_at: str
    status: str
    finished_at: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    fetched_count: int = 0
    new_count: int = 0
    tier_s_count: int = 0
    tier_a_count: int = 0
    cleaned_count: int = 0
    failed_count: int = 0
    message: str = ""
    id: int | None = None
