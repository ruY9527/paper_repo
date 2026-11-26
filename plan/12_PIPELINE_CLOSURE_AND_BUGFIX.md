# Phase 15：全链路闭环收口与核心断链修复计划

> **文档定位**：本文件针对 Phase 1 ~ Phase 14 增量开发后暴露出的 **10 处核心逻辑断链、口径不一致与仓库污染问题**，制定精确的收口修复方案。
> 请严格按 Fix 1 → Fix 10 逐项修复，每项均需补齐对应的自动化闭环测试（`tests/test_pipeline_closure.py`），确保整套系统从 **采集/插队/补传 → 自动入队 → AI 解析 → 校验发布 → 汇总页与导航更新 → Git 推送 → 安全清理** 100% 端到端闭环。

---

## 一、P0 级核心断链修复（必须优先解决）

### Fix 1：修复「跨天解析 → 发布 0 篇」的日期错位断链
- **根因**：
  - `src/paperflow/analyzers/runner.py` 写结果时使用 `paper.fetch_date`（例如昨天 `2026-11-22`），写入 `staging/2026-11-22/<uid>.md`；
  - `src/paperflow/publisher/sync_blog.py` 的 `publish()` 在未传 `target_date` 时默认赋值为 `today_date().isoformat()`（今天 `2026-11-23`），导致 `validate_all_staged(..., target_date=target_date)` **完全跳过昨天及更早日期的待审 `.md`**！
- **精确修复方案**：
  1. 修改 `sync_blog.py:publish()`：
     - 保留 `target_date: str | None = None` 原语义：**当调用方显式传入 `target_date` 时只发布该日期；当 `target_date is None` 时，扫描 `workspace/staging/` 下所有日期目录中尚未发布（`status not in ('PUBLISHED', 'CLEANED')`）的 `.md` 文件**。
     - Commit message 中的 `{date}` 在 `target_date is None` 时取 `today_date().isoformat()`。
  2. 修改 `pipeline/md_validator.py:validate_all_staged()`：增加可选参数 `only_unpublished: bool = False`，支持跳过已发布的旧 staging 文件，避免每次 publish 重复覆盖已发布文章。
  3. 同步检查 `web/routes/tasks.py:run_publish()` 与 `web/routes/git_ops.py:run_publish_and_push()`：未传 `date` 时透传 `target_date=None`。

---

### Fix 2：打通「单篇插队 / 手动升 S 级 / 失败重试」的死胡同
- **根因**（`src/paperflow/web/routes/papers.py`）：
  1. `POST /api/papers/add` 插队后停在 `SCORED`，不下载 PDF、不导出队列，去【AI 解析中心】看不到；
  2. `PATCH /api/papers/{uid}/tier` 升为 S 级或 A 级后停在 `SCORED`，不下载 PDF、不导出队列；
  3. `POST /api/papers/{uid}/retry` 重置为 `FETCHED`，但全系统没有任何任务会自动扫描 `FETCHED` 去重新打分与下载，导致永久卡死。
- **精确修复方案**：
  1. 在 `src/paperflow/pipeline/` 新增轻量辅助函数 `prepare_paper_for_analysis(config, repo, paper_uid, *, auto_download=True, auto_queue=True) -> dict`：
     - 若 `status == FETCHED`：先执行 `score_and_persist()`；
     - 若 `tier == S` 且 `status == SCORED` 且 `auto_download=True`：执行单篇下载（走 `PaywallFilter` + `_download_one`，受限则登记 `paywall_papers`，成功则置 `DOWNLOADED`）；
     - 若 `status in (DOWNLOADED, SCORED)` 且 `tier in (S, A)` 且 `access_type != 'paywall_blocked'` 且 `auto_queue=True`：立即调用 `ensure_analysis_package()` 生成 `queue/<today>/<uid>/` 任务包并置 `status = QUEUED`（同步合并更新 `queue_manifest.json`）。
  2. 改造 `web/routes/papers.py` 三个接口：
     - `add_paper()`：插库强制 S 级后，自动调用 `prepare_paper_for_analysis()`（支持请求体可选 `auto_prepare: true` 默认开启），返回最终真实状态（`QUEUED` 或 `paywall_blocked`），插队完立刻在【AI 解析中心】可见。
     - `set_tier()`：手动升为 `S` 或 `A` 时（且 `status` 在 `FETCHED / SCORED / SKIPPED`），自动调用 `prepare_paper_for_analysis()`，立刻进入待解析队列。
     - `retry()`：重置 `retry_count + 1, last_error = None` 后，自动调用 `prepare_paper_for_analysis()`（而不是扔回 `FETCHED` 无人问津），返回真实新状态。

