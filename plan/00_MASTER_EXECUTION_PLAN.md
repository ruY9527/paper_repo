# PaperFlow 2026 — 顶级期刊与会议论文自动化采集、分析与博客发布系统执行计划

> **文档定位**：本目录（`paper_analysis/plan/`）是面向 **DeepSeek Harness** 与开发者的**完整、可执行工程实施蓝图**。
> 请严格按照本主计划的阶段顺序（Phase 1 → Phase 15）逐模块实现代码、编写单元测试并通过验收标准。

---

## 1. 项目愿景与核心目标

构建一套运行在本地 Windows 环境的**全自动学术情报流水线（PaperFlow 2026）**：

1. **多源定时采集**：每天定时从 **IJCV、TIP、TPAMI、CVPR、NeurIPS、AAAI、ICLR、ICCV、ECCV** 9 个顶级期刊/会议获取 2026 年最新论文元数据（结合 OpenAlex / OpenReview / arXiv 多源互补，解决顶会批次放榜与顶刊流式更新的差异）。
2. **持久化账本与断点补录**：本地 SQLite 永久记录每篇论文的拉取、分级、分析、发布与清理状态；支持**关机/断网自动补录**、**指定时间段手动补录**及**单篇链接临时插队**。
3. **本地 AI 分析对接**：自动筛选高价值论文（S/A/B 分级），下载 S 级 PDF、提取核心架构图（WebP）和干净文本，导出标准化任务队列供 **DeepSeek Harness + WorkBuddy** 批量深度分析。
4. **用完即焚的存储治理**：分析完成并通过 Markdown 格式校验后，**自动删除本地大体积 PDF 与临时解析文件**，仅保留轻量 SQLite 账本与最终 Markdown 笔记。
5. **零污染静态博客发布**：本地引擎代码/数据库/临时文件与公开博客仓库完全隔离；一键将审核后的 Markdown、架构图与自动聚合的知识矩阵（会议总表、SOTA 对比表、开源代码库、周报）同步并推送至 GitHub Pages 自动渲染。

---

## 2. 计划文档索引（请按顺序阅读）

| 文档 | 内容说明 | 对应实现阶段 |
| :--- | :--- | :--- |
| [00_MASTER_EXECUTION_PLAN.md](./00_MASTER_EXECUTION_PLAN.md) | 总体架构、目录规范、技术栈、分阶段执行清单与工程红线 | 全局总纲 |
| [01_DATA_MODEL_AND_CONFIG.md](./01_DATA_MODEL_AND_CONFIG.md) | `config.yaml` 完整配置规范、SQLite 表结构 DDL、状态机与去重规则 | Phase 1 |
| [02_FETCHER_BACKFILL_AND_SCORER.md](./02_FETCHER_BACKFILL_AND_SCORER.md) | 多源拉取器、自动/手动补录引擎、开源代码嗅探、兴趣雷达与 S/A/B 分级 | Phase 2 & 3 |
| [03_ANALYSIS_QUEUE_AND_CLEANUP.md](./03_ANALYSIS_QUEUE_AND_CLEANUP.md) | PDF 下载、架构图抽取、DeepSeek Harness/WorkBuddy 队列协议、安全删除 | Phase 4 & 5 |
| [04_BLOG_PUBLISH_AND_AUTOMATION.md](./04_BLOG_PUBLISH_AND_AUTOMATION.md) | MkDocs-Material 静态博客、知识矩阵聚合、一键发布、Windows 定时任务与通知 | Phase 6 & 7 |
| [05_LOCAL_WEB_UI_DASHBOARD.md](./05_LOCAL_WEB_UI_DASHBOARD.md) | 本地 Web 控制台（FastAPI + SSE 实时进度 + 历史记录 + 在线批注 + 配置中心） | Phase 8 |
| [06_WEB_GIT_PUBLISH_AND_HISTORY.md](./06_WEB_GIT_PUBLISH_AND_HISTORY.md) | Web 端 Git SSH 免密一键提交推送、Diff 预览、提交历史与推送审计中心 | Phase 9 |
| [07_TOPIC_DRIVEN_SEARCH_AND_RECENCY.md](./07_TOPIC_DRIVEN_SEARCH_AND_RECENCY.md) | 研究方向精准检索（中英文/组合词扩展、2026 优先 + 2025 兜底、Web 方向探索页） | Phase 10 |
| [08_AI_ANALYZER_CLAUDE_AND_HARNESS.md](./08_AI_ANALYZER_CLAUDE_AND_HARNESS.md) | AI 自动解析引擎（Claude CLI + Kimi K3 全自动批量解析 & DeepSeek Harness Web 协作桥接） | Phase 11 |
| [09_BLOG_PREVIEW_GATE_AND_PROMPT_STUDIO.md](./09_BLOG_PREVIEW_GATE_AND_PROMPT_STUDIO.md) | 发布前本地 `mkdocs --strict` 门禁与一键预览 + Prompt 模板工作室（按方向自动路由） | Phase 12 |
| [10_PAYWALL_FILTER_AND_MANUAL_PDF_HUB.md](./10_PAYWALL_FILTER_AND_MANUAL_PDF_HUB.md) | 受限出版商（IEEE/Springer 等）过滤名单、受限论文独立账本与手动补传闭环 | Phase 13 |
| [11_SITE_BOOKMARKS_AND_NAV_HUB.md](./11_SITE_BOOKMARKS_AND_NAV_HUB.md) | 个人科研与工具网站收录中心（自动抓元信息、书签导入、死链巡检、博客卡片导航页） | Phase 14 |
| [12_PIPELINE_CLOSURE_AND_BUGFIX.md](./12_PIPELINE_CLOSURE_AND_BUGFIX.md) | 全链路闭环收口与 10 处核心断链修复（跨天发布、单篇入队、Paywall 闭环、图链与清理修复） | Phase 15 |

