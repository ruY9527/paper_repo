# Phase 1：配置系统、SQLite 状态账本与去重规范

本文件定义 `config/config.yaml`、`src/paperflow/config.py`、`src/paperflow/db/models.py`、`src/paperflow/db/repository.py` 及 `src/paperflow/pipeline/dedup.py` 的精确规格。

---

## 1. 配置文件规范（`config/config.yaml`）

提供 `config/config.example.yaml` 作为模板，程序首次启动时若 `config/config.yaml` 不存在则提示复制模板。

```yaml
project:
  target_year: 2026
  workspace_dir: "./workspace"
  paper_repo_dir: "./paper_repo"
  timezone: "Asia/Shanghai"

# 9 大目标顶会与顶刊配置
venues:
  journals:
    TPAMI:
      full_name: "IEEE Transactions on Pattern Analysis and Machine Intelligence"
      issns: ["0162-8828", "1939-3539"]
      arxiv_patterns: ["\\bTPAMI\\b", "IEEE\\s+T-?PAMI", "Trans\\.?\\s+Pattern\\s+Anal"]
    TIP:
      full_name: "IEEE Transactions on Image Processing"
      issns: ["1057-7149", "1941-0042"]
      arxiv_patterns: ["\\bIEEE\\s+TIP\\b", "\\bT-?IP\\b", "Trans\\.?\\s+Image\\s+Process"]
    IJCV:
      full_name: "International Journal of Computer Vision"
      issns: ["0920-5691", "1573-1405"]
      arxiv_patterns: ["\\bIJCV\\b", "Int\\.?\\s+J\\.?\\s+Comput\\.?\\s+Vis"]

  conferences:
    CVPR:
      full_name: "IEEE/CVF Conference on Computer Vision and Pattern Recognition"
      arxiv_patterns: ["CVPR\\s*['’]?2026", "CVPR\\s*26\\b"]
      openalex_source_ids: []   # 运行时支持按名称模糊+年份匹配
    ECCV:
      full_name: "European Conference on Computer Vision"
      arxiv_patterns: ["ECCV\\s*['’]?2026", "ECCV\\s*26\\b"]
    ICCV:
      full_name: "IEEE/CVF International Conference on Computer Vision"
      # 注：ICCV 为奇数年会议，2026 年无正式 ICCV 2026，保留用于捕获延迟发表/Workshop/arXiv 标注
      arxiv_patterns: ["ICCV\\s*['’]?202[56]", "ICCV\\s*2[56]\\b"]
    NeurIPS:
      full_name: "Advances in Neural Information Processing Systems"
      arxiv_patterns: ["NeurIPS\\s*['’]?2026", "NIPS\\s*2026"]
      openreview_venue_id: "NeurIPS.cc/2026/Conference"
    ICLR:
      full_name: "International Conference on Learning Representations"
      arxiv_patterns: ["ICLR\\s*['’]?2026", "ICLR\\s*26\\b"]
      openreview_venue_id: "ICLR.cc/2026/Conference"
    AAAI:
      full_name: "AAAI Conference on Artificial Intelligence"
      arxiv_patterns: ["AAAI\\s*['’]?2026", "AAAI\\s*26\\b"]

# 数据源配置与限流
sources:
  arxiv:
    enabled: true
    categories: ["cs.CV", "cs.LG", "cs.AI", "cs.CL", "cs.RO"]
    rate_limit_seconds: 3.1
    max_results_per_slice: 500
  openalex:
    enabled: true
    mailto: "your_email@example.com"   # OpenAlex Polite Pool 推荐填写邮箱，速率更高
    rate_limit_seconds: 0.5
  openreview:
    enabled: true
    rate_limit_seconds: 1.0

# 补录策略
backfill:
  default_lookback_days: 3             # 首次运行（无水位线时）默认回溯天数
  max_slice_days: 5                    # 单次补录切片最大天数，防止 API 单次翻页溢出
  max_auto_catchup_days: 60            # 单次自动补录上限，超过则提示分段补录

# 个人科研兴趣画像（用于 S/A/B 自动分级）
interest_profile:
  high_priority_keywords:              # 命中 +30 分/词（可累加，上限 60）
    - "action recognition"
    - "video understanding"
    - "temporal action"
    - "multimodal"
    - "vision-language"
  medium_priority_keywords:            # 命中 +15 分/词
    - "diffusion"
    - "3d gaussian"
    - "world model"
    - "self-supervised"
    - "agent"
  exclude_keywords:                    # 命中 -50 分（降权过滤）
    - "medical segmentation"
    - "retinal"
    - "hyperspectral"
  tracked_authors:                     # 重点关注学者，命中 +25 分并打 radar 标记
    - "Kaiming He"
    - "Ross Girshick"
  tracked_affiliations:                # 重点关注机构，命中 +15 分
    - "Google DeepMind"
    - "FAIR"
    - "Meta AI"
  bonuses:
    has_code: 15                       # 检测到 GitHub/代码仓库加分
    oral_or_spotlight: 20              # comment 含 Oral / Spotlight / Best Paper 加分
  thresholds:
    tier_s: 50                         # >= 50 分：S 级（下载 PDF + 抽图 + 精读）
    tier_a: 25                         # 25~49 分：A 级（基于摘要生成速览卡片）
    # < 25 分：B 级（仅写入数据库与汇总列表，不消耗分析 Token）

# 下载、抽图与自动清理策略
storage:
  max_pdf_size_mb: 50
  extract_figures: true
  max_figures_per_paper: 2
  figure_max_width_px: 1200
  figure_webp_quality: 80
  auto_clean_after_publish: true       # 发布成功后自动删除 PDF 与队列临时文件
  min_valid_md_chars: 300              # 校验 MD 有效性的最小正文字符数

# 博客发布配置
publish:
  auto_git_commit: true
  auto_git_push: false                 # 默认 false 防止误推，命令行可用 --push 覆盖
  commit_message_template: "docs: publish {count} papers ({date})"

# 通知配置（可选）
notifications:
  windows_toast: true
  webhook_type: "none"                 # none | feishu | dingtalk | generic
  webhook_url_env: "PAPERFLOW_WEBHOOK_URL"
```

