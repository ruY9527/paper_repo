"""SQLite 永久账本：建表、CRUD、水位线、事务与 upsert 合并策略。

红线：
- 所有文件读写显式 UTF-8（本模块仅经 sqlite3 操作二进制数据库文件）。
- 路径统一 pathlib.Path。
- 建表幂等；upsert 只补全空字段，不覆盖生命周期字段。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import AppConfig
from ..pipeline.dedup import generate_paper_uid, normalize_title
from .models import (
    PaperRecord,
    PaperStatus,
    RunStatus,
    WatermarkRecord,
    WatermarkStatus,
    utc_now_iso,
)

# ---- 建表 DDL（与 01 文档第 2 节完全一致）----

DDL_PAPERS = """
CREATE TABLE IF NOT EXISTS papers (
    paper_uid        TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    authors_json     TEXT NOT NULL,
    affiliations_json TEXT DEFAULT '[]',
    venue            TEXT NOT NULL,
    pub_year         INTEGER NOT NULL,
    pub_date         TEXT,
    fetch_date       TEXT NOT NULL,
    source           TEXT NOT NULL,
    doi              TEXT,
    arxiv_id         TEXT,
    openreview_id    TEXT,
    abstract         TEXT DEFAULT '',
    comment          TEXT DEFAULT '',
    paper_url        TEXT DEFAULT '',
    pdf_url          TEXT DEFAULT '',
    code_url         TEXT DEFAULT '',
    code_stars       INTEGER DEFAULT NULL,
    project_url      TEXT DEFAULT '',

    score            REAL DEFAULT 0.0,
    tier             TEXT DEFAULT 'B',
    is_radar_hit     INTEGER DEFAULT 0,
    matched_tags_json TEXT DEFAULT '[]',

    status           TEXT NOT NULL DEFAULT 'FETCHED',
    pdf_local_path   TEXT DEFAULT NULL,
    downloaded_at    TEXT DEFAULT NULL,
    pdf_deleted      INTEGER DEFAULT 0,
    md_staging_path  TEXT DEFAULT NULL,
    md_blog_path     TEXT DEFAULT NULL,

    retry_count      INTEGER DEFAULT 0,
    last_error       TEXT DEFAULT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    discovery_mode   TEXT NOT NULL DEFAULT 'venue',
    topic_tags_json  TEXT NOT NULL DEFAULT '[]',
    access_type      TEXT NOT NULL DEFAULT 'open'
);
"""

DDL_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_papers_venue_year ON papers(venue, pub_year);
CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_fetch_date ON papers(fetch_date);
CREATE INDEX IF NOT EXISTS idx_papers_normalized_title ON papers(normalized_title);
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi) WHERE doi IS NOT NULL AND doi != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id) WHERE arxiv_id IS NOT NULL AND arxiv_id != '';
"""

DDL_WATERMARKS = """
CREATE TABLE IF NOT EXISTS job_watermarks (
    source_name       TEXT NOT NULL,
    venue             TEXT NOT NULL,
    last_success_date TEXT NOT NULL,
    last_run_at       TEXT NOT NULL,
    last_status       TEXT NOT NULL,
    last_error        TEXT DEFAULT NULL,
    PRIMARY KEY (source_name, venue)
);
"""

DDL_METRICS = """
CREATE TABLE IF NOT EXISTS paper_metrics (
    paper_uid         TEXT PRIMARY KEY REFERENCES papers(paper_uid) ON DELETE CASCADE,
    task              TEXT DEFAULT '',
    backbone          TEXT DEFAULT '',
    datasets_json     TEXT DEFAULT '[]',
    sota_summary      TEXT DEFAULT '',
    tldr              TEXT DEFAULT '',
    innovation_tags_json TEXT DEFAULT '[]',
    user_rating       TEXT DEFAULT '',
    updated_at        TEXT NOT NULL
);
"""

DDL_RUN_LOGS = """
CREATE TABLE IF NOT EXISTS run_logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    command           TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    date_from         TEXT,
    date_to           TEXT,
    fetched_count     INTEGER DEFAULT 0,
    new_count         INTEGER DEFAULT 0,
    tier_s_count      INTEGER DEFAULT 0,
    tier_a_count      INTEGER DEFAULT 0,
    cleaned_count     INTEGER DEFAULT 0,
    failed_count      INTEGER DEFAULT 0,
    status            TEXT NOT NULL,
    message           TEXT DEFAULT ''
);
"""

# Phase 9：Git 推送审计表（06 文档第 2 节）
DDL_GIT_PUSH_LOGS = """
CREATE TABLE IF NOT EXISTS git_push_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT,
    trigger_source  TEXT NOT NULL,
    branch          TEXT NOT NULL,
    remote_url      TEXT DEFAULT '',
    commit_hash     TEXT DEFAULT '',
    commit_message  TEXT DEFAULT '',
    files_changed   INTEGER DEFAULT 0,
    pushed          INTEGER DEFAULT 0,
    status          TEXT NOT NULL,
    duration_ms     INTEGER DEFAULT 0,
    error_message   TEXT DEFAULT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_git_push_logs_created ON git_push_logs(created_at DESC);
"""

# Phase 10：方向检索历史记录表
DDL_TOPIC_SEARCH_RUNS = """
CREATE TABLE IF NOT EXISTS topic_search_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id            TEXT,
    topic_name         TEXT NOT NULL,
    raw_query          TEXT NOT NULL,
    expanded_query     TEXT NOT NULL,
    primary_year       INTEGER NOT NULL,
    fallback_year      INTEGER NOT NULL,
    primary_count      INTEGER DEFAULT 0,
    fallback_count     INTEGER DEFAULT 0,
    filtered_old_count INTEGER DEFAULT 0,
    new_inserted_count INTEGER DEFAULT 0,
    status             TEXT NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topic_runs_created ON topic_search_runs(created_at DESC);
"""