---

## 3. 总体目录架构（本地引擎与公开博客彻底分离）

```text
paper_analysis/                      # 【本地工作区：不推送到博客公仓】
├── plan/                            # 本执行计划文档目录
├── config/
│   ├── config.yaml                  # 用户主配置文件（关键词、学者雷达、路径等）
│   └── config.example.yaml          # 配置模板（不含敏感 Webhook/Token）
├── src/
│   └── paperflow/
│       ├── __init__.py
│       ├── cli.py                   # 统一命令行入口（Typer）
│       ├── config.py                # 配置加载与 Pydantic 校验
│       ├── db/
│       │   ├── __init__.py
│       │   ├── models.py            # 数据类与状态枚举
│       │   └── repository.py        # SQLite 建表、CRUD、水位线与事务管理
│       ├── fetchers/
│       │   ├── __init__.py
│       │   ├── base.py              # BaseFetcher 抽象基类与限流重试封装
│       │   ├── arxiv_fetcher.py     # arXiv 每日增量 + 顶会/顶刊 comment 匹配
│       │   ├── openalex_fetcher.py  # OpenAlex（TPAMI/TIP/IJCV 及顶会）
│       │   ├── openreview_fetcher.py# OpenReview（ICLR/NeurIPS）
│       │   └── single_adder.py      # 单篇 URL/arXiv/DOI 插队录入
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── backfill.py          # 自动补录（水位线追赶）与区间补录调度器
│       │   ├── dedup.py             # 论文 UID 生成与标准化去重
│       │   ├── scorer.py            # 兴趣打分、学者雷达、代码嗅探、S/A/B 分级
│       │   ├── downloader.py        # S 级 PDF 原子下载与校验
│       │   ├── extractor.py         # PyMuPDF 文本提取 + 核心架构图 WebP 抽取
│       │   ├── queue_exporter.py    # 导出 DeepSeek Harness/WorkBuddy 任务队列
│       │   ├── md_validator.py      # 分析结果 MD 格式与 Frontmatter 严格校验
│       │   └── cleaner.py           # 校验通过后的 PDF 与临时文件安全清理
│       ├── publisher/
│       │   ├── __init__.py
│       │   ├── aggregator.py        # 自动生成顶会总表、SOTA 矩阵、开源库、周报
│       │   ├── sync_blog.py         # 同步 MD/图片到 blog_repo 并执行 Git 推送
│       │   ├── git_service.py       # blog_repo 专用 Git/SSH 免密操作与历史查询封装
│       │   └── digest.py            # 生成每日人工速览清单 TODAY_DIGEST.md
│       ├── utils/
│       │   ├── __init__.py
│       │   ├── logger.py            # Rich 控制台 + 按天轮转日志文件
│       │   ├── bibtex.py            # 标准 BibTeX 生成器
│       │   └── notifier.py          # Windows 桌面通知 + 飞书/钉钉 Webhook
│       └── web/                     # 【本地 Web 控制台（仅限本地运行）】
│           ├── app.py               # FastAPI 应用入口
│           ├── task_manager.py      # 后台任务互斥调度 + SSE 实时进度与日志流
│           ├── routes/              # Dashboard / Tasks / Papers / Staging / Settings / Git API
│           └── static/              # 轻量无构建前端（Tailwind + Alpine.js + Chart.js）
├── workspace/                       # 【运行时数据目录：全部加入 .gitignore】
│   ├── state.db                     # SQLite 永久状态账本（核心资产，严禁误删）
│   ├── logs/                        # 运行日志（按天滚动）
│   ├── tmp/                         # 热数据临时区（分析校验通过后自动删除）
│   │   └── pdfs/                    # 临时下载的 PDF
│   ├── queue/                       # 待 DeepSeek Harness/WorkBuddy 分析队列
│   │   └── YYYY-MM-DD/<paper_uid>/  # meta.json + extracted_text.md + prompt.md
│   └── staging/                     # 分析完成后的待审缓冲区（支持人工微调批注）
│       ├── YYYY-MM-DD/
│       │   ├── TODAY_DIGEST.md      # 当日速览清单
│       │   └── <paper_uid>.md       # 生成的论文精读/速览 Markdown
│       └── assets/<paper_uid>/      # 抽取的轻量 WebP 架构图
├── paper_repo/                       # 【独立公开 Git 仓库：仅提交静态博客与 MD】
│   ├── .github/workflows/deploy.yml # GitHub Actions 自动部署 GitHub Pages
│   ├── mkdocs.yml                   # MkDocs-Material 站点配置
│   ├── requirements-docs.txt        # 仅文档构建依赖
│   └── docs/
│       ├── index.md                 # 首页看板（最新动态 + 年度统计）
│       ├── papers/2026/<venue>/     # 单篇论文分析 MD
│       ├── assets/<paper_uid>/      # 论文核心架构图（WebP）
│       ├── venues/                  # 各顶会/顶刊年度总表（自动生成）
│       ├── matrix/                  # SOTA 对比表、开源代码精选（自动生成）
│       └── weekly/                  # 每周趋势周报（自动生成）
├── scripts/
│   ├── run_daily_fetch.ps1          # 每日定时拉取脚本（含自动补录）
│   ├── install_task.ps1             # 一键注册 Windows 任务计划程序
│   └── start_ui.ps1                 # 一键启动本地 Web 控制台并打开浏览器
├── tests/                           # 完整 pytest 单元测试与集成测试
├── pyproject.toml                   # Python 项目与依赖管理
└── .gitignore
```

