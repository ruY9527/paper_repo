# Phase 14：个人科研与工具网站收录中心 & 博客导航页自动渲染

> **背景说明**：本文件为增量新功能规格书（Phase 14），在**完全兼容 Phase 1 ~ Phase 13** 的前提下，为 PaperFlow 增加**“后台收录网站 + 自动渲染到公开博客导航页”**能力，让你的 GitHub Pages 站点同时成为个人专属的**论文精读库 + 高颜值科研/AI/工具网站导航站**。

---

## 1. 核心架构与新增模块

```text
src/paperflow/sites/
├── __init__.py
├── metadata_fetcher.py        # 轻量 HTML 元信息抓取（标题、简介、Favicon）+ URL 标准化去重
├── bookmark_importer.py       # 批量 URL 与 Chrome/Edge 标准 bookmarks.html 导入解析
├── health_checker.py          # 异步/批量网站可达性（死链）巡检
└── blog_renderer.py           # 生成 MkDocs-Material 卡片/表格导航页 + 自动更新 mkdocs.yml

src/paperflow/web/routes/
└── sites.py                   # 网站收录中心全部 REST API + SSE 批量任务路由
```

---

## 2. 配置扩展（`config/config.yaml` 新增 `sites` 节点）

Pydantic 提供完整默认值，确保旧配置文件 100% 向后兼容：

```yaml
sites:
  enabled: true
  blog_layout: "cards"                 # cards（MkDocs-Material 卡片网格，默认）| table（紧凑表格）
  hide_dead_links_in_blog: false       # true 时自动隐藏 health_status == 'DEAD' 的失效网站
  fetch_timeout_seconds: 10.0          # 自动抓取网页标题/简介超时秒数
  health_check_timeout_seconds: 8.0    # 死链巡检超时秒数
  health_check_concurrency: 5          # 死链巡检并发数
```

---

## 3. 数据库平滑扩展（SQLite 独立表，零破坏）

在 `db/repository.py` 初始化时幂等建表，并自动初始化 6 个默认分类（若 `site_categories` 为空）：

### 3.1 `site_categories` 表（网站分类表）

```sql
CREATE TABLE IF NOT EXISTS site_categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,           -- 如 "AI 与大模型"
    slug        TEXT NOT NULL UNIQUE,           -- 如 "ai-llm"
    icon        TEXT DEFAULT '🔗',              -- Emoji 或图标标识
    description TEXT DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 100,   -- 越小越靠前
    created_at  TEXT NOT NULL
);
```

预置默认分类：
1. `AI 与大模型`（`ai-llm`, `🤖`, `sort_order=10`）
2. `论文与学术`（`academic-papers`, `📚`, `sort_order=20`）
3. `数据集与基准`（`datasets-benchmarks`, `📊`, `sort_order=30`）
4. `开源项目与框架`（`open-source`, `🛠️`, `sort_order=40`）
5. `效率与科研工具`（`productivity-tools`, `⚡`, `sort_order=50`）
6. `优质技术博客`（`tech-blogs`, `✍️`, `sort_order=60`）

### 3.2 `collected_sites` 表（收录网站主表）

```sql
CREATE TABLE IF NOT EXISTS collected_sites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,              -- 原始提交 URL
    normalized_url  TEXT NOT NULL UNIQUE,       -- 标准化防重 URL（见第 4.1 节）
    domain          TEXT NOT NULL,              -- 如 "huggingface.co"
    title           TEXT NOT NULL,
    description     TEXT DEFAULT '',            -- 网页简介（自动抓取或手改）
    personal_note   TEXT DEFAULT '',            -- 个人推荐语 / 使用心得
    category_id     INTEGER NOT NULL REFERENCES site_categories(id),
    tags_json       TEXT NOT NULL DEFAULT '[]', -- JSON 数组 ["免费", "Agent", "遥感"]
    favicon_url     TEXT DEFAULT '',            -- 自动解析的 Favicon URL
    rating          INTEGER DEFAULT 0,          -- 可选推荐星级 0~5
    is_pinned       INTEGER NOT NULL DEFAULT 0, -- 1=置顶精选（展示在博客导航页最顶部）
    is_public       INTEGER NOT NULL DEFAULT 1, -- 1=发布到公开博客, 0=仅本地后台私密收藏
    health_status   TEXT NOT NULL DEFAULT 'UNKNOWN',
    -- UNKNOWN | OK | SLOW | DEAD
    http_status     INTEGER DEFAULT NULL,       -- 最近一次巡检 HTTP 状态码
    last_checked_at TEXT DEFAULT NULL,          -- ISO 8601
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sites_category ON collected_sites(category_id);
CREATE INDEX IF NOT EXISTS idx_sites_public_pinned ON collected_sites(is_public, is_pinned);
CREATE INDEX IF NOT EXISTS idx_sites_health ON collected_sites(health_status);
```

