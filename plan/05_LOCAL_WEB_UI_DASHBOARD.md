# Phase 8：本地 Web 控制台（PaperFlow Studio）设计与实现规格

本文件定义本地可视化操作界面（`src/paperflow/web/`）的完整架构、API 接口、实时进度流协议与页面功能。
启动后在浏览器访问 `http://127.0.0.1:8000`，即可一站式完成**拉取、补录、实时进度监控、历史记录查看、论文检索、在线批注审阅、一键发布与磁盘清理**，全程无需敲命令行。

> **设计原则**：
> 1. **纯 Python 零前端编译**：后端 `FastAPI + Uvicorn`，前端采用 `Jinja2 + Tailwind CSS + Alpine.js + Chart.js + Marked.js`，无需安装 Node.js / npm，DeepSeek Harness 可直接生成且 Windows 下秒级启动。
> 2. **仅限本地运行**：默认只监听 `127.0.0.1`，代码位于 `paper_analysis/src/paperflow/web/`，绝不污染公开的 `paper_repo/`。
> 3. **与 CLI 共享同一套内核**：Web 界面所有操作均直接调用 `pipeline/`、`publisher/` 和 `db/` 核心函数，保证与定时脚本、CLI 行为 100% 一致。

---

## 1. 新增目录结构

```text
src/paperflow/web/
├── __init__.py
├── app.py                     # FastAPI 应用入口、路由注册、静态文件挂载
├── task_manager.py            # 后台异步任务调度器、互斥锁、取消令牌、SSE 进度广播
├── routes/
│   ├── __init__.py
│   ├── dashboard.py           # 首页 KPI、图表数据、水位线状态 API
│   ├── tasks.py               # 启动任务、手动补录、取消任务、SSE 实时流、历史记录 API
│   ├── papers.py              # 论文分页检索、提权/降权、单篇插队、重试、BibTeX API
│   ├── staging.py             # 待审 MD 列表、在线读写/保存、校验、发布与清理 API
│   └── settings.py            # config.yaml 可视化读写、Pydantic 校验、重新打分 API
└── static/
    ├── index.html             # 单页现代化 Dashboard（含左侧导航 + 6 大功能视图）
    ├── app.js                 # Alpine.js 状态管理、SSE 订阅、图表与编辑器逻辑
    └── style.css              # 自定义暗色/亮色样式与日志终端风格

scripts/
└── start_ui.ps1               # 一键启动 Web 控制台并自动打开浏览器
```

---

## 2. 核心引擎：后台任务调度与实时进度流（`web/task_manager.py`）

为了让用户直观看到“当前正在拉取哪一天、下载到第几篇 PDF、进度百分之多少、实时日志输出”，必须实现轻量级任务管理器 `TaskManager`：

### 2.1 进度事件结构（JSON）
```json
{
  "task_id": "task_20261121_083012",
  "command": "fetch",
  "status": "RUNNING",
  "stage": "downloading_pdf",
  "current": 3,
  "total": 8,
  "percent": 37.5,
  "message": "[S级] 正在下载 PDF: arxiv_2611.01234 (3/8)",
  "level": "INFO",
  "timestamp": "2026-11-21T08:30:25+08:00"
}
```

### 2.2 关键机制
1. **并发互斥保护**：`fetch` / `publish` / `clean` 等写操作共用一把全局任务锁（同一时间只允许运行 1 个写任务），防止并发写 SQLite 或冲突操作 Git 仓库；若已有任务在跑，前端按钮自动置灰并高亮当前进度条。
2. **进度回调注入**：在 `backfill.py`、`downloader.py`、`extractor.py`、`sync_blog.py`、`cleaner.py` 中预留可选回调参数 `progress_cb: Callable[[dict], None] | None = None` 与 `cancel_event: threading.Event | None = None`：
   - CLI 运行时传 `None`（走原有 Rich 进度条）。
   - Web 运行时传入 `TaskManager.emit()`，实时推送到内存队列。
3. **SSE 实时推流（`GET /api/tasks/{task_id}/stream`）**：
   - 使用 FastAPI `StreamingResponse(..., media_type="text/event-stream")` 向浏览器持续推送事件，自带断线重连与历史缓冲回放（刷新页面后仍能接着看正在运行的任务进度和日志）。
4. **优雅取消（`POST /api/tasks/{task_id}/cancel`）**：
   - 置位 `cancel_event.set()`，正在运行的循环在当前单篇/单切片安全结束后立刻停止，绝不破坏数据库事务或水位线一致性。
5. **完整落库**：每个任务启动与结束都同步写入 `run_logs` 表，同时把该任务的完整文本日志保存到 `workspace/logs/task_<task_id>.log`，方便事后在页面随时回看。

---

## 3. 六大核心功能页面（个人使用体验最大化）