---

## 4. 技术栈选型（Windows 友好、零多余重依赖）

- **Python**: `>= 3.10`
- **CLI 框架**: `typer[all]` + `rich`（彩色表格、进度条、清晰子命令）
- **网络与容灾**: `httpx` + `tenacity`（指数退避重试、超时与限流控制）
- **配置与校验**: `pydantic>=2.0` + `pyyaml`
- **数据库**: Python 内置 `sqlite3`（开启 WAL 模式，无额外数据库服务依赖）
- **PDF 解析与抽图**: `PyMuPDF` (`fitz`) + `Pillow`（极快提取文本与首页/方法图并压缩为 WebP）
- **Markdown 解析**: `python-frontmatter`
- **静态博客**: `mkdocs-material` + `pymdown-extensions`（纯 Python 生态，零 Node.js 环境冲突，原生支持数学公式、Mermaid 图、全文检索、标签筛选与暗色模式）
- **本地 Web 控制台**: `fastapi` + `uvicorn[standard]` + `jinja2` + SSE 实时进度流 + 零构建前端（Tailwind CSS / Alpine.js / Chart.js / Marked.js）
- **测试**: `pytest` + `pytest-mock` + `respx`（Mock HTTP 响应）

---

## 5. DeepSeek Harness 分阶段执行路线图

请严格按以下 7 个 Phase 顺序开发，**每完成一个 Phase 必须运行对应测试并通过后，再进入下一个 Phase**：

- **Phase 1：项目初始化、配置系统与 SQLite 账本**
  - 建立目录结构、`pyproject.toml`、`.gitignore`、`config/config.example.yaml`、`config/config.yaml`。
  - 实现 `config.py`、`db/models.py`、`db/repository.py`、`utils/logger.py`。
  - **验收标准**：`pytest tests/test_db.py tests/test_config.py` 全部通过；建表幂等、状态流转与水位线读写正确。

