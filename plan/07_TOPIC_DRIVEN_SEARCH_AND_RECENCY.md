# Phase 10：研究方向精准检索（Topic-Driven Search）与近两年时效优先策略

> **背景说明**：Phase 1 ~ Phase 9 已全部完成并稳定运行。本文件为**增量新功能规格书（Phase 10）**，在**完全不破坏现有功能与历史数据库**的前提下，新增**“按研究方向（Topic）精准抓取论文”**能力（如 `agent`、`agent+图像融合`、`HSI-MSI图像融合`），并强制执行 **“今年（2026）绝对优先，最差仅兜底去年（2025），彻底过滤前年及更早论文”** 的两年时效窗口策略。

---

## 1. 核心需求与设计原则

1. **双模式并行，无缝融入现有流水线**：
   - 原有 **Venue 模式**（按 9 大顶会/顶刊定时盲扫）保持不变。
   - 新增 **Topic 方向模式**：按用户输入的单个方向或组合交叉方向，跨 **arXiv + OpenAlex** 精准检索，拉取后的论文自动进入现有 `dedup.py` 去重、`state.db` 账本、`downloader.py` 下载、`extractor.py` 抽图、`queue_exporter.py` 导出队列以及 `paper_repo` 博客发布与清理全流程。
2. **严格的“近两年”时效策略（今年优先，最差去年）**：
   - 动态基于 `current_year = config.project.target_year`（当前为 `2026`）计算：
     - **优先年份（Primary Year）**：`2026`（今年）
     - **兜底年份（Fallback Year）**：`2025`（去年）
     - **硬过滤底线**：任何 `pub_year < current_year - 1`（即 `<= 2024`）的论文**一律硬性丢弃，绝不入库**。
   - **配额优先填充逻辑**：当某方向目标拉取 `limit` 篇（如 `20` 篇）时：
     1. 优先拉取并保留所有 `2026` 年高相关论文；
     2. 若 `2026` 年结果数 `>= limit`，**全部取 `2026` 年**（不混入 `2025` 年）；
     3. 若 `2026` 年结果数 `< limit`（常见于极细分交叉方向，如 `agent+图像融合`），则自动用 `2025` 年结果按相关性/引用数/开源情况择优补齐剩余 `limit - len(primary)` 个名额；
     4. 排序展示时始终 **`2026` 年置顶**，`2025` 年排在下方并打上 `2025 兜底` 视觉标识。
3. **不限于 9 大顶会（兼容专业顶刊）**：
   - 在方向检索模式下（如 `HSI-MSI图像融合`），很多顶流工作发表在 `IEEE TGRS`、`Information Fusion`、`IEEE TCI` 或最新 `arXiv` 上。
   - 因此 Topic 模式允许保留论文真实 `venue`（若命中 9 大顶会/顶刊则标准化为简称并给额外加分；若为其他期刊/会议则保留真实名称如 `IEEE TGRS` / `Information Fusion`；若为纯预印本则标记为 `arXiv`），同时提供可选开关 `--top-venues-only` 供需要时收紧。
4. **豁免全局排除词冲突（关键防坑）**：
   - 注意现有 `config.yaml` 的 `interest_profile.exclude_keywords` 中可能包含 `hyperspectral` 等词。
   - 当用户主动检索 `HSI-MSI图像融合` 时，**Topic 模式命中的论文必须自动豁免全局 `exclude_keywords` 扣分**，避免用户主动搜的方向反而被降权跳过。

---

## 2. 配置与数据库平滑扩展（100% 向后兼容）

### 2.1 `config/config.yaml` 新增 `topic_search` 节点
在 `config/config.yaml` 与 `config/config.example.yaml` 中追加以下配置（Pydantic 模型提供完整默认值，确保旧配置文件不改也能直接运行）：