---

### Fix 3：补齐「受限论文（Paywall）」抢救、转摘要与补传的下游闭环
- **根因**（`src/paperflow/web/routes/paywall.py` & `src/paperflow/pipeline/manual_pdf.py`）：
  1. `POST /api/paywall/papers/{uid}/rescue` 抢救出 arXiv 后，未更新 `paywall_papers.oa_rescue_status='RESCUED_ARXIV'`、`manual_status='PDF_UPLOADED'`（或新增 `RESCUED`）、未将 `papers.access_type` 改回 `'open'`，也未触发下载和入队；
  2. `POST /api/paywall/papers/{uid}/fallback-abstract` 只改了 `tier='A'`，未导出队列，解析中心看不到；
  3. `manual_pdf.py:attach_local_pdf()` 补传 PDF 后只到 `DOWNLOADED`，未生成 `queue/` 任务包，在【AI 解析中心】点【复制 Prompt】给 DeepSeek Harness Web 时报 `404`。
- **精确修复方案**：
  1. `paywall.py:rescue()`：当 `filter_and_rescue()` 返回 `action == "rescued"` 时：
     - 更新 `paywall_papers`：`oa_rescue_status = "RESCUED_ARXIV"`, `manual_status = "RESCUED"`, `resolved_at = now_iso()`；
     - 更新 `papers`：`access_type = "open"`；
     - 立即调用 Fix 2 的 `prepare_paper_for_analysis()` 完成 arXiv PDF 下载与队列导出。
     - 若未找到，更新 `paywall_papers.oa_rescue_status = "NOT_FOUND"`。
  2. `paywall.py:fallback_abstract()`：将 `tier` 改为 `A`、更新 `paywall_papers.manual_status = "ABSTRACT_ONLY"` 后，立即调用 `ensure_analysis_package()` 导出摘要版任务包并置 `status = QUEUED`（立刻在【AI 解析中心】可见）。
  3. `manual_pdf.py:attach_local_pdf()`：补传并抽图完成后，顺手调用 `ensure_analysis_package()` 生成 `prompt.md` + `meta.json` 并置 `status = QUEUED`。
  4. `web/routes/analyzer.py:analyzer_prompt()`（`GET /api/analyzer/prompt/{paper_uid}`）：若 `_find_paper_dir()` 为 `None` 但论文存在于账本中，**自动调用 `ensure_analysis_package()` 即时补齐任务包**后再返回 Prompt，彻底消灭 `404 未找到论文任务包`。

---

### Fix 4：统一“三套分裂的博客发布逻辑” + 修复清理器相对路径 Bug
- **根因**：
  - `sync_blog.py:publish()`、`blog_articles.py:publish_one()`、`analyzer.py:analyzer_sync_to_blog()` 各自复制文件，行为不一致（后两者不刷新 `aggregator` 汇总页；`analyzer_sync_to_blog` 连校验、公式修复、AI 声明与返回链接都漏掉了）。
  - `cleaner.py:clean_papers()` 直接用相对路径 `Path(paper.md_blog_path).exists()` 校验文件是否存在，实际应相对于 `config.paper_repo_path / "docs"` 解析！
- **精确修复方案**：
  1. **收口单篇发布内核**：让 `blog_articles.py:publish_one(config, repo, paper_uid, *, rebuild_agg=True)` 成为**唯一**单篇发布内核：
     - 必须先执行 `validate_md_file(..., persist=True)`（未通过直接拒绝发布）；
     - 统一执行图片路径修复（见 Fix 5）、`fix_bare_math`、`append_ai_notice`、`append_back_link`、复制 WebP 架构图、更新 `status = PUBLISHED` 与 `md_blog_path`；
     - 默认调用 `rebuild_all(config, repo)` 刷新首页/Venue总表/SOTA矩阵/专题页（批量发布时传 `rebuild_agg=False`，批尾统一调一次 `rebuild_all`）。
  2. **重构 `analyzer.py:analyzer_sync_to_blog()`**：删除重复拷贝代码，直接委托调用 `publish_one(manager.config, manager.repo, paper_uid, rebuild_agg=True)`。
  3. **重构 `sync_blog.py:publish()`**：内部复用 `publish_one(..., rebuild_agg=False)`，彻底消除三套逻辑漂移。
  4. **修复 `cleaner.py:clean_papers()`**：
     - 校验 `md_blog_path` 时，若 `not Path(p).is_absolute()`，自动拼接为 `config.paper_repo_path / "docs" / p` 再检查 `.exists()` 与 `st_size > 0`。
     - 清理某篇论文的 `queue/<date>/<uid>/` 目录后，同步把该 `uid` 从对应的 `queue_manifest.json` 的 `items` 中移除（若 `items` 为空则删除该 `queue_manifest.json` 以便清理空日期目录）。