---

## 2. SQLite 数据库表结构（`workspace/state.db`）

连接数据库时必须启用：`PRAGMA journal_mode=WAL;` 与 `PRAGMA foreign_keys=ON;`。

### 2.1 `papers` 表（论文主账本）

```sql
CREATE TABLE IF NOT EXISTS papers (
    paper_uid        TEXT PRIMARY KEY,        -- 全局唯一 ID（见第 4 节生成规则）
    title            TEXT NOT NULL,
    normalized_title TEXT NOT NULL,           -- 小写去标点标题，用于二级防重
    authors_json     TEXT NOT NULL,           -- JSON 数组 ["Author A", "Author B"]
    affiliations_json TEXT DEFAULT '[]',      -- JSON 数组
    venue            TEXT NOT NULL,           -- 标准化简称: CVPR/ECCV/ICCV/NeurIPS/ICLR/AAAI/TPAMI/TIP/IJCV
    pub_year         INTEGER NOT NULL,
    pub_date         TEXT,                    -- YYYY-MM-DD（发表或预印本日期）
    fetch_date       TEXT NOT NULL,           -- YYYY-MM-DD（入库日期）
    source           TEXT NOT NULL,           -- arxiv | openalex | openreview | manual
    doi              TEXT,
    arxiv_id         TEXT,
    openreview_id    TEXT,
    abstract         TEXT DEFAULT '',
    comment          TEXT DEFAULT '',         -- arXiv comment / 录用备注（如 Oral/Spotlight）
    paper_url        TEXT DEFAULT '',
    pdf_url          TEXT DEFAULT '',
    code_url         TEXT DEFAULT '',
    code_stars       INTEGER DEFAULT NULL,
    project_url      TEXT DEFAULT '',

    -- 兴趣打分与分级
    score            REAL DEFAULT 0.0,
    tier             TEXT DEFAULT 'B',        -- S | A | B
    is_radar_hit     INTEGER DEFAULT 0,       -- 1=命中关注学者/机构/Oral
    matched_tags_json TEXT DEFAULT '[]',      -- 命中的关键词列表

    -- 生命周期状态机
    status           TEXT NOT NULL DEFAULT 'FETCHED',
    -- 允许值: FETCHED | SCORED | DOWNLOADED | QUEUED | ANALYZED | STAGED | PUBLISHED | CLEANED | SKIPPED | FAILED
    pdf_local_path   TEXT DEFAULT NULL,       -- 临时 PDF 路径，删除后置 NULL
    pdf_deleted      INTEGER DEFAULT 0,       -- 0=未删/未下, 1=已安全删除
    md_staging_path  TEXT DEFAULT NULL,       -- staging 中生成的 MD 路径
    md_blog_path     TEXT DEFAULT NULL,       -- 最终发布到 paper_repo 的相对路径

    -- 容错与审计
    retry_count      INTEGER DEFAULT 0,
    last_error       TEXT DEFAULT NULL,
    created_at       TEXT NOT NULL,           -- ISO 8601
    updated_at       TEXT NOT NULL            -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_papers_venue_year ON papers(venue, pub_year);
CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_fetch_date ON papers(fetch_date);
CREATE INDEX IF NOT EXISTS idx_papers_normalized_title ON papers(normalized_title);
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi) WHERE doi IS NOT NULL AND doi != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id) WHERE arxiv_id IS NOT NULL AND arxiv_id != '';
```