# Phase 11：AI 解析审计表
DDL_ANALYSIS_RUNS = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT,
    paper_uid       TEXT NOT NULL REFERENCES papers(paper_uid) ON DELETE CASCADE,
    backend         TEXT NOT NULL,
    model_name      TEXT DEFAULT '',
    attempt         INTEGER DEFAULT 1,
    status          TEXT NOT NULL,
    stage           TEXT DEFAULT '',
    duration_ms     INTEGER DEFAULT 0,
    output_chars    INTEGER DEFAULT 0,
    error_message   TEXT DEFAULT NULL,
    error_detail    TEXT DEFAULT NULL,       -- JSON：error_type/stderr/http_status/response_snippet 等
    errors_json     TEXT DEFAULT NULL,       -- JSON：校验错误列表
    started_at      TEXT DEFAULT NULL,
    finished_at     TEXT DEFAULT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_paper ON analysis_runs(paper_uid, created_at DESC);
"""

# analysis_runs 旧库平滑迁移列（解析进度/断点/错误详单所需，幂等无损）
_ANALYSIS_MIGRATION_COLUMNS = {
    "stage": "TEXT DEFAULT ''",
    "started_at": "TEXT DEFAULT NULL",
    "finished_at": "TEXT DEFAULT NULL",
    "error_detail": "TEXT DEFAULT NULL",
    "errors_json": "TEXT DEFAULT NULL",
}

# Phase 14：网站收录中心（分类表 + 收录网站表）
DDL_SITE_CATEGORIES = """
CREATE TABLE IF NOT EXISTS site_categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE,
    icon        TEXT DEFAULT '🔗',
    description TEXT DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 100,
    created_at  TEXT NOT NULL
);
"""

DDL_COLLECTED_SITES = """
CREATE TABLE IF NOT EXISTS collected_sites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,
    normalized_url  TEXT NOT NULL UNIQUE,
    domain          TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT DEFAULT '',
    personal_note   TEXT DEFAULT '',
    category_id     INTEGER NOT NULL REFERENCES site_categories(id),
    tags_json       TEXT NOT NULL DEFAULT '[]',
    favicon_url     TEXT DEFAULT '',
    rating          INTEGER DEFAULT 0,
    is_pinned       INTEGER NOT NULL DEFAULT 0,
    is_public       INTEGER NOT NULL DEFAULT 1,
    health_status   TEXT NOT NULL DEFAULT 'UNKNOWN',
    http_status     INTEGER DEFAULT NULL,
    last_checked_at TEXT DEFAULT NULL,
    visit_count     INTEGER DEFAULT 0,        -- 打开次数（使用频率）
    last_visited_at TEXT DEFAULT NULL,        -- 最近打开时间
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sites_category ON collected_sites(category_id);
CREATE INDEX IF NOT EXISTS idx_sites_public_pinned ON collected_sites(is_public, is_pinned);
CREATE INDEX IF NOT EXISTS idx_sites_health ON collected_sites(health_status);
"""

# 默认科研/开发分类（id 稳定，sort_order 越小越靠前）
# collected_sites 旧库平滑迁移列（书签使用统计）
_SITE_MIGRATION_COLUMNS = {
    "visit_count": "INTEGER DEFAULT 0",
    "last_visited_at": "TEXT DEFAULT NULL",
}

DEFAULT_SITE_CATEGORIES = [
    ("AI 与大模型", "ai-llm", "🤖", 10),
    ("论文与学术", "academic-papers", "📚", 20),
    ("数据集与基准", "datasets-benchmarks", "📊", 30),
    ("开源项目与框架", "open-source", "🛠️", 40),
    ("效率与科研工具", "productivity-tools", "⚡", 50),
    ("优质技术博客", "tech-blogs", "✍️", 60),
]

# Phase 13：受限论文独立账本表
DDL_PAYWALL_PAPERS = """
CREATE TABLE IF NOT EXISTS paywall_papers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_uid           TEXT NOT NULL UNIQUE REFERENCES papers(paper_uid) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    venue               TEXT NOT NULL,
    pub_year            INTEGER NOT NULL,
    tier                TEXT NOT NULL DEFAULT 'S',
    publisher           TEXT NOT NULL,
    domain              TEXT NOT NULL,
    landing_url         TEXT DEFAULT '',
    blocked_pdf_url     TEXT DEFAULT '',
    doi                 TEXT DEFAULT '',
    block_reason        TEXT NOT NULL,
    oa_rescue_status    TEXT NOT NULL DEFAULT 'NOT_TRIED',
    manual_status       TEXT NOT NULL DEFAULT 'PENDING_MANUAL',
    note                TEXT DEFAULT '',
    detected_at         TEXT NOT NULL,
    resolved_at         TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_paywall_manual_status ON paywall_papers(manual_status);