```yaml
topic_search:
  enabled: true
  # 时效策略：今年优先，最差去年（动态基于 target_year 计算）
  recency_policy:
    primary_year: 2026                 # 优先年份（默认取 project.target_year）
    allow_fallback_prev_year: true     # 是否允许用去年（target_year - 1）补齐缺口
    primary_year_bonus: 25.0           # 今年论文额外时效加分
    strict_min_year_offset: 1          # 严格底线：只允许 [target_year - 1, target_year]
  default_limit_per_topic: 20
  auto_promote_top_n_to_s: 3           # 每个方向拉取后，自动将排名前 N 的 2026 论文标为 S 级（0 表示按分值正常分级）

  # 中英文与学术缩写同义词扩展词典（用户可自由追加）
  synonym_dict:
    "agent": ["agent", "LLM agent", "multimodal agent", "autonomous agent", "agentic"]
    "图像融合": ["image fusion", "multi-modal image fusion", "infrared and visible image fusion", "multi-focus image fusion"]
    "hsi-msi": ["hyperspectral and multispectral", "HSI-MSI", "HSI and MSI", "hyperspectral super-resolution", "multispectral fusion"]
    "hsi-msi图像融合": ["HSI-MSI fusion", "hyperspectral and multispectral image fusion", "HSI and MSI fusion", "hyperspectral image super-resolution"]
    "超分": ["super-resolution"]
    "遥感": ["remote sensing"]
    "多模态": ["multimodal", "vision-language"]

  # 常驻订阅方向列表（可用于 `paperflow topic-run` 与每日定时任务）
  subscriptions:
    - name: "Agent"
      slug: "agent"
      query: "agent"
      enabled: true
      limit: 20
      only_primary_year: false
      top_venues_only: false
    - name: "Agent + 图像融合"
      slug: "agent-image-fusion"
      query: "agent+图像融合"
      enabled: true
      limit: 20
      only_primary_year: false
      top_venues_only: false
    - name: "HSI-MSI 图像融合"
      slug: "hsi-msi-fusion"
      query: "HSI-MSI图像融合"
      enabled: true
      limit: 20
      only_primary_year: false
      top_venues_only: false
```

### 2.2 SQLite 无损迁移（`db/repository.py`）
在初始化数据库时自动检查列是否存在（`PRAGMA table_info(papers)`），缺失则平滑执行 `ALTER TABLE`（不删除、不破坏现有任何历史记录）：

```sql
-- 1. 扩展 papers 表
ALTER TABLE papers ADD COLUMN discovery_mode TEXT NOT NULL DEFAULT 'venue'; -- venue | topic | manual
ALTER TABLE papers ADD COLUMN topic_tags_json TEXT NOT NULL DEFAULT '[]';   -- JSON 数组，如 ["HSI-MSI 图像融合", "Agent + 图像融合"]

-- 2. 新增方向检索历史记录表（方便 Web 界面快速查看各方向拉取历史）
CREATE TABLE IF NOT EXISTS topic_search_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id            TEXT,
    topic_name         TEXT NOT NULL,
    raw_query          TEXT NOT NULL,
    expanded_query     TEXT NOT NULL,
    primary_year       INTEGER NOT NULL,
    fallback_year      INTEGER NOT NULL,
    primary_count      INTEGER DEFAULT 0,      -- 本次命中今年（2026）篇数
    fallback_count     INTEGER DEFAULT 0,      -- 本次兜底去年（2025）篇数
    filtered_old_count INTEGER DEFAULT 0,      -- 被拦截的 2024 及更早篇数
    new_inserted_count INTEGER DEFAULT 0,
    status             TEXT NOT NULL,          -- SUCCESS | FAILED
    created_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_topic_runs_created ON topic_search_runs(created_at DESC);
```

---

## 3. 核心算法模块设计

### 3.1 智能方向查询解析与扩展器（`src/paperflow/pipeline/topic_query.py`）

将用户自然输入（中文、英文、缩写、`+` 组合词）转化为对 **arXiv** 和 **OpenAlex** 高度友好的精准检索式：

1. **组合语法解析**：
   - 将输入按 `+`、`＆`、`&`、` AND ` 拆分为多个**必选概念组（AND Groups）**。
   - 例如：
     - `"agent"` → 1 组：`["agent"]`
     - `"agent+图像融合"` → 2 组：`["agent", "图像融合"]`
     - `"HSI-MSI图像融合"` → 先整体查词典命中 `"hsi-msi图像融合"`；若未整体命中，则按中英文边界自动切分为 `["HSI-MSI", "图像融合"]`。
2. **词典扩展（OR 组）**：
   - 每个概念组在 `config.topic_search.synonym_dict` 中忽略大小写匹配，扩展为同义词列表（英文短语自动加双引号）。
   - 未命中词典的英文术语直接原样保留为短语查询。
3. **目标源语法生成**：
   - **arXiv 查询串**：每组生成 `(ti:"term1" OR abs:"term1" OR ti:"term2" OR abs:"term2")`，多组之间用 `AND` 连接。
   - **OpenAlex 查询串**：生成 `title_and_abstract.search` 兼容的布尔检索串（支持 `AND` / `OR` 与引号短语）。
4. **本地相关性二次校验与打分（`compute_topic_relevance(paper, parsed_query)`）**：
   - 标题命中概念组比摘要命中权重更高（标题命中 +25/组，摘要命中 +12/组）。
   - **交叉方向完整性校验**：对于 `A + B` 组合方向，必须同时命中 A 组和 B 组才算“完全匹配”（`+30` 分）；若某极细分方向完全匹配数不足，可启用**自动放宽回退（Relaxation Fallback）**并在日志中明确标注 `relaxed_match`。