- **Phase 2：多源论文采集器与去重引擎**
  - 实现 `pipeline/dedup.py`、`fetchers/base.py`、`arxiv_fetcher.py`、`openalex_fetcher.py`、`openreview_fetcher.py`、`single_adder.py`。
  - **验收标准**：使用 Mock 响应跑通 `pytest tests/test_fetchers.py tests/test_dedup.py`，验证去重优先级（DOI > arXiv ID > 标题哈希）及 9 大目标 Venue 的映射正确性。

- **Phase 3：自动/手动补录调度器 + 兴趣打分与代码嗅探**
  - 实现 `pipeline/backfill.py` 与 `pipeline/scorer.py`（关键词加权、学者/机构雷达、GitHub 链接提取、S/A/B 分级）。
  - **验收标准**：模拟“停机 5 天”场景，验证自动补录按天切片拉取并仅在成功后推进水位线；`pytest tests/test_backfill.py tests/test_scorer.py` 全部通过。

- **Phase 4：PDF 原子下载、文本/架构图抽取与分析队列导出**
  - 实现 `pipeline/downloader.py`、`pipeline/extractor.py`、`pipeline/queue_exporter.py`、`utils/bibtex.py`。
  - **验收标准**：能为 S 级论文下载 PDF、抽取压缩后的 WebP 架构图与干净文本，并输出结构完整的 `workspace/queue/YYYY-MM-DD/<paper_uid>/` 任务包。

- **Phase 5：分析结果校验器与“用完即焚”安全清理**
  - 实现 `pipeline/md_validator.py`、`pipeline/cleaner.py`、`publisher/digest.py`。
  - **验收标准**：验证合法 MD 通过校验并安全删除临时 PDF 且写入 `pdf_deleted=1`；验证非法/空 MD 会拦截删除并保留 PDF 以便重试。

- **Phase 6：静态博客骨架、知识矩阵聚合与一键发布**
  - 初始化 `paper_repo/`（`mkdocs.yml`、`deploy.yml`、首页模板）。
  - 实现 `publisher/aggregator.py`（Venue 总表、SOTA 矩阵、开源精选、周报）与 `publisher/sync_blog.py`。
  - **验收标准**：执行 `paperflow publish --dry-run` 与 `mkdocs build --strict` 零报错。

- **Phase 7：统一 CLI、Windows 定时任务与通知集成**
  - 组装 `cli.py` 所有命令，实现 `utils/notifier.py`，编写 `scripts/run_daily_fetch.ps1` 与 `scripts/install_task.ps1`。
  - **验收标准**：跑通端到端 Smoke Test（`fetch --dry-run` → `status` → `export-queue` → `validate` → `publish --no-push` → `clean --dry-run`）。

- **Phase 8：本地 Web 控制台（PaperFlow Studio）**
  - 实现 `web/task_manager.py`（后台互斥任务队列 + 取消令牌 + SSE 实时进度与日志流）、`web/routes/` 全部 REST API 与 `web/static/` 6 大可视化页面，接入 `paperflow ui` 与 `scripts/start_ui.ps1`。
  - **验收标准**：`pytest tests/test_web.py` 全绿；浏览器访问 `http://127.0.0.1:8000` 可完成补录、实时进度监控、历史记录回看、待审在线批注、发布与清理。

- **Phase 9：Web 端 Git SSH 免密一键提交与历史可视化中心**
  - 扩展 SQLite `git_push_logs` 表，实现 `publisher/git_service.py`（SSH 免密非交互执行、Diff 预览、`git log` 解析）、`web/routes/git_ops.py` 及前端第 7 页【Git 发布中心】。
  - **验收标准**：`pytest tests/test_git_ops.py`（基于本地 Bare 仓库全离线模拟）全绿；在 Web 端可检测 SSH 连通性、查看待提交 Diff、一键发布并推送 GitHub、回看完整 Commit 历史与推送审计记录。

- **Phase 10：研究方向精准检索与近两年时效优先策略**
  - 平滑迁移 SQLite（`discovery_mode`、`topic_tags_json`、`topic_search_runs`），实现 `pipeline/topic_query.py`（中英文+组合词扩展）、`fetchers/topic_fetcher.py`（2026 优先 + 2025 兜底 + 严禁 ≤2024）、CLI（`topic-search` / `topic-run` / `topic-list`）、博客专题聚合页及 Web 第 8 页【方向精准检索】。
  - **验收标准**：`pytest tests/test_topic_search.py` 与全量回归测试 100% 通过。