### 2.2 `job_watermarks` 表（定时拉取与补录水位线）

```sql
CREATE TABLE IF NOT EXISTS job_watermarks (
    source_name       TEXT NOT NULL,          -- arxiv | openalex | openreview
    venue             TEXT NOT NULL,          -- 具体 venue 或 'ALL'（如 arxiv 统一扫描）
    last_success_date TEXT NOT NULL,          -- YYYY-MM-DD，已完整拉取的最后一天
    last_run_at       TEXT NOT NULL,          -- ISO 8601
    last_status       TEXT NOT NULL,          -- SUCCESS | PARTIAL | FAILED
    last_error        TEXT DEFAULT NULL,
    PRIMARY KEY (source_name, venue)
);
```

### 2.3 `paper_metrics` 表（跨论文知识矩阵数据）

```sql
CREATE TABLE IF NOT EXISTS paper_metrics (
    paper_uid         TEXT PRIMARY KEY REFERENCES papers(paper_uid) ON DELETE CASCADE,
    task              TEXT DEFAULT '',        -- 如 Video Action Recognition
    backbone          TEXT DEFAULT '',        -- 如 ViT-L / Mamba / Diffusion
    datasets_json     TEXT DEFAULT '[]',      -- 如 ["Kinetics-400", "THUMOS14"]
    sota_summary      TEXT DEFAULT '',        -- 一句话核心指标结论
    tldr              TEXT DEFAULT '',        -- 一句话核心贡献
    innovation_tags_json TEXT DEFAULT '[]',   -- 如 ["Zero-Shot", "Efficiency"]
    user_rating       TEXT DEFAULT '',        -- 人工批注星级（可选）
    updated_at        TEXT NOT NULL
);
```

### 2.4 `run_logs` 表（任务执行历史审计）

```sql
CREATE TABLE IF NOT EXISTS run_logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    command           TEXT NOT NULL,          -- fetch | backfill | export-queue | publish | clean
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
    status            TEXT NOT NULL,          -- RUNNING | SUCCESS | FAILED
    message           TEXT DEFAULT ''
);
```

---

## 3. 论文生命周期状态机

状态流转严格遵循以下路径（所有状态变更必须通过 `PaperRepository.update_status()` 统一记录 `updated_at`）：

```text
FETCHED ──► SCORED ──┬── (B 级) ──────────────────────────► SKIPPED (仅留账本/总表)
                     ├── (A 级) ──► QUEUED ──► ANALYZED ──► STAGED ──► PUBLISHED ──► CLEANED
                     └── (S 级) ──► DOWNLOADED ──► QUEUED ──► ANALYZED ──► STAGED ──► PUBLISHED ──► CLEANED
                                        │              │
                                        └── (异常) ──► FAILED (保留 retry_count，支持重试)
```

---

## 4. `paper_uid` 生成与多源去重规则（`pipeline/dedup.py`）

不同数据源（例如 arXiv 与 OpenAlex）可能会抓到同一篇论文，必须遵循以下合并优先级：

1. **标题标准化函数 `normalize_title(title: str) -> str`**：
   - 转小写 → 去除 LaTeX 花括号与非字母数字字符 → 合并多余空格。
2. **`paper_uid` 生成优先级**：
   - 优先使用 `doi`：`doi_` + `sha1(doi.lower().strip())[:12]`
   - 其次使用 `arxiv_id`（去掉版本号如 `v2`）：`arxiv_` + `2603.12345`（将 `/` 替换为 `_`）
   - 其次使用 `openreview_id`：`or_` + `<id>`
   - 兜底使用标准化标题：`title_` + `sha1(normalized_title)[:12]`
3. **入库合并策略（`upsert_paper`）**：
   - 先按 `doi`、`arxiv_id`、`normalized_title` 依次查库。
   - **若已存在**：不覆盖已有的 `status`、`md_blog_path`、`pdf_deleted` 等生命周期字段；仅执行**字段补全**（例如原来只有 arXiv 预印本，后来 OpenAlex 补齐了正式 `doi` 和 `TPAMI` 正式发表日期，则补充这些空字段，并在日志中记录 `enriched`）。
   - **若不存在**：插入新记录，返回 `is_new = True`。

---

## 5. Phase 1 验收测试要求（`tests/test_db.py`, `tests/test_config.py`）

1. 测试 `config.example.yaml` 能通过 Pydantic 严格校验并正确解析所有 9 个 Venue。
2. 测试 `PaperRepository` 重复初始化建表不报错（幂等）。
3. 测试同一篇论文先由 `arxiv` 入库（无 DOI）、再由 `openalex` 入库（带 DOI 且同标题）时，能正确合并而非插入两条记录，且原状态不被重置。
4. 测试水位线 `get_watermark` / `set_watermark` 读写准确。
