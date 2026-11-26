"""配置加载与 Pydantic 严格校验。

所有路径统一使用 pathlib.Path，配置中的相对路径相对项目根目录（本文件上溯两级）
解析。文件读写显式指定 UTF-8，满足 Windows 编码兼容红线。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# 项目根目录：src/paperflow/config.py -> src/paperflow -> src -> 项目根
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

# 9 大目标 Venue（期刊 3 + 会议 6）。内部统一用大写 key 做比较。
ALL_VENUES: tuple[str, ...] = (
    "TPAMI", "TIP", "IJCV", "CVPR", "ECCV", "ICCV", "NEURIPS", "ICLR", "AAAI",
)

# 规范展示名（用于报告/前端展示时恢复混合大小写）
VENUE_DISPLAY_NAMES: dict[str, str] = {
    "TPAMI": "TPAMI", "TIP": "TIP", "IJCV": "IJCV", "CVPR": "CVPR",
    "ECCV": "ECCV", "ICCV": "ICCV", "NEURIPS": "NeurIPS", "ICLR": "ICLR",
    "AAAI": "AAAI",
}


class StrictModel(BaseModel):
    """禁止未知字段，确保配置拼写错误能被立即发现。"""

    model_config = ConfigDict(extra="forbid")


class ProjectConfig(StrictModel):
    target_year: int = Field(default=2026, ge=2000, le=2100)
    workspace_dir: str = "./workspace"
    paper_repo_dir: str = "./paper_repo"
    timezone: str = "Asia/Shanghai"


class VenueConfig(StrictModel):
    """期刊与会议共用的 venue 定义；可选字段区分二者。"""

    full_name: str
    issns: list[str] = Field(default_factory=list)
    arxiv_patterns: list[str] = Field(default_factory=list)
    openalex_source_ids: list[str] = Field(default_factory=list)
    openreview_venue_id: str | None = None


class VenuesConfig(StrictModel):
    journals: dict[str, VenueConfig]
    conferences: dict[str, VenueConfig]

    @field_validator("journals", "conferences")
    @classmethod
    def _upper_keys(cls, value: dict[str, VenueConfig]) -> dict[str, VenueConfig]:
        return {k.upper(): v for k, v in value.items()}

    def all(self) -> dict[str, VenueConfig]:
        """返回全部 venue（期刊 + 会议）的合并字典。"""
        merged: dict[str, VenueConfig] = {}
        merged.update(self.journals)
        merged.update(self.conferences)
        return merged

    def names(self) -> list[str]:
        return list(self.all().keys())


class ArxivSourceConfig(StrictModel):
    enabled: bool = True
    categories: list[str] = Field(default_factory=list)
    rate_limit_seconds: float = Field(default=3.1, gt=0)
    max_results_per_slice: int = Field(default=500, gt=0)


class OpenAlexSourceConfig(StrictModel):
    enabled: bool = True
    mailto: str = "your_email@example.com"
    rate_limit_seconds: float = Field(default=0.5, gt=0)


class OpenReviewSourceConfig(StrictModel):
    enabled: bool = True
    rate_limit_seconds: float = Field(default=1.0, gt=0)


class SourcesConfig(StrictModel):
    arxiv: ArxivSourceConfig
    openalex: OpenAlexSourceConfig
    openreview: OpenReviewSourceConfig


class BackfillConfig(StrictModel):
    default_lookback_days: int = Field(default=3, ge=0)
    max_slice_days: int = Field(default=5, ge=1)
    max_auto_catchup_days: int = Field(default=60, ge=1)


class BonusesConfig(StrictModel):
    has_code: int = 15
    oral_or_spotlight: int = 20


class ThresholdsConfig(StrictModel):
    tier_s: int = 50
    tier_a: int = 25

    @field_validator("tier_s", "tier_a")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("阈值不能为负数")
        return value


class InterestProfileConfig(StrictModel):
    high_priority_keywords: list[str] = Field(default_factory=list)
    medium_priority_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    tracked_authors: list[str] = Field(default_factory=list)
    tracked_affiliations: list[str] = Field(default_factory=list)
    bonuses: BonusesConfig = Field(default_factory=BonusesConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)


class StorageConfig(StrictModel):
    max_pdf_size_mb: int = Field(default=50, gt=0)
    extract_figures: bool = True
    max_figures_per_paper: int = Field(default=2, ge=0)
    figure_max_width_px: int = Field(default=1200, gt=0)
    figure_webp_quality: int = Field(default=80, ge=1, le=100)
    auto_clean_after_publish: bool = True
    min_valid_md_chars: int = Field(default=300, ge=0)


class PublishConfig(StrictModel):
    auto_git_commit: bool = True
    auto_git_push: bool = False
    commit_message_template: str = "docs: publish {count} papers ({date})"
    # Phase 9：在线博客地址（用于 Web Git 中心一键打开）与远端名称
    blog_site_url: str = "https://ruY9527.github.io/paper_repo/"
    git_remote_name: str = "origin"
    # Phase 12：发布前 MkDocs 严格构建门禁与本地预览端口
    require_mkdocs_strict_build: bool = True
    preview_port: int = Field(default=8001, ge=1, le=65535)


class NotificationsConfig(StrictModel):
    windows_toast: bool = True
    webhook_type: str = "none"
    webhook_url_env: str = "PAPERFLOW_WEBHOOK_URL"


# ---- Phase 10：研究方向精准检索 ----

class RecencyPolicyConfig(StrictModel):
    """两年时效策略；primary_year 缺省时动态取 project.target_year。"""

    primary_year: int | None = None  # None => 运行时用 project.target_year
    allow_fallback_prev_year: bool = True
    primary_year_bonus: float = 25.0
    strict_min_year_offset: int = 1  # 只允许 [target_year-1, target_year]

    @field_validator("strict_min_year_offset")
    @classmethod
    def _check_offset(cls, value: int) -> int:
        if value < 0:
            raise ValueError("strict_min_year_offset 不能为负")
        return value


class TopicSubscriptionConfig(StrictModel):
    name: str
    slug: str
    query: str
    enabled: bool = True
    limit: int = Field(default=20, gt=0)
    only_primary_year: bool = False
    top_venues_only: bool = False


class TopicSearchConfig(StrictModel):
    enabled: bool = True
    recency_policy: RecencyPolicyConfig = Field(default_factory=RecencyPolicyConfig)
    default_limit_per_topic: int = Field(default=20, gt=0)
    auto_promote_top_n_to_s: int = Field(default=3, ge=0)
    synonym_dict: dict[str, list[str]] = Field(default_factory=dict)
    subscriptions: list[TopicSubscriptionConfig] = Field(default_factory=list)


# ---- Phase 11：AI 论文自动解析引擎 ----

class ClaudeCliConfig(StrictModel):
    enabled: bool = True
    executable: str = "claude"
    args: list[str] = Field(default_factory=lambda: ["-p", "--output-format", "text"])
    model: str = ""
    extra_env: dict[str, str] = Field(default_factory=dict)


class HarnessWebConfig(StrictModel):
    enabled: bool = True
    web_url: str = "http://127.0.0.1:3080"
    auto_watch_staging: bool = True


class OpenAIApiConfig(StrictModel):
    enabled: bool = False
    base_url: str = "http://127.0.0.1:11434/v1"
    api_key_env: str = "PAPERFLOW_LLM_API_KEY"
    model: str = "kimi-k3"


class AnalyzerConfig(StrictModel):
    default_backend: str = "claude_cli"
    max_input_chars: int = Field(default=60000, gt=0)
    max_retries: int = Field(default=2, ge=0)
    timeout_seconds: int = Field(default=240, gt=0)
    cooldown_seconds: float = Field(default=3.0, ge=0)
    auto_validate_after_analysis: bool = True
    claude_cli: ClaudeCliConfig = Field(default_factory=ClaudeCliConfig)
    harness_web: HarnessWebConfig = Field(default_factory=HarnessWebConfig)
    openai_api: OpenAIApiConfig = Field(default_factory=OpenAIApiConfig)

    @field_validator("default_backend")
    @classmethod
    def _check_backend(cls, value: str) -> str:
        if value not in ("claude_cli", "harness_web", "openai_api"):
            raise ValueError("default_backend 必须是 claude_cli / harness_web / openai_api")
        return value


# ---- Phase 13：受限出版商过滤与手动补传 ----

class PaywallDomainConfig(StrictModel):
    domain: str
    publisher: str = ""
    note: str = ""


class DownloadPolicyConfig(StrictModel):
    enable_paywall_filter: bool = True
    auto_try_arxiv_rescue: bool = True
    auto_classify_html_403_as_paywall: bool = True
    manual_inbox_dir: str = "./workspace/inbox_pdfs"
    paywall_domains: list[PaywallDomainConfig] = Field(default_factory=list)


# ---- Phase 14：网站收录中心与博客导航页 ----

class SitesConfig(StrictModel):
    enabled: bool = True
    blog_layout: str = "cards"  # cards | table
    hide_dead_links_in_blog: bool = False
    fetch_timeout_seconds: float = 10.0
    health_check_timeout_seconds: float = 8.0
    health_check_concurrency: int = 5

    @field_validator("blog_layout")
    @classmethod
    def _check_layout(cls, value: str) -> str:
        if value not in ("cards", "table"):
            raise ValueError("blog_layout 必须是 cards 或 table")
        return value


class AppConfig(StrictModel):
    project: ProjectConfig
    venues: VenuesConfig
    sources: SourcesConfig
    backfill: BackfillConfig
    interest_profile: InterestProfileConfig
    storage: StorageConfig
    publish: PublishConfig
    notifications: NotificationsConfig
    # Phase 10 / 11：旧配置不含这些节点时由默认值构造，保证向后兼容
    topic_search: TopicSearchConfig = Field(default_factory=TopicSearchConfig)
    analyzer: AnalyzerConfig = Field(default_factory=AnalyzerConfig)
    # Phase 13：受限出版商过滤与手动补传
    download_policy: DownloadPolicyConfig = Field(default_factory=DownloadPolicyConfig)
    # Phase 14：网站收录中心与博客导航页
    sites: SitesConfig = Field(default_factory=SitesConfig)

    @field_validator("venues")
    @classmethod
    def _check_nine_venues(cls, value: VenuesConfig) -> VenuesConfig:
        names = set(value.names())
        missing = set(ALL_VENUES) - names
        if missing:
            raise ValueError(f"配置缺少目标 Venue: {sorted(missing)}")
        extra = names - set(ALL_VENUES)
        if extra:
            raise ValueError(f"配置包含未知 Venue: {sorted(extra)}")
        return value

    # ---- 便捷路径属性 ----
    @property
    def workspace_path(self) -> Path:
        return _resolve_path(self.project.workspace_dir)

    @property
    def paper_repo_path(self) -> Path:
        return _resolve_path(self.project.paper_repo_dir)

    @property
    def db_path(self) -> Path:
        return self.workspace_path / "state.db"

    @property
    def primary_year(self) -> int:
        """Phase 10 优先年份：缺省动态取 target_year。"""
        return self.topic_search.recency_policy.primary_year or self.target_year

    @property
    def fallback_year(self) -> int:
        """Phase 10 兜底年份（优先年份 - 1）。"""
        return self.primary_year - 1

    @property
    def min_allowed_year(self) -> int:
        """Phase 10 硬过滤底线：小于该年份一律丢弃。"""
        return self.primary_year - max(0, self.topic_search.recency_policy.strict_min_year_offset)

    @property
    def inbox_pdfs_path(self) -> Path:
        """Phase 13 批量补传 PDF 收件箱目录。"""
        return _resolve_path(self.download_policy.manual_inbox_dir)

    @property
    def target_year(self) -> int:
        return self.project.target_year


def _resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (PROJECT_ROOT / path)


def load_config(path: str | Path | None = None) -> AppConfig:
    """从 YAML 加载并校验配置。

    path 缺省时使用 ``config/config.yaml``；文件不存在时抛 FileNotFoundError，
    调用方应提示用户先复制 ``config.example.yaml``。
    """
    cfg_path = Path(path) if path is not None else PROJECT_ROOT / "config" / "config.yaml"
    cfg_path = _resolve_path(str(cfg_path)) if not cfg_path.is_absolute() else cfg_path
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {cfg_path}。请先复制 config/config.example.yaml 为 config/config.yaml"
        )
    data: dict[str, Any] = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)


def load_example_config() -> AppConfig:
    """加载模板配置（测试与初始化使用）。"""
    return load_config(PROJECT_ROOT / "config" / "config.example.yaml")