---

## 4. 核心功能模块设计

### 4.1 URL 标准化与元信息自动抓取（`sites/metadata_fetcher.py`）

1. **URL 标准化（`normalize_url(raw_url: str) -> tuple[str, str]`）**：
   - 自动补全缺失协议（默认 `https://`），仅允许 `http` / `https` 协议（拒绝 `javascript:` / `file:` 等非法协议）。
   - 主机名转小写；移除常见追踪查询参数（`utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`, `spm`, `from`）；去除无意义末尾斜杠（根路径除外）与 `#fragment`。
   - 返回 `(normalized_url, domain)` 用于入库防重。
2. **轻量 HTML 元信息解析（零重依赖）**：
   - 使用 `httpx.Client(timeout=fetch_timeout_seconds, follow_redirects=True)` 发起 GET 请求（带常见浏览器 `User-Agent`，流式读取前 256KB 防止大文件 OOM）。
   - 使用 Python 标准库 `html.parser.HTMLParser` 提取：
     - `<title>` 或 `<meta property="og:title">`
     - `<meta name="description">` 或 `<meta property="og:description">`
     - `<link rel="icon" ...>` / `<link rel="shortcut icon" ...>`，通过 `urllib.parse.urljoin` 转为绝对 URL；若未声明则兜底为 `https://<domain>/favicon.ico`。
   - **优雅降级**：若目标站超时、403 或反爬拦截，**绝不抛 500 异常**，而是返回 `{ok: False, title: domain, description: "", favicon_url: ..., warning: "无法自动抓取，请手动补全标题"}`，让用户顺利完成收录。

### 4.2 批量 URL 与浏览器书签导入（`sites/bookmark_importer.py`）

1. **多行 URL 批量导入**：按行解析 URL 列表，去重后逐条抓取元信息并入库（走 `TaskManager` + SSE 实时进度，支持单条失败不中断整批）。
2. **Chrome / Edge 标准 `bookmarks.html` 导入**：
   - 使用标准库 `html.parser` 解析 Netscape Bookmark HTML 格式（`<H3>` 文件夹名 → `<A HREF="...">标题</A>`）。
   - 文件夹名自动匹配已有分类（或可选自动创建新分类 / 归入指定默认分类），已存在的 `normalized_url` 自动跳过并统计 `skipped_duplicates`。

### 4.3 死链巡检引擎（`sites/health_checker.py`）

- 对所有已收录网站（或指定分类）并发执行轻量探测（优先 `HEAD`，遇 `405 Method Not Allowed` 自动回退 `GET` 流式只读响应头）：
  - `200 <= status < 400` 且耗时 `<= 3s` → `OK`
  - `200 <= status < 400` 且耗时 `> 3s` → `SLOW`
  - `status >= 400`（如 404/410/5xx）或连接/超时异常 → `DEAD`
- 通过 `progress_cb` 推送 SSE 进度，实时更新 `health_status`、`http_status` 与 `last_checked_at`。

### 4.4 博客导航页自动渲染器（`sites/blog_renderer.py`）

与 `publisher/aggregator.py` 无缝联动（在 `paperflow publish` 和独立 `paperflow site-sync` 时均自动执行）：

