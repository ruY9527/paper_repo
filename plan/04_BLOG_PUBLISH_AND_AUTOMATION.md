# Phase 6 & 7：静态博客架构、知识矩阵聚合、一键发布与 Windows 定时自动化

本文件定义 `paper_repo/`、`src/paperflow/publisher/`、`src/paperflow/cli.py`、`src/paperflow/utils/notifier.py` 及 `scripts/` 的精确设计规格。

---

## 1. 静态博客仓库设计（`paper_repo/` — 纯净公开仓库）

`paper_repo/` 是一个**完全独立的 Git 仓库**，只存放 MkDocs 配置、GitHub Actions 部署脚本、最终发布的 Markdown 和轻量 WebP 架构图，不包含任何爬虫脚本、SQLite 数据库或 PDF。

### 1.1 `paper_repo/mkdocs.yml` 标准配置

```yaml
site_name: "PaperFlow 2026 — 顶会顶刊论文精读库"
site_description: "2026 CVPR / ECCV / NeurIPS / ICLR / AAAI / TPAMI / TIP / IJCV 自动化追踪与深度解析"
theme:
  name: material
  language: zh
  palette:
    - scheme: default
      primary: indigo
      accent: cyan
      toggle:
        icon: material/brightness-7
        name: 切换暗色模式
    - scheme: slate
      primary: indigo
      accent: cyan
      toggle:
        icon: material/brightness-4
        name: 切换亮色模式
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.top
    - search.suggest
    - search.highlight
    - content.code.copy

plugins:
  - search
  - tags

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
  - pymdownx.arithmatex:
      generic: true
  - pymdownx.tabbed:
      alternate_style: true
  - tables
  - toc:
      permalink: true

extra_javascript:
  - https://unpkg.com/mathjax@3/es5/tex-mml-chtml.js
```

### 1.2 `paper_repo/.github/workflows/deploy.yml`（全自动部署 GitHub Pages）

```yaml
name: Deploy PaperFlow Blog
on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements-docs.txt
      - run: mkdocs gh-deploy --force
```

`paper_repo/requirements-docs.txt` 仅需两行：
```text
mkdocs-material>=9.5
pymdown-extensions>=10.7
```

---

## 2. 知识矩阵与自动聚合页面生成器（`publisher/aggregator.py`）

每次执行 `paperflow publish` 时，直接查询本地 `workspace/state.db`（`papers` + `paper_metrics` 两表联合），自动重新生成以下 Markdown 汇总页面并写入 `paper_repo/docs/`（幂等覆盖，无需手工维护）：

1. **首页看板（`docs/index.md`）**：
   - 年度总览统计卡片：已收录总数、S 级精读数、A 级速览数、带开源代码论文数、最近更新时间。
   - 各顶会/顶刊收录数量进度表（9 个 Venue 一览）。
   - 最近发布的 15 篇高价值论文列表（带跳转链接与 TL;DR）。
2. **各顶会/顶刊年度总表（`docs/venues/<VENUE>-2026.md`）**：
   - 列出该会议/期刊 2026 年所有已入库论文（S/A 级带站内精读链接，B 级带外部 Paper 原文链接），按日期倒序排列，含 `Tier`、`Code`、`TL;DR` 列。
3. **跨论文 SOTA 对比矩阵（`docs/matrix/sota-2026.md`）**：
   - 读取 `paper_metrics` 表，按 `task` 分组生成对比表格（列：论文标题、Venue、Backbone、Datasets、关键 SOTA 指标、创新标签）。
4. **2026 开源代码精选库（`docs/matrix/open-source-2026.md`）**：
   - 筛选 `code_url != ''` 的所有论文，按 `code_stars`（或发布日期）降序排列，一键直达代码仓库。
5. **每周趋势周报（`docs/weekly/<YYYY>-W<ww>.md`）**：
   - 按 ISO 周自动归档本周所有已发布的 S/A 级论文、高频关键词 Top 10、以及本周热门方向统计。

---

## 3. 博客同步与 Git 自动发布器（`publisher/sync_blog.py`）

执行 `paperflow publish [--push] [--clean] [--dry-run]` 的完整流程：

1. 先调用 `md_validator.validate_all_staged()`，确保所有待发文档通过校验。
2. 将 `workspace/staging/YYYY-MM-DD/<paper_uid>.md` 复制到：
   `paper_repo/docs/papers/2026/<VENUE>/<paper_uid>.md`（自动修正图片相对路径为 `../../../assets/<paper_uid>/fig_1.webp`）。
3. 将 `workspace/staging/assets/<paper_uid>/*.webp` 复制到 `paper_repo/docs/assets/<paper_uid>/`。
4. 调用 `aggregator.rebuild_all()` 刷新首页、Venue 总表、SOTA 矩阵、开源库与周报。
5. 将已同步的论文在 SQLite 中更新为 `status = 'PUBLISHED'`、`md_blog_path = 'papers/2026/...'`。
6. **Git 操作**（若 `--dry-run` 则仅打印变更文件清单，不执行写入和 Git）：
   - 检测 `paper_repo/` 是否已初始化为 Git 仓库且有变更（`git status --porcelain`）。
   - 若有变更且启用 `auto_git_commit`：执行 `git add -A` 与 `git commit -m "docs: publish {N} papers ({date})"`。
   - 若传入 `--push`（或配置 `auto_git_push: true`）：执行 `git push`。