- **Phase 11：AI 论文自动解析引擎（Claude CLI + Kimi K3 & DeepSeek Harness Web 协作）**
  - 新增 `analysis_runs` 表，实现 `analyzers/`（`claude_cli_analyzer.py` 非交互批量调用 + Markdown 清洗 + 校验自修复重试、`openai_api_analyzer.py`、`runner.py`）、CLI（`analyze` / `analyzer-check`）、`web/routes/analyzer.py` 及前端第 9 页【AI 解析中心】（含 DeepSeek Harness Web 一键复制/粘贴回填协作）。
  - **验收标准**：`pytest tests/test_analyzer.py` 与全量回归测试 100% 通过。

- **Phase 12：发布前本地 MkDocs 严格门禁预览 & Prompt 模板工作室**
  - 实现 `publisher/mkdocs_service.py`（临时目录 `mkdocs build --strict` 门禁 + `mkdocs serve` 单实例本地预览与进程回收）、`pipeline/prompt_manager.py`（`config/prompts/` 外部模板 + 方向自动路由 + 防 LaTeX 花括号安全渲染）、CLI 与 Web 端【Prompt 模板工作室】及【Git 发布中心】预览门禁集成。
  - **验收标准**：`pytest tests/test_preview_and_prompts.py` 与全量回归测试 100% 通过。

- **Phase 13：受限出版商过滤名单（IEEE 等需登录源）、受限论文独立账本与手动补传闭环**
  - 平滑扩展 `papers.access_type` 与独立表 `paywall_papers`，实现 `pipeline/paywall_filter.py`（域名拦截 + arXiv 同名开放版抢救 + 动态 403/HTML 登录墙兜底）、`pipeline/manual_pdf.py`（单篇上传校验 + `inbox_pdfs/` 批量扫描匹配 + 清单导出）、CLI 与 Web 端【受限论文清单（Paywall Hub）】页面。
  - **验收标准**：`pytest tests/test_paywall.py` 与全量回归测试 100% 通过。

- **Phase 14：个人科研与工具网站收录中心 & 博客导航页自动渲染**
  - 新增 SQLite `site_categories` 与 `collected_sites` 表，实现 `src/paperflow/sites/`（URL 标准化与 HTML 元信息抓取、多行 URL 与浏览器书签 HTML 导入、死链巡检、MkDocs-Material 卡片/表格导航页渲染与 `mkdocs.yml` 自动挂载）、CLI 与 Web 端【网站收录中心】页面。
  - **验收标准**：`pytest tests/test_sites.py`（含隐私隔离与 `mkdocs build --strict` 门禁验证）及全量回归测试 100% 通过。

- **Phase 15：全链路闭环收口与核心断链修复**
  - 按 `12_PIPELINE_CLOSURE_AND_BUGFIX.md` 逐项修复 10 处断链（跨天发布、插队/升S/重试自动入队、Paywall 抢救与补传闭环、三套发布逻辑统一、架构图路径归一化、清理器相对路径修复、重新打分豁免方向论文、KPI 口径与导航同步、脏测试数据清理与测试隔离）。
  - **验收标准**：`pytest tests/test_pipeline_closure.py` 与全量 `pytest -v` 100% 通过且零污染真实目录。

---

## 6. 工程实现红线（DeepSeek Harness 必读）

1. **Windows 编码兼容**：所有文件读写必须显式指定 `encoding="utf-8"`；所有路径操作统一使用 `pathlib.Path`，严禁硬编码 `/` 或 `\` 拼接。
2. **原子写入**：下载 PDF 与写入关键 Markdown/JSON 时，先写入 `.tmp` / `.part` 文件，校验成功后再 `os.replace()` 重命名，防止断电导致半截损坏文件。
3. **绝对幂等**：同一天重复运行 `fetch`、`export-queue`、`publish`、`clean` 任意多次，不能产生重复数据库记录、重复博客文章或异常崩溃。
4. **绝不误删**：清理器（`cleaner.py`）永远不得删除 `workspace/state.db` 或 `paper_repo/` 中的文件；仅允许删除 `workspace/tmp/` 和已确认入库的 `workspace/queue/` 子目录。
5. **敏感信息隔离**：Webhook URL、GitHub Token 等只允许通过环境变量或本地未提交的 `config.yaml` 读取，绝不写入代码或 `paper_repo/`。
6. **礼貌抓取**：对所有外部 API 强制执行请求间隔（arXiv >= 3s，OpenAlex >= 0.5s，OpenReview >= 1s）并设置规范的 `User-Agent`。