1. **安全更新 `paper_repo/mkdocs.yml`（幂等不破坏原有配置）**：
   - 确保 `markdown_extensions` 中包含 `attr_list` 和 `md_in_html`（MkDocs-Material 卡片网格 `grid cards` 必需扩展）。
   - 确保 `nav:` 顶层包含 `- 网站导航: sites/index.md`（若已存在则不重复添加，保留其余所有导航项不变）。
2. **严格隐私过滤**：
   - **只查询 `is_public == 1` 的记录**；`is_public == 0` 的私密收藏**绝对不能出现在任何生成的 Markdown 文件中**！
   - 若配置 `hide_dead_links_in_blog: true`，自动跳过 `health_status == 'DEAD'` 的记录。
3. **生成 `paper_repo/docs/sites/index.md`**：
   - 顶部统计栏：共公开收录 X 个网站、覆盖 Y 个分类、最后同步日期。
   - **⭐ 精选置顶区**（筛选 `is_pinned == 1`）：始终采用 MkDocs-Material 高颜值 `grid cards` 卡片网格展示：
     ```markdown
     <div class="grid cards" markdown>

     -   **🤖 [Hugging Face](https://huggingface.co){ target="_blank" }**

         ---

         开源大模型、数据集与 Demo 托管社区。

         > 💡 个人心得：日常找开源权重和论文 Demo 的首选站点。

         `AI 与大模型` · `免费` · `开源`

     </div>
     ```
   - **各分类分区**（按 `site_categories.sort_order` 顺序生成 `## 🤖 AI 与大模型` 等二级标题，自动接入右侧 TOC 目录树）：
     - `blog_layout == "cards"`：同样使用 `<div class="grid cards" markdown>` 卡片布局。
     - `blog_layout == "table"`：生成紧凑 Markdown 表格（列：网站名称与直链、简介、个人心得、标签）。
   - **字符安全转义**：所有写入 Markdown 表格或卡片的 `title`、`description`、`personal_note` 必须转义 `|` 与换行符，防止破坏 Markdown 渲染导致 `mkdocs build --strict` 报错。
4. **首页联动（`paper_repo/docs/index.md`）**：
   - 在首页总览看板中增加“收录网站总数”统计项与跳转至 `[网站导航](sites/index.md)` 的快捷卡片。

---

## 5. CLI 新增命令（`src/paperflow/cli.py`）

| 命令 | 参数选项 | 功能说明 |
| :--- | :--- | :--- |
| `paperflow site-add` | `URL`, `--category`, `--title`, `--note`, `--tags`, `--pin`, `--private`, `--no-fetch` | 收录单个网站（默认自动抓标题与简介） |
| `paperflow site-list` | `--category`, `--public-only`, `--dead-only`, `--q` | Rich 表格展示已收录网站列表 |
| `paperflow site-check` | `--category` | 执行死链巡检并更新可达性状态 |
| `paperflow site-sync` | `--layout cards\|table` | 重新生成 `paper_repo/docs/sites/index.md` 并确保 `mkdocs.yml` 导航已挂载 |

---

## 6. Web 控制台新增页面：页面 12 — 网站收录中心（Site Hub）

在 `src/paperflow/web/routes/sites.py` 实现完整 API，并在 `index.html` 左侧导航栏新增 **【网站收录中心】**：

### 6.1 新增 REST API（`src/paperflow/web/routes/sites.py`）