### 3.2 多源方向检索与“两年优先”调度器（`src/paperflow/fetchers/topic_fetcher.py`）

实现 `TopicSearchEngine`，核心执行流程如下：

1. **年份窗口计算**：
   - `primary_year = config.topic_search.recency_policy.primary_year`（2026）
   - `fallback_year = primary_year - 1`（2025）
2. **两阶段拉取（2026 First, 2025 Fallback）**：
   - **Stage A（拉取 2026）**：
     - OpenAlex 显式附加 `filter=publication_year:2026`（按 `publication_date:desc` 拉取）。
     - arXiv 按 `submittedDate` 倒序拉取，附加时间范围 `[202601010000 TO 202612312359]`。
     - 合并、去重并过滤掉任何非 `2026` 年的脏数据。
   - **Stage B（按需兜底 2025）**：
     - 如果 `only_primary_year == False` 且 `len(primary_results) < limit`：
     - 计算缺口 `need = limit - len(primary_results)`。
     - 向 OpenAlex（`filter=publication_year:2025`，按 `cited_by_count:desc` 或相关性排序）与 arXiv（`[202501010000 TO 202512312359]`）拉取候选论文。
     - 严格过滤掉任何 `pub_year != 2025`（即 `<= 2024`）的论文，并统计 `filtered_old_count`。
3. **综合排序（保证 2026 绝对靠前）**：
   - 排序键：`(pub_year == primary_year, total_score, pub_date or "")` 降序。
   - 综合分 `total_score = topic_relevance_score + recency_bonus (2026: +25, 2025: 0) + top_venue_bonus (+15) + code_bonus (+15) + radar_bonus`。
   - 最终截断至 `limit` 篇返回。
4. **入库与合并**：
   - 调用现有 `PaperRepository.upsert_paper()`：
     - 若论文已存在于 `state.db`（比如之前被顶会模式拉过），**合并追加** `topic_tags_json`（不覆盖原有状态与分析记录）。
     - 若为新论文，设置 `discovery_mode = 'topic'`，写入 `topic_tags_json`，跳过全局 `exclude_keywords` 扣分；若排名前 `auto_promote_top_n_to_s` 且为 `2026` 年论文，自动提升为 `S` 级。
   - 可选立即触发 `downloader.py` + `extractor.py` 下载 S 级 PDF 并抽图。

---

## 4. 博客专题聚合联动（`publisher/aggregator.py` 扩展）

在执行 `paperflow publish` 刷新聚合页面时，新增生成 **研究方向专题页**：
- 扫描 `papers` 表中所有非空的 `topic_tags_json`，按方向自动生成：
  - `paper_repo/docs/topics/<topic_slug>.md`（如 `agent.md`、`agent-image-fusion.md`、`hsi-msi-fusion.md`）
- 页面结构：
  - 顶部统计（该方向 2026 收录数 / 2025 兜底收录数 / 开源代码数）
  - **🔥 2026 最新前沿** 表格（置顶展示）
  - **📌 2025 精选兜底** 表格（折叠或分区展示）
- 同步在 `paper_repo/docs/index.md` 增加“按研究方向浏览”快捷入口卡片。

---

## 5. CLI 新增命令（`src/paperflow/cli.py`）

| 命令 | 参数选项 | 功能说明 |
| :--- | :--- | :--- |
| `paperflow topic-search` | `QUERY`, `--limit 20`, `--only-primary-year`, `--top-venues-only`, `--sources arxiv,openalex`, `--download`, `--dry-run` | 即时按方向检索论文（2026 优先、2025 兜底），支持预览实际扩展后的英文检索式 |
| `paperflow topic-run` | `--topic <name>`, `--download`, `--dry-run` | 批量执行 `config.yaml` 中所有已启用的常驻订阅方向（可加入 `scripts/run_daily_fetch.ps1` 每日自动追新） |
| `paperflow topic-list` | 无 | 展示已配置的常驻方向、同义词扩展预览及各方向 2026/2025 已收录统计 |

---

## 6. Web 控制台新增页面：页面 8 — 方向精准检索中心（Topic Explorer）

在 `src/paperflow/web/` 中新增路由模块 `routes/topics.py`，并在 `static/index.html` 左侧导航栏新增 **【方向精准检索】** 入口：

### 6.1 新增 REST API（`src/paperflow/web/routes/topics.py`）