### 页面 1：总览仪表盘（Dashboard）
- **顶部 KPI 统计卡片（6 项）**：
  - 2026 累计收录数 / 今日新增数
  - S 级精读数 / A 级速览数
  - 当前待分析队列数（`QUEUED`）与待审发布数（`STAGED`）
  - 已发布博客篇数（`PUBLISHED` + `CLEANED`）
  - 当前临时 PDF 占用空间（MB）与累计已释放空间（MB）
- **水位线健康雷达（Catch-up Banner）**：
  - 展示 `job_watermarks` 中 arXiv / OpenAlex / OpenReview 的上次成功日期。
  - 若任意数据源落后于今天，自动弹出醒目提示条（如 *“检测到距离上次拉取已过 3 天”*）并附带 **【一键自动补录】** 按钮。
- **数据可视化图表（Chart.js）**：
  - 柱状图：9 大顶会/顶刊（CVPR / ECCV / ICCV / NeurIPS / ICLR / AAAI / TPAMI / TIP / IJCV）收录量对比（按 S/A/B 堆叠）。
  - 折线图：近 30 天每日入库论文趋势。
- **高频快捷操作栏**：
  - **【一键拉取并导出队列】**、**【一键发布并清理】**、**【查看本地博客预览】**
  - **单篇论文快速插队框**：粘贴任意 arXiv 链接或 DOI + 选择 Venue → 点击【插队精读】，立刻自动抓取并下载 PDF 进入 S 级队列。

### 页面 2：任务中心与实时进度控制台（Task Console）
- **实时任务进度卡片**：
  - 动画进度条（0% ~ 100%）、当前阶段标签（拉取中 → 打分中 → 下载 PDF → 抽取架构图 → 完成）、已用时间、**【停止任务】** 按钮。
- **类终端实时日志窗口（Live Terminal）**：
  - 黑底等宽字体，按 `INFO`（绿/白）、`WARNING`（黄）、`ERROR`（红）着色；支持搜索关键字、按级别过滤、暂停/恢复自动滚底、一键复制日志。
- **可视化手动补录面板（Backfill Panel）**：
  - 起始日期 & 结束日期选择器（Date Picker）
  - Venue 多选标签（全选 / 顶刊 / 顶会 / 单选）
  - 数据源勾选（arXiv / OpenAlex / OpenReview）
  - `Dry-Run（仅试跑不入库）` 开关 → 点击 **【启动补录】** 立即在上方看到实时进度。
- **历史操作记录表（`run_logs`）**：
  - 按时间倒序展示所有**定时任务**和**手动任务**的执行记录（触发来源、命令、日期区间、新增数、S/A 级数、清理数、耗时、状态），点击任意一行可展开查看该次运行的完整日志文件。

### 页面 3：论文总账本（Paper Explorer）
- **多维组合筛选**：搜索框（标题/作者/摘要/UID）+ Venue 下拉 + Tier（S/A/B）+ 状态（全部/待分析/待审/已发布/已清理/失败）+ 仅看有开源代码 + 仅看 Radar 命中。
- **高信息密度列表**：展示标题、Venue 徽章、Tier 徽章、Radar 火焰图标、评分、开源 Star 徽章、状态徽章、PDF 状态（本地已存 / 已安全删除 / 无）。
- **单篇便捷操作（个人科研超实用）**：
  - **一键提权 / 降权**：发现某篇 B 级论文其实很有意思？点 **【升为 S 级】** 自动下载 PDF 并加入精读队列；不感兴趣则点 **【跳过】**。
  - **失败重试**：对 `FAILED` 状态论文点 **【重试】**，页面直接显示失败原因（`last_error`）。
  - **一键复制 BibTeX** / 直达 Paper 原文 / 直达 GitHub 代码仓库。

### 页面 4：待审工作台与在线批注编辑器（Staging Review & Annotator）
DeepSeek Harness + WorkBuddy 分析完写入 `workspace/staging/` 后，这是你每天早上的“5 分钟阅兵场”：
- **左侧待审队列**：按日期分组列出待发论文，显示校验状态（✅ 通过 / ❌ 缺字段）、TL;DR 和抽取出来的 **WebP 架构图缩略图**。
- **右侧双栏 Markdown 编辑器**：
  - 左栏：直接在线编辑 Markdown，提供快捷按钮一键插入 **个人灵感批注块**（`> 💡 个人思考：`）或打星标（`⭐ 必读` / `🔥 计划复现`）。
  - 右栏：基于 `Marked.js` 实时渲染预览，所见即所得（直接预览架构图排版）。
- **底部一键动作**：
  - **【保存并重新校验】**、**【移出发布队列】**、**【一键发布所有通过校验的论文到 GitHub（含自动清理 PDF）】**。

### 页面 5：存储治理与“用完即焚”中心（Storage & Cleanup）
- 实时统计并展示：
  - `workspace/tmp/pdfs/` 文件数量与总大小（MB）
  - `workspace/queue/` 目录数量与总大小（MB）
  - `workspace/state.db` 账本大小（仅几 MB，标注“永久保护”）