| Method | Path | 说明 |
| :--- | :--- | :--- |
| `POST` | `/api/sites/fetch-meta` | 输入 URL，自动抓取并返回标题、简介、Favicon 与标准化结果（用于表单预填） |
| `GET` | `/api/sites` | 分页/条件查询网站列表（`category_id`, `is_public`, `is_pinned`, `health_status`, `tag`, `q`）+ 顶部统计 |
| `POST` | `/api/sites` | 新增收录网站（自动标准化防重，重复返回 `409 Conflict`） |
| `PUT` | `/api/sites/{site_id}` | 编辑网站信息（标题、简介、心得、分类、标签、置顶、公开/私密、星级） |
| `DELETE` | `/api/sites/{site_id}` | 删除已收录网站 |
| `POST` | `/api/sites/batch-import-urls` | 批量粘贴多行 URL 导入（走 `TaskManager` + SSE 进度） |
| `POST` | `/api/sites/import-bookmarks` | 上传 Chrome/Edge `bookmarks.html` 批量导入 |
| `POST` | `/api/sites/health-check` | 启动一键死链巡检（走 `TaskManager` + SSE 进度） |
| `POST` | `/api/sites/sync-blog` | 一键同步生成博客导航页（可选返回 `mkdocs build --strict` 校验结果） |
| `GET` / `POST` / `PUT` / `DELETE` | `/api/sites/categories`（及 `/{cat_id}`） | 分类增删改查与排序管理 |

### 6.2 前端界面布局
1. **顶部快速收录栏（极速 3 秒入库）**：
   - URL 输入框 + **【🔍 自动抓取信息】** 按钮 → 自动填充标题、简介与图标预览。
   - 分类下拉框、标签输入、个人心得输入、星级选择、**置顶精选**开关、**公开到博客**开关（默认开启）→ 点击 **【➕ 收录保存】**。
2. **顶部快捷工具条**：
   - **【📥 批量导入（多行 URL / 浏览器书签）】** 弹窗
   - **【🩺 一键死链巡检】**（带 SSE 进度条）
   - **【🏷️ 分类管理】** 弹窗
   - 布局切换（`卡片网格` / `紧凑表格`）+ **【🔄 同步到博客导航页】**（同步后直接提供快捷跳转【Git 发布中心】或【本地预览 `:8001`】）。
3. **主列表展示区**：
   - 筛选栏：分类胶囊、公开/私密、仅看置顶、仅看失效链接、关键词搜索。
   - 列表每项显示：Favicon 图标、可点击标题、域名、分类徽章、标签、个人心得、公开/私密徽章（`🌐 公开` / `🔒 私密`）、健康状态灯（绿/黄/红）、以及 **【置顶】**、**【公开切换】**、**【编辑】**、**【删除】** 快捷操作按钮。

---

## 7. Phase 14 验收测试要求（`tests/test_sites.py`）

1. **URL 标准化与去重测试**：
   - 验证 `https://HuggingFace.co/?utm_source=twitter` 与 `https://huggingface.co` 归一化一致，重复收录触发去重拦截；非法协议 `javascript:alert(1)` 被拒绝。
2. **HTML 元信息抓取 Mock 测试**：
   - Mock 正常 HTML 页面提取 `<title>`、`description` 与 `favicon`；Mock 超时/403 时平滑降级不抛异常。
3. **浏览器书签 HTML 导入测试**：
   - 构造标准 Chrome `bookmarks.html`（含 2 个文件夹 + 3 条链接 + 1 条重复链接），验证正确导入、分类自动映射、重复项跳过。
4. **隐私隔离与博客严格构建测试（核心必测）**：
   - 插入 2 条 `is_public=1`（其中 1 条 `is_pinned=1`）和 1 条 `is_public=0`（含敏感词 `"SECRET_INTERNAL_PORTAL"`）的网站，运行 `sync-blog`：
     - 断言 `paper_repo/docs/sites/index.md` 包含 2 条公开网站且置顶项位于精选区；
     - 断言 `"SECRET_INTERNAL_PORTAL"` **绝对不出现在** `sites/index.md` 中；
     - 断言 `paper_repo/mkdocs.yml` 已自动包含 `attr_list`、`md_in_html` 与 `网站导航: sites/index.md`；
     - 在 `paper_repo/` 上执行 `mkdocs build --strict` 断言**零警告零报错通过**。
5. **死链巡检、Web API 与全量回归测试**：
   - Mock `200` / `404` / 超时验证 `health_status` 准确更新为 `OK` / `DEAD`；测试 `/api/sites/*` 全套 CRUD 与同步接口；最后运行全量 `pytest -v` 确认 Phase 1 ~ Phase 14 全部 100% 通过无回归。