| Method | Path | 说明 |
| :--- | :--- | :--- |
| `POST` | `/api/topics/preview-query` | 实时预览用户输入的中文/组合词将被扩展成的 arXiv / OpenAlex 英文检索式 |
| `POST` | `/api/topics/search` | 启动方向检索任务（走 `TaskManager` + SSE 实时进度流），支持 `query`, `limit`, `only_primary_year`, `top_venues_only`, `sources`, `auto_download`, `dry_run` |
| `POST` | `/api/topics/run-subscriptions` | 一键跑完所有已启用的常驻订阅方向（SSE 实时进度） |
| `GET` | `/api/topics/subscriptions` | 获取常驻方向列表 + 每个方向的 2026/2025 收录统计 |
| `PUT` | `/api/topics/subscriptions` | 在线增删改常驻方向（自动 Pydantic 校验并写回 `config.yaml`） |
| `GET` | `/api/topics/history` | 查询 `topic_search_runs` 方向检索历史（含 2026 命中数、2025 兜底数、过滤掉的老论文数） |

### 6.2 前端界面布局
1. **顶部智能检索面板**：
   - 大号方向输入框（Placeholder：`输入研究方向，支持中英文与 + 组合，如：agent、agent+图像融合、HSI-MSI图像融合`）。
   - 下方一行**常驻方向快捷胶囊**（点击直接填入并检索），右侧附带 **【一键追新所有订阅方向】** 按钮。
   - **实时查询式预览折叠条**：输入时防抖调用 `/api/topics/preview-query`，直观展示解析出的英文逻辑检索式（如 `("agent" OR ...) AND ("image fusion" OR ...)`）。
   - 参数条：年份策略徽章（`2026 优先 → 2025 兜底，严禁 ≤2024` / 可勾选 `仅看 2026`）、数量上限（10/20/50）、仅限顶会顶刊开关、自动下载 S 级 PDF 开关。
2. **实时 SSE 进度条 + 分年结果展示区**：
   - 任务运行时实时显示：`正在检索 arXiv (2026) → 2026 命中 8 篇，不足 20 篇，自动启动 2025 兜底补齐...`
   - 完成后结果自动按年份分组高亮展示：
     - **`🔥 2026 最新 (8 篇)`**（默认展开，绿色年份徽章）
     - **`📌 2025 兜底补充 (12 篇)`**（琥珀色年份徽章，附带提示“已自动过滤掉 X 篇 2024 及更早论文”）
   - 每条论文卡片支持一键 **【升为 S 级并下载 PDF】**、**【复制 BibTeX】**、直达原文/代码仓库。
3. **底部双标签管理区**：
   - **Tab 1：常驻方向订阅管理**：表格化添加/编辑/启停/删除常驻追踪方向（如 `Agent`、`Agent+图像融合`、`HSI-MSI图像融合`）以及自定义同义词扩展词典。
   - **Tab 2：方向检索历史**：展示 `topic_search_runs` 每次检索的关键词、2026/2025 命中比例与新增入库数。

---

## 7. Phase 10 验收测试要求（`tests/test_topic_search.py`）

1. **查询解析与中英扩展测试**：
   - 验证 `"agent"`、`"agent+图像融合"`、`"HSI-MSI图像融合"` 均能生成语法合法的 arXiv 与 OpenAlex 查询串，且 `+` 正确生成 `AND` 关系。
2. **两年时效优先逻辑测试（核心必测）**：
   - **场景 A（2026 充足）**：Mock 返回 25 篇 2026 论文 + 10 篇 2025 论文，`limit=20` → 断言最终结果 **20 篇全部为 2026**，不触发或不包含 2025。
   - **场景 B（2026 不足，2025 补齐）**：Mock 返回 6 篇 2026 论文 + 20 篇 2025 论文 + 10 篇 2024 论文，`limit=15` → 断言最终结果共 15 篇：前 6 篇全为 2026，后 9 篇为 2025，**0 篇 2024**，`filtered_old_count == 10`。
   - **场景 C（仅 2026 模式）**：`only_primary_year=True`，2026 仅 6 篇 → 断言只返回 6 篇 2026，不拉取 2025。
3. **全局排除词豁免测试**：
   - 在 `exclude_keywords` 包含 `"hyperspectral"` 的配置下，通过 Topic 模式搜 `"HSI-MSI图像融合"`，断言论文不被扣 `-50` 分且正常评为高分。
4. **SQLite 平滑迁移测试**：
   - 构造不含 `discovery_mode` 与 `topic_tags_json` 列的旧版 `state.db`，初始化 `PaperRepository` 后验证自动 `ALTER TABLE` 成功且旧数据 100% 保留。
5. **Web API 测试**：
   - 验证 `/api/topics/preview-query`、`/api/topics/search`（SSE 流）、`/api/topics/subscriptions`、`GET /api/topics/history` 全部返回 `200` 且状态落库正确。
6. **回归测试**：
   - 运行全量 `pytest -v`，确认原有 Phase 1 ~ Phase 9 的所有测试依然 100% 通过，无任何破坏性回归。