---

### Fix 5：修复「架构图相对路径」在导出、Prompt、Staging、博客四处的断裂
- **根因**：
  - `queue_exporter.py`（L134）把 `figures_markdown` 写成裸文件名 `![核心架构图](fig_1.webp)`；
  - `sync_blog.py` 和 `blog_articles.py` 仅替换 `](../../assets/` → `](../../../assets/`，导致 `fig_1.webp` 在博客里永久 404 且炸掉 `mkdocs build --strict`！
- **精确修复方案**：
  1. **统一标准写法**：`queue_exporter.py` 与 `analyzers/base.py:ensure_analysis_package()` 生成 `figures_markdown` 时，统一使用 Staging 标准相对路径：
     `![核心架构图](../../assets/{paper.paper_uid}/{Path(f).name})`
  2. **发布时强韧兜底替换**：在公共函数 `fix_image_paths_for_blog(content: str, paper_uid: str) -> str` 中，同时兼容处理以下 3 种模型可能输出的写法，全部统一归一化为 `../../../assets/{paper_uid}/{filename}`：
     - `](../../assets/<uid>/<file>.webp)` → `](../../../assets/<uid>/<file>.webp)`
     - `](assets/<uid>/<file>.webp)` 或 `](workspace/staging/assets/<uid>/<file>.webp)` → `](../../../assets/<uid>/<file>.webp)`
     - 裸文件名 `](fig_1.webp)`（当且仅当 `staging/assets/<uid>/fig_1.webp` 真实存在时）→ `](../../../assets/<uid>/fig_1.webp)`。
  3. 如果某篇 Markdown 引用的 `../../../assets/<uid>/<file>.webp` 实际文件不存在，记录明确 WARNING，避免把断链推上博客。

---

### Fix 6：修复「重新打分误杀方向检索论文」& 统一采集/流水线行为
- **根因**：
  - `web/routes/settings.py:rescore()` 对所有 `SCORED` 论文（含 `discovery_mode == 'topic'`）调用 `score_and_persist()`，未豁免 `exclude_keywords`，导致含 `hyperspectral` 的 `HSI-MSI 图像融合` 论文被误杀成 `SKIPPED`。
  - `web/routes/tasks.py:run_fetch()` 未遵循 `dry_run` 参数且下载后未自动 `export_queue`；`run_pipeline()` 的 `topic_run` 与 `steps` 判定条件冗余易踩坑；`scripts/run_daily_fetch.ps1` 未支持 `-AutoAnalyze` 且通知为静态文本。
- **精确修复方案**：
  1. `settings.py:rescore()`：
     - 跳过 `discovery_mode == "topic"` 或 `source == "manual"` 的论文（或在 `score_paper()` 新增参数 `exempt_exclude_keywords: bool = False`，对 `discovery_mode == "topic"` 传 `True`，且保留其 `topic_tags` 与不降级为 `B/SKIPPED`）。
  2. `tasks.py:run_fetch()`：
     - 支持 `dry_run` 参数（`dry_run=True` 时只统计不入库不下载）；
     - 非 `dry_run` 时下载完 S 级 PDF 后，与 `topic_fetcher.py` 保持一致，自动调用 `export_queue(cfg, repo)`（可通过 `auto_export=False` 关闭），确保拉取完立刻能在【AI 解析中心】看到。
  3. `tasks.py:run_pipeline()`：
     - 只要 `p.get("topic_run")` 为真 或 `"topics" in steps`，即执行常驻方向追新（去掉双重 `and` 陷阱）。
  4. `scripts/run_daily_fetch.ps1`：
     - 增加可选开关 `[switch]$AutoAnalyze`，开启时自动执行 `python -m paperflow analyze`；
     - 播报前读取 `paperflow status` 或 SQLite 当日统计，输出真实数字（今日新增/S级/A级/待解析/受限篇数）。

---

## 二、P1 级口径一致性、导航与仓库卫生修复

### Fix 7：统一前后端 KPI 统计口径
- 修改 `web/routes/dashboard.py`：`queued` 统计口径与 `analyzer.py` 保持一致（或拆分返回 `queued_ready` = `QUEUED + DOWNLOADED`、`queued`、`downloaded`），保证首页看板“待解析队列”数字与【AI 解析中心】完全一致。