- **可清理预览列表（Dry-Run）**：清晰列出哪些已分析/已发布的 PDF 满足安全删除条件、哪些因为未分析完或校验失败而被**自动保护**。
- 提供 **【一键安全清理】** 按钮，执行后实时刷新释放的空间大小。

### 页面 6：可视化配置与兴趣雷达中心（Settings）
- 直接在网页表单中可视化维护 `config/config.yaml`：
  - 增删高/中优先级关键词、排除词（Tag 标签式交互）
  - 增删重点关注学者与机构（Radar）
  - 调整 S/A/B 分数阈值、是否自动 `git push`、Webhook 开关
- 保存前后端自动使用 Pydantic 校验合法性，自动备份 `config/config.yaml.bak` 后再覆盖写入。
- 提供 **【用新规则重新给未分析论文打分】** 按钮，改完关键词立刻生效。

---

## 4. 核心 REST & SSE API 清单

| Method | Path | 说明 |
| :--- | :--- | :--- |
| `GET` | `/api/dashboard/summary` | 获取 KPI 卡片、Venue 分布、30 天趋势、水位线健康度 |
| `POST` | `/api/tasks/fetch` | 启动拉取/补录任务（支持 `date_from`, `date_to`, `venues`, `sources`, `dry_run`） |
| `POST` | `/api/tasks/export-queue` | 启动队列导出任务 |
| `POST` | `/api/tasks/publish` | 启动博客发布任务（支持 `push`, `clean`, `dry_run`） |
| `POST` | `/api/tasks/clean` | 启动安全清理任务（支持 `dry_run`, `include_staged`） |
| `GET` | `/api/tasks/active` | 查询当前正在运行的任务（用于页面刷新后恢复进度条） |
| `GET` | `/api/tasks/{task_id}/stream` | **SSE 实时进度与日志流** |
| `POST` | `/api/tasks/{task_id}/cancel` | 优雅取消正在运行的任务 |
| `GET` | `/api/tasks/history` | 分页查询 `run_logs` 历史操作记录 |
| `GET` | `/api/tasks/history/{log_id}/log` | 读取指定历史任务的详细日志文件内容 |
| `GET` | `/api/papers` | 多条件分页查询论文账本 |
| `POST` | `/api/papers/add` | 单篇 URL/DOI 插队录入 |
| `PATCH` | `/api/papers/{paper_uid}/tier` | 手动调整论文分级（S/A/B）或跳过 |
| `POST` | `/api/papers/{paper_uid}/retry` | 单篇失败重试 |
| `GET` | `/api/papers/{paper_uid}/bibtex` | 获取标准 BibTeX |
| `GET` | `/api/staging` | 获取所有待审论文列表、校验状态与缩略图路径 |
| `GET` / `PUT` | `/api/staging/{paper_uid}` | 读取 / 保存在线编辑后的 Staging Markdown 内容 |
| `DELETE` | `/api/staging/{paper_uid}` | 移除不想发布的 Staging Markdown |
| `GET` | `/api/storage/summary` | 统计临时区大小与可清理文件预览 |
| `GET` / `PUT` | `/api/settings` | 读取 / 校验并保存 `config.yaml` |
| `POST` | `/api/settings/rescore` | 按最新兴趣画像重新给未发布论文打分 |

---

## 5. 启动方式与 CLI 集成

1. **CLI 启动命令**：
   - `paperflow ui`（默认监听 `127.0.0.1:8000`）
   - 支持 `--host 127.0.0.1`、`--port 8000`、`--open`（启动后自动用默认浏览器打开）。
2. **Windows 一键双击脚本（`scripts/start_ui.ps1`）**：
   - 自动激活 `.venv`，启动 `paperflow ui --open`。
3. **新增依赖**（加入 `pyproject.toml`）：
   - `fastapi>=0.115`
   - `uvicorn[standard]>=0.30`
   - `jinja2>=3.1`

---

## 6. Phase 8 验收测试要求（`tests/test_web.py`）

使用 FastAPI `TestClient` 覆盖以下核心测试：
1. `GET /` 返回 `200 OK` 且正确加载主页面；`GET /api/dashboard/summary` 返回完整统计与水位线结构。
2. `POST /api/tasks/fetch`（Mock 模式下）成功返回 `task_id`，重复并发调用返回 `409 Conflict`（验证互斥锁有效）。
3. `GET /api/tasks/{task_id}/stream` 能收到 `RUNNING` 进度事件直至 `SUCCESS` 终态事件，且 `run_logs` 表新增对应记录。
4. `GET /api/papers` 支持按 `venue`、`tier`、`status`、`q` 精准筛选；`PATCH /api/papers/{uid}/tier` 成功将 B 级升为 S 级。
5. `PUT /api/staging/{uid}` 成功保存人工批注后的 Markdown 并通过校验。
6. `PUT /api/settings` 传入非法配置（如 `tier_s < tier_a`）时返回 `422` 且不破坏原 `config.yaml`。