7. 若传入 `--clean`（或配置 `auto_clean_after_publish: true`）：调用 `cleaner.clean_published()` 自动删除已发布论文的临时 PDF 与队列目录，更新状态为 `CLEANED`。

---

## 4. 统一 CLI 命令设计（`src/paperflow/cli.py`）

使用 `Typer` + `Rich` 打造清晰易用的命令行入口（安装后可通过 `paperflow ...` 或 `python -m paperflow ...` 调用）：

| 命令 | 参数选项 | 功能说明 |
| :--- | :--- | :--- |
| `paperflow init` | `--config` | 初始化工作区目录、SQLite 数据库、配置模板与 `paper_repo/` 骨架 |
| `paperflow fetch` | `--from`, `--to`, `--venue`, `--source`, `--force`, `--dry-run` | 拉取最新论文；不传日期时自动按水位线补录所有缺漏天数，并自动打分、下载 S 级 PDF、抽图 |
| `paperflow add` | `--url`, `--venue` | 单篇论文临时插队（arXiv URL / DOI），强制标为 S 级并立即准备分析包 |
| `paperflow export-queue` | `--date`, `--limit` | 导出待 DeepSeek Harness / WorkBuddy 分析的任务队列与 `queue_manifest.json` |
| `paperflow validate` | `--date` | 校验 `staging/` 中生成的 MD，提取 `metrics` 入库并生成 `TODAY_DIGEST.md` |
| `paperflow publish` | `--push`, `--clean`, `--dry-run` | 校验并同步至 `paper_repo/`、刷新知识矩阵、提交/推送 GitHub、自动清理 PDF |
| `paperflow clean` | `--dry-run`, `--include-staged` | 安全清理已分析/已发布论文的临时 PDF 与队列目录 |
| `paperflow status` | `--venue`, `--failed` | Rich 彩色看板：展示 9 大 Venue 收录数、各状态统计、水位线日期、失败重试列表 |
| `paperflow retry-failed` | `--max-retries` | 重新拉取/下载此前标记为 `FAILED` 的论文 |
| `paperflow ui` | `--host`, `--port`, `--open` | 启动本地 Web 控制台（PaperFlow Studio），在浏览器可视化操作与监控实时进度 |

---

## 5. Windows 定时自动化与运行简报（`scripts/` & `utils/notifier.py`）

### 5.1 定时拉取脚本（`scripts/run_daily_fetch.ps1`）
- 自动激活项目虚拟环境（`.venv\Scripts\Activate.ps1`）。
- 依次执行：
  1. `paperflow fetch`（自动补录关机期间缺漏天数 + 去重 + 打分 + 下载 S 级 PDF + 抽图）
  2. `paperflow export-queue`（把今天新抓到的 S/A 级论文打包进 `workspace/queue/YYYY-MM-DD/`）
- 记录完整输出到 `workspace/logs/daily_YYYY-MM-DD.log`。
- 结束时调用 `notifier.py` 发送极简播报：
  - **Windows 桌面通知**（优先使用 `winotify` 或 PowerShell 原生 Toast，失败时静默降级到日志）
  - **可选 Webhook**（飞书/钉钉卡片，仅当环境变量 `PAPERFLOW_WEBHOOK_URL` 存在时触发）
  - 播报内容示例：`PaperFlow 日报：补录 2 天，新增 16 篇（S 级 3 篇，A 级 7 篇），待 DeepSeek 分析队列已就绪。`

### 5.2 一键注册 Windows 任务计划（`scripts/install_task.ps1`）
- 使用 `Register-ScheduledTask` 创建名为 `PaperFlow_Daily_Fetch` 的定时任务（默认每天 `08:00` 执行）。
- **关键参数**：必须启用 `New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries`。
  - **效果**：即使早上 8 点电脑关机，只要之后任意时间一开机，Windows 任务计划会自动补跑 `run_daily_fetch.ps1`，配合内置水位线引擎实现**双重防漏保障**。

---

## 6. 最终端到端验收清单（DeepSeek Harness 交付标准）

在宣布项目实现完成前，必须全部通过以下验证：

1. **单元测试全绿**：运行 `pytest -v`，覆盖 `db`、`config`、`dedup`、`fetchers`、`backfill`、`scorer`、`extractor`、`validator`、`cleaner`、`aggregator`、`sync_blog`，通过率 100%。
2. **离线端到端冒烟测试**：
   - 运行 `paperflow init` 成功创建工作区与 `paper_repo/`。
   - 构造 Mock 数据模拟 1 篇 S 级论文 + 1 篇 A 级论文 + 1 篇 B 级论文入库。
   - 运行 `paperflow export-queue` 成功生成 `queue_manifest.json`、`meta.json`、`extracted_text.md`、`prompt.md`。
   - 模拟写入合法的 `staging/` Markdown 文件，运行 `paperflow validate` 生成 `TODAY_DIGEST.md` 且写入 `paper_metrics`。
   - 运行 `paperflow publish --clean`（不加 `--push`），验证：
     - `paper_repo/docs/` 下文章、WebP 图片、首页看板、Venue 总表、SOTA 矩阵、开源库均已生成。
     - `workspace/tmp/pdfs/` 下对应 PDF 已被自动删除，且 SQLite 中 `status = 'CLEANED'`、`pdf_deleted = 1`。
     - `paper_repo` 执行 `mkdocs build --strict` 零警告零报错通过。
3. **联网连通性自检（可选）**：运行 `paperflow fetch --from 2026-11-18 --to 2026-11-20 --dry-run` 验证真实 API 请求可正常返回且无编码/解析异常。