### Fix 8：博客 `mkdocs.yml` 动态导航与年份参数化
- `publisher/aggregator.py`：
  - 将写死的 `f"{VENUE_DISPLAY_NAMES.get(v, v)}-2026.md"`、`sota-2026.md`、`open-source-2026.md` 全部改为动态使用 `config.target_year`；
  - 扩展 `mkdocs.yml` 导航同步逻辑（复用 `sites/blog_renderer.py` 的纯文本安全更新思路，绝不用 `yaml.safe_dump` 破坏 `!!python/name`）：当 `docs/topics/` 下生成了方向专题页或 `docs/weekly/` 下生成了周报时，自动在 `mkdocs.yml` 的 `nav:` 下挂载 **「研究方向」** 与 **「趋势周报」** 入口（幂等更新）。

### Fix 9：统一配置热重载（消除多路由 `CONFIG_PATH` 分裂）
- 在 `web/task_manager.py` 或 `web/state.py` 提供统一的 `reload_config(app_or_manager, new_config_path=None)` 辅助函数：
  - 当 `settings.py` / `topics.py` / `paywall.py` 保存 `config.yaml` 时，统一更新 `manager.config`、`app.state.config`，并同步刷新 `app.state.mkdocs_service.preview_port` 与 `paper_repo_dir`。

### Fix 10：清理已污染的测试脏数据 & 加固测试隔离
- **清理动作**（请检查并确认后再删除）：
  1. 检查 `paper_repo/docs/papers/2026/CVPR/p0.md`、`p1.md`、`p2.md`、`p3.md` 等明显属于测试假数据的文件，从 `paper_repo/docs/` 和 `workspace/state.db` 中清理干净（保留真实 `arxiv_*` / `doi_*` 论文）；
  2. 清理 `workspace/staging/2026-03-16/` 测试残留目录；
  3. 审计 `tests/` 下所有测试文件，确保**没有任何测试默认读写项目根目录的真实 `paper_repo/`、`workspace/state.db` 或 `config/config.yaml`**（全部必须通过 `tmp_path` 隔离）。

---

## 三、Phase 15 端到端闭环验收测试（`tests/test_pipeline_closure.py`）

必须全部通过以下自动化闭环测试（全部在 `tmp_path` 隔离运行，零污染真实目录）：

1. **跨天发布闭环测试**：模拟论文 `fetch_date = 昨天`，解析产物写入 `staging/昨天/<uid>.md`，今天调用 `publish(config, repo)`（不传 `target_date`）→ 断言成功发布 1 篇、`status == PUBLISHED`。
2. **单篇插队 / 升 S 级 / 重试闭环测试**：
   - Mock `SinglePaperAdder` 调用 `POST /api/papers/add` → 断言无需手动点导出，直接出现在 `GET /api/analyzer/queue`；
   - B 级论文调 `PATCH /api/papers/{uid}/tier` 升为 S 级 → 自动进入 `QUEUED`；
   - `FAILED` 论文调 `POST /api/papers/{uid}/retry` → 不停留在 `FETCHED`，自动推进至 `SCORED/QUEUED`。
3. **Paywall 抢救 & 补传 & 摘要降级闭环测试**：
   - `rescue` 成功 → `oa_rescue_status == 'RESCUED_ARXIV'`、`access_type == 'open'` 且进入待解析队列；
   - `fallback-abstract` → 直接进入 `QUEUED` 且 `GET /api/analyzer/prompt/{uid}` 返回 `200`；
   - `upload-pdf` → 自动生成 `queue/` 任务包且 `GET /api/analyzer/prompt/{uid}` 返回 `200`。
4. **图片路径 & 单篇/全量发布统一 & 清理器测试**：
   - 分别测试正文含 `fig_1.webp` 和 `../../assets/<uid>/fig_1.webp` → 发布后统一变成 `../../../assets/<uid>/fig_1.webp` 且 `mkdocs build --strict` 零警告通过；
   - 删除 staging 文件后仅保留相对路径 `md_blog_path`，运行 `clean_papers()` → 断言识别博客文件存在、安全清理临时 PDF、`pdf_deleted == 1`、`queue_manifest.json` 同步清理该 `uid`。
5. **重新打分不误杀方向论文测试**：
   - 配置 `exclude_keywords=["hyperspectral"]`，入库一篇 `discovery_mode="topic"` 的 `HSI-MSI` 论文，调用 `POST /api/settings/rescore` → 断言仍保留高分且**不被降为 `SKIPPED`**。
6. **全量回归测试**：运行 `pytest -v`，确认全项目所有测试 100% 通过且**不会向真实 `paper_repo/` 或 `workspace/` 写入任何测试文件**。