CREATE INDEX IF NOT EXISTS idx_paywall_publisher ON paywall_papers(publisher);
CREATE INDEX IF NOT EXISTS idx_paywall_venue_year ON paywall_papers(venue, pub_year);
"""

ALL_DDL = (
    DDL_PAPERS, DDL_INDEXES, DDL_WATERMARKS, DDL_METRICS,
    DDL_RUN_LOGS, DDL_GIT_PUSH_LOGS, DDL_TOPIC_SEARCH_RUNS, DDL_ANALYSIS_RUNS,
    DDL_PAYWALL_PAPERS, DDL_SITE_CATEGORIES, DDL_COLLECTED_SITES,
)

# 建表 DDL（不含索引）——先建表/补列，最后再建索引，避免旧库缺列导致索引创建失败
_TABLE_DDL = (
    DDL_PAPERS, DDL_WATERMARKS, DDL_METRICS,
    DDL_RUN_LOGS, DDL_GIT_PUSH_LOGS, DDL_TOPIC_SEARCH_RUNS, DDL_ANALYSIS_RUNS,
    DDL_PAYWALL_PAPERS, DDL_SITE_CATEGORIES, DDL_COLLECTED_SITES,
)
_INDEX_DDL = (DDL_INDEXES,)

# 旧库平滑迁移白名单：papers 表所有可能缺失的列（列 -> DDL 片段）。
# 含 Phase 10 新增列，也含历史演进列，确保任意旧库都能无损升级。
_PAPER_MIGRATION_COLUMNS = {
    "affiliations_json": "TEXT DEFAULT '[]'",
    "pub_date": "TEXT",
    "doi": "TEXT",
    "arxiv_id": "TEXT",
    "openreview_id": "TEXT",
    "abstract": "TEXT DEFAULT ''",
    "comment": "TEXT DEFAULT ''",
    "paper_url": "TEXT DEFAULT ''",
    "pdf_url": "TEXT DEFAULT ''",
    "code_url": "TEXT DEFAULT ''",
    "code_stars": "INTEGER DEFAULT NULL",
    "project_url": "TEXT DEFAULT ''",
    "score": "REAL DEFAULT 0.0",
    "tier": "TEXT DEFAULT 'B'",
    "is_radar_hit": "INTEGER DEFAULT 0",
    "matched_tags_json": "TEXT DEFAULT '[]'",
    "pdf_local_path": "TEXT DEFAULT NULL",
    "downloaded_at": "TEXT DEFAULT NULL",
    "pdf_deleted": "INTEGER DEFAULT 0",
    "md_staging_path": "TEXT DEFAULT NULL",
    "md_blog_path": "TEXT DEFAULT NULL",
    "retry_count": "INTEGER DEFAULT 0",
    "last_error": "TEXT DEFAULT NULL",
    # Phase 10 新增
    "discovery_mode": "TEXT NOT NULL DEFAULT 'venue'",
    "topic_tags_json": "TEXT NOT NULL DEFAULT '[]'",
    # Phase 13 新增
    "access_type": "TEXT NOT NULL DEFAULT 'open'",
}

# upsert 时视为“可补全”的字段：仅在现有值为空时写入
_ENRICH_FIELDS = (
    "doi", "arxiv_id", "openreview_id", "pub_date", "abstract", "comment",
    "paper_url", "pdf_url", "code_url", "project_url", "affiliations_json",
)


class PaperRepository:
    """SQLite 账本仓储，所有状态变更集中于此。"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def from_config(cls, config: AppConfig) -> "PaperRepository":
        return cls(config.db_path)

    # ---- 连接与初始化 ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        """幂等建表 + 旧库无损迁移。

        顺序：先建表 -> PRAGMA 检查并 ALTER 补齐 papers 缺失列 -> 最后建索引。
        这样即便旧库缺列（会导致 CREATE INDEX 失败）也能平滑升级，绝不清空数据。
        """
        conn = self._connect()
        try:
            # 1) 建表（IF NOT EXISTS，旧库跳过）
            conn.executescript("\n".join(_TABLE_DDL))
            conn.commit()
            # 2) 旧库平滑迁移：只补缺失列，不动任何历史记录
            self._migrate_paper_columns(conn)
            self._migrate_analysis_columns(conn)
            self._migrate_site_columns(conn)
            # 3) 建索引（此时所有引用列一定存在）
            conn.executescript("\n".join(_INDEX_DDL))
            conn.commit()
            # 4) Phase 14：幂等预置 6 个默认网站分类（仅在空表时写入）
            self._seed_site_categories(conn)
        finally:
            conn.close()

    def _migrate_paper_columns(self, conn: sqlite3.Connection) -> None:
        """按白名单对 papers 表补齐缺失列（含 Phase 10 新增列），幂等无损。"""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
        added: list[str] = []
        for column, ddl_type in _PAPER_MIGRATION_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE papers ADD COLUMN {column} {ddl_type}")
                added.append(column)
        if added:
            conn.commit()

    def _migrate_site_columns(self, conn: sqlite3.Connection) -> None:
        """按白名单对 collected_sites 补齐缺失列（使用统计），幂等无损。"""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(collected_sites)").fetchall()}
        added: list[str] = []
        for column, ddl_type in _SITE_MIGRATION_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE collected_sites ADD COLUMN {column} {ddl_type}")
                added.append(column)
        if added:
            conn.commit()

    def _seed_site_categories(self, conn: sqlite3.Connection) -> None:
        """仅在 site_categories 为空时预置 6 个默认分类（幂等，不覆盖用户自定义）。"""
        n = conn.execute("SELECT COUNT(*) FROM site_categories").fetchone()[0]
        if n:
            return
        now = utc_now_iso()
        conn.executemany(
            "INSERT INTO site_categories (name, slug, icon, description, sort_order, created_at) "
            "VALUES (?, ?, ?, '', ?, ?)",
            [(name, slug, icon, order, now) for name, slug, icon, order in DEFAULT_SITE_CATEGORIES],
        )
        conn.commit()

    def _migrate_analysis_columns(self, conn: sqlite3.Connection) -> None:
        """按白名单对 analysis_runs 补齐缺失列（解析进度/断点），幂等无损。"""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(analysis_runs)").fetchall()}
        added: list[str] = []
        for column, ddl_type in _ANALYSIS_MIGRATION_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE analysis_runs ADD COLUMN {column} {ddl_type}")
                added.append(column)
        if added:
            conn.commit()


    # ---- papers CRUD ----

    @staticmethod
    def _paper_to_row(p: PaperRecord) -> dict[str, Any]:
        return {
            "paper_uid": p.paper_uid,
            "title": p.title,
            "normalized_title": p.normalized_title,
            "authors_json": p.authors_json,
            "affiliations_json": p.affiliations_json,
            "venue": p.venue,
            "pub_year": p.pub_year,
            "pub_date": p.pub_date,
            "fetch_date": p.fetch_date,
            "source": p.source,
            "doi": p.doi,
            "arxiv_id": p.arxiv_id,
            "openreview_id": p.openreview_id,
            "abstract": p.abstract,
            "comment": p.comment,
            "paper_url": p.paper_url,
            "pdf_url": p.pdf_url,
            "code_url": p.code_url,
            "code_stars": p.code_stars,
            "project_url": p.project_url,
            "score": p.score,
            "tier": p.tier,
            "is_radar_hit": p.is_radar_hit,
            "matched_tags_json": p.matched_tags_json,
            "status": p.status,
            "pdf_local_path": p.pdf_local_path,
            "pdf_deleted": p.pdf_deleted,
            "md_staging_path": p.md_staging_path,
            "md_blog_path": p.md_blog_path,
            "retry_count": p.retry_count,
            "last_error": p.last_error,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
            "discovery_mode": p.discovery_mode,
            "topic_tags_json": p.topic_tags_json,
            "access_type": p.access_type,
        }

    @staticmethod
    def _row_to_paper(row: sqlite3.Row) -> PaperRecord:
        return PaperRecord(**{key: row[key] for key in row.keys()})

    def get_paper(self, paper_uid: str) -> PaperRecord | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM papers WHERE paper_uid = ?", (paper_uid,)).fetchone()
            return self._row_to_paper(row) if row else None
        finally:
            conn.close()

    def _find_existing(self, conn: sqlite3.Connection, paper: PaperRecord) -> str | None:
        """按 paper_uid -> DOI -> arxiv_id -> normalized_title 依次查库，返回已存在 UID。

        paper_uid 是最终去重键（由 DOI/arXivID/标题哈希生成），必须最先判，
        否则同一论文标题轻微变化会让 UID 相同但 normalized_title 不同，
        导致误判为新记录并触发 UNIQUE 冲突。
        """
        if paper.paper_uid:
            row = conn.execute(
                "SELECT paper_uid FROM papers WHERE paper_uid = ?", (paper.paper_uid,)
            ).fetchone()
            if row:
                return row["paper_uid"]
        if paper.doi:
            row = conn.execute("SELECT paper_uid FROM papers WHERE doi = ?", (paper.doi,)).fetchone()
            if row:
                return row["paper_uid"]
        if paper.arxiv_id:
            row = conn.execute("SELECT paper_uid FROM papers WHERE arxiv_id = ?", (paper.arxiv_id,)).fetchone()
            if row:
                return row["paper_uid"]
        row = conn.execute(
            "SELECT paper_uid FROM papers WHERE normalized_title = ?", (paper.normalized_title,)
        ).fetchone()
        return row["paper_uid"] if row else None

    def upsert_paper(self, paper: PaperRecord) -> tuple[PaperRecord, bool]:
        """插入或补全一条论文记录。

        返回 (最终记录, is_new)。已存在时不覆盖 status / md_blog_path /
        pdf_deleted 等生命周期字段，仅补全空字段；补全时记录 enriched 日志语义
        （通过 updated_at 变更体现）。
        """
        with self._transaction() as conn:
            existing_uid = self._find_existing(conn, paper)
            if existing_uid is None:
                row_data = self._paper_to_row(paper)
                cols = ", ".join(row_data.keys())
                placeholders = ", ".join("?" for _ in row_data)
                conn.execute(
                    f"INSERT INTO papers ({cols}) VALUES ({placeholders})",
                    tuple(row_data.values()),
                )
                final_uid = paper.paper_uid
                is_new = True
            else:
                # 补全空字段，绝不触碰生命周期
                updates: dict[str, Any] = {}
                existing = conn.execute(
                    "SELECT * FROM papers WHERE paper_uid = ?", (existing_uid,)
                ).fetchone()
                for field in _ENRICH_FIELDS:
                    incoming = getattr(paper, field)
                    current = existing[field]
                    is_empty = current is None or current == "" or current == "[]"
                    if incoming and (incoming != "[]") and is_empty:
                        updates[field] = incoming
                if updates:
                    updates["updated_at"] = utc_now_iso()
                    set_clause = ", ".join(f"{k} = ?" for k in updates)
                    conn.execute(
                        f"UPDATE papers SET {set_clause} WHERE paper_uid = ?",
                        (*updates.values(), existing_uid),
                    )
                final_uid = existing_uid
                is_new = False

            row = conn.execute("SELECT * FROM papers WHERE paper_uid = ?", (final_uid,)).fetchone()
            return self._row_to_paper(row), is_new

    def insert_paper_from_fields(self, **kwargs: Any) -> tuple[PaperRecord, bool]:
        """便捷入口：由原始字段构造 PaperRecord 并执行 upsert。"""
        if "paper_uid" not in kwargs or not kwargs["paper_uid"]:
            kwargs["paper_uid"] = generate_paper_uid(
                doi=kwargs.get("doi"),
                arxiv_id=kwargs.get("arxiv_id"),
                openreview_id=kwargs.get("openreview_id"),
                title=kwargs.get("title", ""),
            )
        if "normalized_title" not in kwargs or not kwargs["normalized_title"]:
            kwargs["normalized_title"] = normalize_title(kwargs.get("title", ""))
        valid_keys = set(PaperRecord.__dataclass_fields__.keys())
        clean = {k: v for k, v in kwargs.items() if k in valid_keys}
        return self.upsert_paper(PaperRecord(**clean))

    def update_status(
        self,
        paper_uid: str,
        status: str | PaperStatus,
        **extra: Any,
    ) -> None:
        """统一状态变更入口，自动刷新 updated_at。"""
        status_value = status.value if isinstance(status, PaperStatus) else status
        allowed = {s.value for s in PaperStatus}
        if status_value not in allowed:
            raise ValueError(f"非法状态: {status_value}")
        now = utc_now_iso()
        updates: dict[str, Any] = {"status": status_value, "updated_at": now}
        # 首次进入 DOWNLOADED 时记录下载时间（幂等：已有值不覆盖）
        if status_value == PaperStatus.DOWNLOADED.value:
            cur = self._connect()
            try:
                row = cur.execute(
                    "SELECT downloaded_at FROM papers WHERE paper_uid=?", (paper_uid,)
                ).fetchone()
            finally:
                cur.close()
            if row and not row["downloaded_at"]:
                updates["downloaded_at"] = now
        for key, value in extra.items():
            if key in PaperRecord.__dataclass_fields__:
                updates[key] = value
        with self._transaction() as conn:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE papers SET {set_clause} WHERE paper_uid = ?",
                (*updates.values(), paper_uid),
            )

    def update_fields(self, paper_uid: str, **fields: Any) -> None:
        """更新任意合法字段并刷新 updated_at（用于打分、下载路径等）。"""
        valid = set(PaperRecord.__dataclass_fields__.keys()) - {"paper_uid", "created_at"}
        updates = {k: v for k, v in fields.items() if k in valid}
        if not updates:
            return
        updates["updated_at"] = utc_now_iso()
        with self._transaction() as conn:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE papers SET {set_clause} WHERE paper_uid = ?",
                (*updates.values(), paper_uid),
            )

    def get_papers_by_status(self, *statuses: str) -> list[PaperRecord]:
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM papers WHERE status IN ({placeholders})", tuple(statuses)
            ).fetchall()
            return [self._row_to_paper(r) for r in rows]
        finally:
            conn.close()

    def get_all_papers(self) -> list[PaperRecord]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM papers ORDER BY fetch_date DESC, pub_date DESC").fetchall()
            return [self._row_to_paper(r) for r in rows]
        finally:
            conn.close()

    def count_papers(self) -> int:
        conn = self._connect()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0])
        finally:
            conn.close()

    # ---- 水位线 ----

    def get_watermark(self, source_name: str, venue: str) -> WatermarkRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM job_watermarks WHERE source_name = ? AND venue = ?",
                (source_name, venue),
            ).fetchone()
            return WatermarkRecord(**{k: row[k] for k in row.keys()}) if row else None
        finally:
            conn.close()

    def set_watermark(
        self,
        source_name: str,
        venue: str,
        last_success_date: str,
        last_status: str | WatermarkStatus = WatermarkStatus.SUCCESS,
        last_error: str | None = None,
    ) -> None:
        status_value = last_status.value if isinstance(last_status, WatermarkStatus) else last_status
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO job_watermarks
                    (source_name, venue, last_success_date, last_run_at, last_status, last_error)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_name, venue) DO UPDATE SET
                    last_success_date = excluded.last_success_date,
                    last_run_at = excluded.last_run_at,
                    last_status = excluded.last_status,
                    last_error = excluded.last_error
                """,
                (source_name, venue, last_success_date, utc_now_iso(), status_value, last_error),
            )

    def get_all_watermarks(self) -> list[WatermarkRecord]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM job_watermarks").fetchall()
            return [WatermarkRecord(**{k: row[k] for k in row.keys()}) for row in rows]
        finally:
            conn.close()

    # ---- paper_metrics ----

    @staticmethod
    def _metrics_scalar(value: Any, *, as_json: bool = False) -> str:
        """把模型输出的任意 metrics 字段归一化为可绑定的标量字符串。

        AI 生成的 metrics 常把 task/backbone/sota_summary 写成嵌套 dict/list，
        SQLite 无法直接绑定；这里统一序列化，避免一个字段类型异常阻断整个发布。
        """
        if value is None:
            return "[]" if as_json else ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def upsert_metrics(self, paper_uid: str, metrics: dict[str, Any]) -> None:
        now = utc_now_iso()
        if not isinstance(metrics, dict):
            metrics = {}
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO paper_metrics
                    (paper_uid, task, backbone, datasets_json, sota_summary, tldr,
                     innovation_tags_json, user_rating, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_uid) DO UPDATE SET
                    task = excluded.task, backbone = excluded.backbone,
                    datasets_json = excluded.datasets_json, sota_summary = excluded.sota_summary,
                    tldr = excluded.tldr, innovation_tags_json = excluded.innovation_tags_json,
                    updated_at = excluded.updated_at
                """,
                (
                    paper_uid,
                    self._metrics_scalar(metrics.get("task", "")),
                    self._metrics_scalar(metrics.get("backbone", "")),
                    self._metrics_scalar(metrics.get("datasets", []), as_json=True),
                    self._metrics_scalar(metrics.get("sota_summary", "")),
                    self._metrics_scalar(metrics.get("tldr", "")),
                    self._metrics_scalar(metrics.get("innovation_tags", []), as_json=True),
                    self._metrics_scalar(metrics.get("user_rating", "")),
                    now,
                ),
            )

    def get_metrics(self, paper_uid: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM paper_metrics WHERE paper_uid = ?", (paper_uid,)
            ).fetchone()
            if not row:
                return None
            return {
                "task": row["task"],
                "backbone": row["backbone"],
                "datasets": json.loads(row["datasets_json"] or "[]"),
                "sota_summary": row["sota_summary"],
                "tldr": row["tldr"],
                "innovation_tags": json.loads(row["innovation_tags_json"] or "[]"),
                "user_rating": row["user_rating"],
            }
        finally:
            conn.close()

    @staticmethod
    def _parse_metrics_list(raw: Any) -> list | str:
        """容错解析 metrics 的列表字段；兼容历史写入的纯文本脏数据。"""
        if raw is None or raw == "":
            return []
        if isinstance(raw, (list, dict)):
            return raw
        try:
            return json.loads(str(raw))
        except (json.JSONDecodeError, ValueError, TypeError):
            # 历史数据可能直接存了描述性文本：包成单元素列表，既保留原文又满足下游 join
            return [str(raw)]

    def get_all_metrics(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM paper_metrics").fetchall()
            return [
                {
                    "paper_uid": r["paper_uid"],
                    "task": r["task"],
                    "backbone": r["backbone"],
                    "datasets": self._parse_metrics_list(r["datasets_json"]),
                    "sota_summary": r["sota_summary"],
                    "tldr": r["tldr"],
                    "innovation_tags": self._parse_metrics_list(r["innovation_tags_json"]),
                    "user_rating": r["user_rating"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ---- run_logs ----

    def start_run(self, command: str, date_from: str | None = None, date_to: str | None = None) -> int:
        with self._transaction() as conn:
            cur = conn.execute(
                "INSERT INTO run_logs (command, started_at, status, date_from, date_to) VALUES (?, ?, ?, ?, ?)",
                (command, utc_now_iso(), RunStatus.RUNNING.value, date_from, date_to),
            )
            return int(cur.lastrowid)

    def finish_run(
        self,
        run_id: int,
        status: str | RunStatus = RunStatus.SUCCESS,
        **counts: Any,
    ) -> None:
        status_value = status.value if isinstance(status, RunStatus) else status
        allowed_counts = {
            "fetched_count", "new_count", "tier_s_count", "tier_a_count",
            "cleaned_count", "failed_count", "message",
        }
        fields: dict[str, Any] = {"finished_at": utc_now_iso(), "status": status_value}
        for key, value in counts.items():
            if key in allowed_counts:
                fields[key] = value
        with self._transaction() as conn:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE run_logs SET {set_clause} WHERE id = ?",
                (*fields.values(), run_id),
            )

    # ---- git_push_logs（Phase 9 推送审计）----

    def add_git_push_log(self, *, task_id: str | None = None,
                         trigger_source: str = "web", branch: str = "",
                         remote_url: str = "", commit_hash: str = "",
                         commit_message: str = "", files_changed: int = 0,
                         pushed: bool = False, status: str = "SUCCESS",
                         duration_ms: int = 0,
                         error_message: str | None = None) -> int:
        with self._transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO git_push_logs
                    (task_id, trigger_source, branch, remote_url, commit_hash,
                     commit_message, files_changed, pushed, status, duration_ms,
                     error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, trigger_source, branch, remote_url, commit_hash,
                 commit_message, files_changed, int(pushed), status, duration_ms,
                 error_message, utc_now_iso()),
            )
            return int(cur.lastrowid)

    def get_git_push_logs(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM git_push_logs ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_query_history(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """某方向/关键词的历史检索记录（用于「已检索过」提示与增量判断）。"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM topic_search_runs WHERE raw_query=? "
                "OR topic_name=? ORDER BY id DESC LIMIT ?",
                (query, query, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ---- topic_search_runs（Phase 10 方向检索历史）----

    def add_topic_search_run(self, *, topic_name: str, raw_query: str,
                             expanded_query: str, primary_year: int,
                             fallback_year: int, primary_count: int = 0,
                             fallback_count: int = 0, filtered_old_count: int = 0,
                             new_inserted_count: int = 0, status: str = "SUCCESS",
                             task_id: str | None = None) -> int:
        with self._transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO topic_search_runs
                    (task_id, topic_name, raw_query, expanded_query, primary_year,
                     fallback_year, primary_count, fallback_count, filtered_old_count,
                     new_inserted_count, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, topic_name, raw_query, expanded_query, primary_year,
                 fallback_year, primary_count, fallback_count, filtered_old_count,
                 new_inserted_count, status, utc_now_iso()),
            )
            return int(cur.lastrowid)

    def get_topic_search_runs(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM topic_search_runs ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def append_topic_tag(self, paper_uid: str, tag: str) -> None:
        """给已存在论文追加方向标签（去重），不触碰任何生命周期字段。"""
        row = self.get_paper(paper_uid)
        if row is None:
            return
        try:
            tags = json.loads(row.topic_tags_json or "[]")
        except json.JSONDecodeError:
            tags = []
        if tag not in tags:
            tags.append(tag)
            self.update_fields(paper_uid, topic_tags_json=json.dumps(tags, ensure_ascii=False))

    # ---- analysis_runs（Phase 11 AI 解析审计）----

    def add_analysis_run(self, *, paper_uid: str, backend: str,
                         status: str, task_id: str | None = None,
                         model_name: str = "", attempt: int = 1,
                         duration_ms: int = 0, output_chars: int = 0,
                         error_message: str | None = None,
                         stage: str = "", started_at: str | None = None,
                         finished_at: str | None = None,
                         error_detail: str | None = None,
                         errors_json: str | None = None) -> int:
        with self._transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO analysis_runs
                    (task_id, paper_uid, backend, model_name, attempt, status, stage,
                     duration_ms, output_chars, error_message, error_detail, errors_json,
                     started_at, finished_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, paper_uid, backend, model_name, attempt, status, stage,
                 duration_ms, output_chars, error_message, error_detail, errors_json,
                 started_at, finished_at, utc_now_iso()),
            )
            return int(cur.lastrowid)

    def start_analysis_run(self, *, paper_uid: str, backend: str,
                           task_id: str | None = None, model_name: str = "") -> int:
        """解析开始时立即落库一条 RUNNING 记录（断点痕迹）。"""
        return self.add_analysis_run(
            paper_uid=paper_uid, backend=backend, status="RUNNING", task_id=task_id,
            model_name=model_name, stage="starting", started_at=utc_now_iso(),
        )

    def delete_analysis_run(self, run_id: int) -> None:
        """删除实时 RUNNING 痕迹记录（终态写入前调用）。"""
        with self._transaction() as conn:
            conn.execute("DELETE FROM analysis_runs WHERE id = ?", (run_id,))

    def update_analysis_run(self, run_id: int, **fields: Any) -> None:
        """更新解析审计记录（终态、阶段、耗时、输出等）。"""
        allowed = {"status", "stage", "duration_ms", "output_chars", "error_message",
                   "model_name", "attempt", "finished_at", "error_detail", "errors_json"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        with self._transaction() as conn:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE analysis_runs SET {set_clause} WHERE id = ?",
                         (*updates.values(), run_id))

    def mark_interrupted_runs(self) -> int:
        """启动时把遗留的 RUNNING 记录标记为 INTERRUPTED（进程重启/崩溃断点）。"""
        with self._transaction() as conn:
            cur = conn.execute(
                "UPDATE analysis_runs SET status='INTERRUPTED', "
                "error_message='progress interrupted (process restart)', finished_at=? "
                "WHERE status='RUNNING'",
                (utc_now_iso(),),
            )
            return cur.rowcount

    def get_analysis_progress(self, limit: int = 100) -> dict[str, Any]:
        """解析进度视图：解析中/已完成/失败/中断 分组 + 最近记录。"""
        conn = self._connect()
        try:
            all_rows = [dict(r) for r in conn.execute(
                "SELECT * FROM analysis_runs ORDER BY id DESC"
            ).fetchall()]
            recent = all_rows[:limit]
            # 每篇论文最新一条审计；统计以论文为单位，与点击展开的明细条数一致
            latest: dict[str, dict] = {}
            for r in all_rows:
                if r["paper_uid"] not in latest:
                    latest[r["paper_uid"]] = dict(r)
            statuses = [v["status"] for v in latest.values()]
            from collections import Counter
            counts = dict(Counter(statuses))
            return {
                "counts": counts,
                "running": counts.get("RUNNING", 0),
                "success": counts.get("SUCCESS", 0),
                "failed": sum(counts.get(s, 0) for s in
                              ("FAILED", "ERROR", "TIMEOUT", "VALIDATION_FAILED", "CANCELLED")),
                "interrupted": counts.get("INTERRUPTED", 0),
                "recent": recent,
                "latest_by_paper": latest,
            }
        finally:
            conn.close()

    def get_analysis_category(self, category: str) -> list[dict[str, Any]]:
        """按统计分类返回每篇论文的最新解析记录（与进度胶囊数字对齐）。

        category: running | success | failed | interrupted
        """
        status_sets = {
            "running": {"RUNNING"},
            "success": {"SUCCESS"},
            "failed": {"FAILED", "ERROR", "TIMEOUT", "VALIDATION_FAILED", "CANCELLED"},
            "interrupted": {"INTERRUPTED"},
        }
        wanted = status_sets.get(category, set())
        if not wanted:
            return []
        conn = self._connect()
        try:
            # 每篇论文取最新一条审计，再按分类过滤（与 latest_by_paper 语义一致）
            rows = conn.execute("SELECT * FROM analysis_runs ORDER BY id DESC").fetchall()
            latest: dict[str, dict] = {}
            for r in rows:
                if r["paper_uid"] not in latest:
                    latest[r["paper_uid"]] = dict(r)
            return [v for v in latest.values() if v["status"] in wanted]
        finally:
            conn.close()

    def get_analysis_runs(self, limit: int = 50, offset: int = 0,
                          paper_uid: str | None = None) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if paper_uid:
                rows = conn.execute(
                    "SELECT * FROM analysis_runs WHERE paper_uid=? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (paper_uid, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM analysis_runs ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ---- sites（Phase 14 网站收录中心）----

    def get_site_categories(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM site_categories ORDER BY sort_order, id"
            ).fetchall()]
        finally:
            conn.close()

    def add_site_category(self, *, name: str, slug: str, icon: str = "🔗",
                          description: str = "", sort_order: int = 100) -> int:
        with self._transaction() as conn:
            cur = conn.execute(
                "INSERT INTO site_categories (name, slug, icon, description, sort_order, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, slug, icon, description, sort_order, utc_now_iso()),
            )
            return int(cur.lastrowid)

    def update_site_category(self, cat_id: int, **fields: Any) -> None:
        allowed = {"name", "slug", "icon", "description", "sort_order"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        with self._transaction() as conn:
            conn.execute(
                f"UPDATE site_categories SET {', '.join(k+'=?' for k in updates)} WHERE id=?",
                (*updates.values(), cat_id),
            )

    def delete_site_category(self, cat_id: int) -> None:
        with self._transaction() as conn:
            conn.execute("DELETE FROM site_categories WHERE id=?", (cat_id,))

    def add_site(self, *, url: str, normalized_url: str, domain: str, title: str,
                 category_id: int, description: str = "", personal_note: str = "",
                 tags: list[str] | None = None, favicon_url: str = "", rating: int = 0,
                 is_pinned: int = 0, is_public: int = 1) -> int:
        now = utc_now_iso()
        with self._transaction() as conn:
            cur = conn.execute(
                """INSERT INTO collected_sites
                   (url, normalized_url, domain, title, description, personal_note,
                    category_id, tags_json, favicon_url, rating, is_pinned, is_public,
                    health_status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'UNKNOWN', ?, ?)""",
                (url, normalized_url, domain, title, description, personal_note,
                 category_id, json.dumps(tags or [], ensure_ascii=False), favicon_url,
                 rating, is_pinned, is_public, now, now),
            )
            return int(cur.lastrowid)

    def get_site(self, site_id: int) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            r = conn.execute("SELECT * FROM collected_sites WHERE id=?", (site_id,)).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    def get_site_by_normalized_url(self, normalized_url: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            r = conn.execute(
                "SELECT * FROM collected_sites WHERE normalized_url=?", (normalized_url,)
            ).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    def get_sites(self, *, category_id: int | None = None, is_public: int | None = None,
                  is_pinned: int | None = None, health_status: str | None = None,
                  tag: str | None = None, q: str | None = None,
                  sort: str = "recent",
                  limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        clauses, args = [], []
        if category_id is not None:
            clauses.append("category_id=?"); args.append(category_id)
        if is_public is not None:
            clauses.append("is_public=?"); args.append(is_public)
        if is_pinned is not None:
            clauses.append("is_pinned=?"); args.append(is_pinned)
        if health_status:
            clauses.append("health_status=?"); args.append(health_status)
        if q:
            clauses.append("(title LIKE ? OR domain LIKE ? OR description LIKE ? OR personal_note LIKE ?)")
            args += [f"%{q}%"] * 4
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = {
            "recent": "is_pinned DESC, id DESC",
            "rating": "is_pinned DESC, rating DESC, id DESC",
            "visited": "is_pinned DESC, visit_count DESC, last_visited_at DESC",
            "title": "is_pinned DESC, title ASC",
        }.get(sort, "is_pinned DESC, id DESC")
        sql = f"SELECT * FROM collected_sites{where} ORDER BY {order} LIMIT ? OFFSET ?"
        args += [limit, offset]
        conn = self._connect()
        try:
            rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()
        if tag:
            rows = [r for r in rows if tag in json.loads(r.get("tags_json") or "[]")]
        return rows

    def count_sites(self, **filters) -> dict[str, Any]:
        rows = self.get_sites(limit=100000, **filters)
        return {
            "total": len(rows),
            "public": sum(1 for r in rows if r["is_public"] == 1),
            "private": sum(1 for r in rows if r["is_public"] == 0),
            "pinned": sum(1 for r in rows if r["is_pinned"] == 1),
            "dead": sum(1 for r in rows if r["health_status"] == "DEAD"),
        }

    def mark_site_visited(self, site_id: int) -> None:
        """记录一次打开：visit_count+1、last_visited_at=现在（GMT+8）。"""
        from ..utils.timeutil import now_iso
        with self._transaction() as conn:
            conn.execute(
                "UPDATE collected_sites SET visit_count=COALESCE(visit_count,0)+1, "
                "last_visited_at=?, updated_at=? WHERE id=?",
                (now_iso(), now_iso(), site_id),
            )

    def update_site(self, site_id: int, **fields: Any) -> None:
        allowed = {"url", "normalized_url", "domain", "title", "description", "personal_note",
                   "category_id", "tags_json", "favicon_url", "rating", "is_pinned", "is_public",
                   "health_status", "http_status", "last_checked_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = utc_now_iso()
        with self._transaction() as conn:
            conn.execute(
                f"UPDATE collected_sites SET {', '.join(k+'=?' for k in updates)} WHERE id=?",
                (*updates.values(), site_id),
            )

    def delete_site(self, site_id: int) -> None:
        with self._transaction() as conn:
            conn.execute("DELETE FROM collected_sites WHERE id=?", (site_id,))

    def update_site_health(self, site_id: int, *, status: str, http_status: int | None,
                           checked_at: str) -> None:
        self.update_site(site_id, health_status=status, http_status=http_status,
                         last_checked_at=checked_at)

    # ---- paywall_papers（Phase 13 受限论文独立账本）----

    def add_paywall_paper(self, *, paper_uid: str, title: str, venue: str,
                          pub_year: int, publisher: str, domain: str,
                          block_reason: str, landing_url: str = "",
                          blocked_pdf_url: str = "", doi: str = "",
                          tier: str = "S", oa_rescue_status: str = "NOT_TRIED",
                          manual_status: str = "PENDING_MANUAL", note: str = "") -> int:
        with self._transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO paywall_papers
                    (paper_uid, title, venue, pub_year, tier, publisher, domain,
                     landing_url, blocked_pdf_url, doi, block_reason, oa_rescue_status,
                     manual_status, note, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_uid) DO UPDATE SET
                    publisher=excluded.publisher, domain=excluded.domain,
                    block_reason=excluded.block_reason, blocked_pdf_url=excluded.blocked_pdf_url,
                    landing_url=excluded.landing_url, doi=excluded.doi
                """,
                (paper_uid, title, venue, pub_year, tier, publisher, domain,
                 landing_url, blocked_pdf_url, doi, block_reason, oa_rescue_status,
                 manual_status, note, utc_now_iso()),
            )
            return int(cur.lastrowid)

    def get_paywall_paper(self, paper_uid: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM paywall_papers WHERE paper_uid = ?", (paper_uid,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_paywall_papers(self, *, manual_status: str | None = None,
                           publisher: str | None = None, venue: str | None = None,
                           q: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
        conn = self._connect()
        try:
            sql = "SELECT * FROM paywall_papers WHERE 1=1"
            params: list = []
            if manual_status:
                sql += " AND manual_status = ?"; params.append(manual_status)
            if publisher:
                sql += " AND publisher = ?"; params.append(publisher)
            if venue:
                sql += " AND venue = ?"; params.append(venue)
            if q:
                sql += " AND (title LIKE ? OR paper_uid LIKE ? OR doi LIKE ?)"
                like = f"%{q}%"; params += [like, like, like]
            sql += " ORDER BY detected_at DESC LIMIT ? OFFSET ?"
            params += [limit, offset]
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def update_paywall_paper(self, paper_uid: str, **fields) -> None:
        allowed = {"manual_status", "oa_rescue_status", "note", "resolved_at",
                   "landing_url", "blocked_pdf_url", "publisher", "domain"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        if "manual_status" in updates and updates["manual_status"] in (
            "PDF_UPLOADED", "ABSTRACT_ONLY", "IGNORED"
        ):
            updates["resolved_at"] = utc_now_iso()
        with self._transaction() as conn:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE paywall_papers SET {set_clause} WHERE paper_uid = ?",
                (*updates.values(), paper_uid),
            )

    def count_paywall_by_status(self) -> dict[str, int]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT manual_status, COUNT(*) c FROM paywall_papers GROUP BY manual_status"
            ).fetchall()
            return {r["manual_status"]: r["c"] for r in rows}
        finally:
            conn.close()
