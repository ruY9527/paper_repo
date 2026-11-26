# Phase 13：受限出版商过滤名单（IEEE 等需登录源）、受限论文独立账本与手动补传闭环

> **背景说明**：本文件为增量新功能规格书（Phase 13），在**完全兼容 Phase 1 ~ Phase 12** 的前提下，专门解决 **IEEE Xplore（TPAMI / TIP / TGRS）、Springer（IJCV）、Elsevier（Information Fusion）、ACM DL** 等需要机构登录/付费墙才能下载 PDF 的现实痛点：
> 1. **事前域名过滤（不盲目下载）**：命中受限域名名单且无合法开放获取镜像（如 arXiv）的论文，**不尝试下载、不触发 403/HTML 报错、不污染失败重试队列**；
> 2. **独立表格与专属 Web 页面永久留痕**：在 SQLite 中新建独立表 `paywall_papers`，并在 Web 控制台新增 **【受限论文清单（Paywall Hub）】** 页面集中记录与管理；
> 3. **进阶闭环能力**：支持 **arXiv 同名开放版自动抢救**、**一键跳转官网下载**、**单篇拖拽补传本地 PDF（自动抽图+精读+发布后照样用完即焚）**、**批量导出待下载清单 + 扫描本地目录自动匹配 PDF** 以及 **一键转摘要速览**。

---

## 1. 配置扩展（`config/config.yaml` 新增 `download_policy` 节点）

在 `config/config.yaml` 与 `config/config.example.yaml` 追加以下配置（Pydantic 提供完整默认值，向后兼容）：

```yaml
download_policy:
  enable_paywall_filter: true          # 开启受限域名过滤，命中后跳过下载并写入 paywall_papers 表
  auto_try_arxiv_rescue: true          # 命中受限域名前，先尝试按标题精确匹配 arXiv 开放预印本
  auto_classify_html_403_as_paywall: true  # 未在名单内但返回 401/403/HTML 登录页时，自动归入受限表而非死循环重试
  manual_inbox_dir: "./workspace/inbox_pdfs"  # 批量补传本地 PDF 的收件箱目录

  # 默认需登录/付费墙域名过滤名单（支持子域名匹配，可在 Web 界面动态增删）
  paywall_domains:
    - domain: "ieeexplore.ieee.org"
      publisher: "IEEE Xplore"
      note: "TPAMI / TIP / TGRS 等需机构账号或校园网登录"
    - domain: "link.springer.com"
      publisher: "Springer"
      note: "IJCV 等需机构登录"
    - domain: "sciencedirect.com"
      publisher: "Elsevier"
      note: "Information Fusion / Pattern Recognition 等"
    - domain: "dl.acm.org"
      publisher: "ACM DL"
      note: "ACM 期刊与会议"
    - domain: "onlinelibrary.wiley.com"
      publisher: "Wiley"
      note: "Wiley 期刊"
    - domain: "tandfonline.com"
      publisher: "Taylor & Francis"
      note: "遥感/工程类期刊"
```

---

## 2. 数据库平滑扩展（独立表 `paywall_papers` + `papers` 兼容列）

在 `db/repository.py` 初始化时通过 `PRAGMA table_info(papers)` 平滑迁移，**绝不破坏现有数据**：

### 2.1 `papers` 表新增 1 列
```sql
ALTER TABLE papers ADD COLUMN access_type TEXT NOT NULL DEFAULT 'open';
-- 允许值: open（开放可直下） | paywall_blocked（命中受限名单，未下载） | manual_uploaded（用户手动补传 PDF）
```

### 2.2 新增独立账本表 `paywall_papers`
专门以结构化表格记录所有被拦截不下载的受限论文及其后续人工处理状态：

```sql
CREATE TABLE IF NOT EXISTS paywall_papers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_uid           TEXT NOT NULL UNIQUE REFERENCES papers(paper_uid) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    venue               TEXT NOT NULL,
    pub_year            INTEGER NOT NULL,
    tier                TEXT NOT NULL DEFAULT 'S',
    publisher           TEXT NOT NULL,              -- 如 "IEEE Xplore" / "Springer" / "Elsevier"
    domain              TEXT NOT NULL,              -- 如 "ieeexplore.ieee.org"
    landing_url         TEXT DEFAULT '',            -- 论文官网/DOI 直达链接（方便一键跳转登录下载）
    blocked_pdf_url     TEXT DEFAULT '',            -- 被拦截的原始 PDF URL
    doi                 TEXT DEFAULT '',
    block_reason        TEXT NOT NULL,              -- domain_blacklist | http_403_login_wall | non_pdf_html
    oa_rescue_status    TEXT NOT NULL DEFAULT 'NOT_TRIED',
    -- NOT_TRIED | RESCUED_ARXIV | NOT_FOUND
    manual_status       TEXT NOT NULL DEFAULT 'PENDING_MANUAL',
    -- PENDING_MANUAL（待人工处理）| ABSTRACT_ONLY（已转摘要速览）| PDF_UPLOADED（已补传本地 PDF）| IGNORED（已忽略）
    note                TEXT DEFAULT '',            -- 用户个人备注（如“等连校园 VPN 一起下”）
    detected_at         TEXT NOT NULL,              -- ISO 8601
    resolved_at         TEXT DEFAULT NULL           -- 处理完成时间
);

CREATE INDEX IF NOT EXISTS idx_paywall_manual_status ON paywall_papers(manual_status);
CREATE INDEX IF NOT EXISTS idx_paywall_publisher ON paywall_papers(publisher);
CREATE INDEX IF NOT EXISTS idx_paywall_venue_year ON paywall_papers(venue, pub_year);
```

---

## 3. 核心过滤与进阶抢救/补传引擎

### 3.1 受限域名检测与过滤服务（`src/paperflow/pipeline/paywall_filter.py`）

封装 `PaywallFilter(config, repo)`，在 `downloader.py` 执行真实 HTTP 下载**之前**调用：

1. **域名匹配逻辑 `match_paywall(url: str) -> PaywallRule | None`**：
   - 使用 `urllib.parse.urlparse(url).netloc.lower()` 提取主机名，匹配 `paywall_domains`（支持精确匹配与后缀子域名匹配，如 `*.ieee.org`）。
   - 同时检查 `paper.pdf_url` 和 `paper.paper_url`（若 `pdf_url` 为空但 `paper_url` 属于 IEEE/Springer，也直接判定为受限论文）。
2. **步骤 1 — 智能开放获取抢救（OA Rescue，优先找合法免费源）**：
   - 若论文自带 `arxiv_id`，直接使用 `https://arxiv.org/pdf/{arxiv_id}.pdf`，**放行下载**，不进受限表。
   - 若 `pdf_url` 本身指向非受限开放域（如 `arxiv.org`、`openaccess.thecvf.com`、`openreview.net`、`hal.science`），直接**放行下载**。
   - 若命中受限域名且开启 `auto_try_arxiv_rescue: true`：
     - 调用 arXiv API 按标题精确查询（限流保护），对比 `normalize_title(candidate.title) == paper.normalized_title`（完全一致才认领，防止张冠李戴！）。
     - **抢救成功**：回填 `arxiv_id` 与 `pdf_url = https://arxiv.org/pdf/{id}.pdf`，记录日志 `OA Rescue succeeded via arXiv`，直接**放行自动下载**！
3. **步骤 2 — 拦截并登记至 `paywall_papers` 表（绝不发起无效下载）**：
   - 若无开放镜像，**跳过下载**：
     - 更新 `papers.access_type = 'paywall_blocked'`（保持 `status = 'SCORED'`，绝不标记为 `FAILED`，不浪费重试次数）。
     - 幂等写入 `paywall_papers` 表（`manual_status = 'PENDING_MANUAL'`，`block_reason = 'domain_blacklist'`）。
     - 通过日志 / SSE 明确输出：`[Paywall Filter] 跳过需登录下载 (IEEE Xplore): <title> -> 已登记至受限论文清单`。
4. **步骤 3 — 运行时动态兜底拦截（修改 `downloader.py`）**：
   - 对于不在名单中的未知域名，若下载时返回 HTTP `401` / `403` 或响应头不是 PDF（返回 HTML 登录页），当 `auto_classify_html_403_as_paywall: true` 时，自动调用 `PaywallFilter.record_blocked(...)` 登记到 `paywall_papers`（`block_reason = 'http_403_login_wall'`），并在页面提示“建议将该域名加入受限过滤名单”。

### 3.2 本地 PDF 手动补传与批量收件箱匹配（`src/paperflow/pipeline/manual_pdf.py`）

1. **单篇手动上传绑定（`attach_local_pdf(paper_uid, pdf_bytes_or_path)`）**：
   - 严格校验前 4 字节为 `%PDF` 且大小 `<= max_pdf_size_mb`。
   - 原子写入 `workspace/tmp/pdfs/<paper_uid>.pdf`。
   - 立即调用现有 `extractor.py` 提取干净文本与 WebP 架构图。
   - 更新账本：
     - `papers`: `tier = 'S'`, `status = 'DOWNLOADED'`, `access_type = 'manual_uploaded'`, `pdf_local_path = ...`, `pdf_deleted = 0`
     - `paywall_papers`: `manual_status = 'PDF_UPLOADED'`, `resolved_at = now`
   - 后续自动进入 `export-queue` → Claude CLI / DeepSeek Harness 精读 → 发布 → **发布完成后同样按“用完即焚”规则自动删除临时 PDF**！
2. **批量收件箱自动匹配（`scan_inbox_pdfs()`）**：
   - 用户连上校园 VPN 后，从 IEEE/Springer 批量下载多篇 PDF 直接扔进 `workspace/inbox_pdfs/` 文件夹。
   - 扫描该目录所有 `.pdf` 文件，按以下优先级自动与 `paywall_papers`（`PENDING_MANUAL`）配对：
     1. 文件名直接包含 `paper_uid`（如 `doi_a1b2c3d4e5f6.pdf`）；
     2. 用 `PyMuPDF` 读取 PDF 第 1 页文本，提取 DOI 正则匹配数据库 `doi`；
     3. 用 PDF 第 1 页前 500 字符标准化后与待处理论文的 `normalized_title` 做子串/高相似度（>= 0.85）匹配。
   - 匹配成功后自动调用 `attach_local_pdf()` 完成绑定并移走原文件（防重复扫描），返回详细匹配报告（成功绑定几篇、未匹配几篇）。
3. **一键导出待下载清单（`export_pending_checklist(fmt="markdown" | "csv")`）**：
   - 导出所有 `PENDING_MANUAL` 论文为 Markdown 或 CSV（含标题、Venue、年份、出版商、可直接点击的 DOI/官网链接、建议保存文件名 `<paper_uid>.pdf`），方便连上校园网集中下载。

---

## 4. 博客聚合联动（`publisher/aggregator.py` 微调）

在生成 `paper_repo/docs/venues/<VENUE>-2026.md`（如 `TPAMI-2026.md`、`TIP-2026.md`、`IJCV-2026.md`）时：
- 若某篇论文 `access_type == 'paywall_blocked'` 且尚未发布精读文章，在总表状态列清晰标注 `🔒 需登录/待补传` 并附带官网/DOI 原文链接，确保年度顶刊追踪表依然完整无缺漏。

---

## 5. CLI 新增命令（`src/paperflow/cli.py`）

| 命令 | 参数选项 | 功能说明 |
| :--- | :--- | :--- |
| `paperflow paywall-list` | `--status PENDING_MANUAL`, `--publisher IEEE` | Rich 表格展示所有被过滤拦截的受限论文清单 |
| `paperflow paywall-rescue` | `--paper-uid`, `--all-pending` | 对待处理的受限论文尝试按标题搜寻 arXiv 同名开放版 |
| `paperflow paywall-attach` | `PAPER_UID`, `PDF_PATH` | 手动将本地下载好的 PDF 绑定到指定受限论文并自动抽图 |
| `paperflow paywall-scan-inbox` | 无 | 扫描 `workspace/inbox_pdfs/` 自动匹配并绑定批量下载的 PDF |
| `paperflow paywall-export` | `--format md\|csv`, `--output` | 导出待人工下载清单（含官网直链与建议文件名） |

---

## 6. Web 控制台新增页面：页面 11 — 受限论文清单（Paywall Hub）

在 `src/paperflow/web/routes/paywall.py` 实现完整 API，并在 `index.html` 左侧导航栏新增 **【受限论文清单】**（当存在 `PENDING_MANUAL` 论文时显示琥珀色数字角标）：

### 6.1 新增 REST API（`src/paperflow/web/routes/paywall.py`）

| Method | Path | 说明 |
| :--- | :--- | :--- |
| `GET` | `/api/paywall/papers` | 分页查询 `paywall_papers`（支持按 `publisher` / `venue` / `manual_status` / `q` 筛选）+ 顶部统计卡片 |
| `POST` | `/api/paywall/papers/{paper_uid}/rescue` | 对单篇受限论文触发 arXiv 同名开放版抢救 |
| `POST` | `/api/paywall/papers/{paper_uid}/upload-pdf` | `multipart/form-data` 上传本地 PDF，自动校验、抽图并升级为可精读状态 |
| `POST` | `/api/paywall/papers/{paper_uid}/fallback-abstract` | 标记为 `ABSTRACT_ONLY`，不下载 PDF，直接以摘要速览方式进入分析队列 |
| `PATCH` | `/api/paywall/papers/{paper_uid}` | 更新 `manual_status`（如 `IGNORED`）或个人备注 `note` |
| `POST` | `/api/paywall/scan-inbox` | 扫描 `workspace/inbox_pdfs/` 批量自动匹配绑定本地 PDF |
| `GET` | `/api/paywall/export` | 一键下载待处理清单文件（`?format=csv` 或 `?format=md`） |
| `GET` / `PUT` | `/api/paywall/domains` | 读取 / 动态维护 `download_policy.paywall_domains` 过滤名单（写回 `config.yaml`） |

### 6.2 前端界面布局
1. **顶部统计与批量工具栏**：
   - 统计卡片：待人工处理数（按 IEEE / Springer / Elsevier 分布）、已通过 arXiv 抢救数、已手动补传 PDF 数、已转摘要速览数。
   - 快捷按钮组：
     - **【📥 导出待下载清单 (MD/CSV)】**
     - **【📂 扫描本地补传目录 (`inbox_pdfs/`)】**
     - **【⚙️ 管理受限域名名单】**（弹窗可视化增删如 `ieeexplore.ieee.org`、`link.springer.com` 等域名）
2. **受限论文专属表格（核心展示区）**：
   - 多维筛选栏：出版商下拉（全部 / IEEE Xplore / Springer / Elsevier / ACM）、Venue、年份、处理状态（默认显示 `待人工处理`）、关键字搜索。
   - 表格列：论文标题（含 DOI）、Venue & 年份、Tier、出版商徽章（如蓝色 `IEEE Xplore`、橙色 `Springer`）、拦截原因、当前状态、以及**单行动作按钮组**：
     - **【🔗 官网下载】**：新标签页直达 IEEE/Springer 论文页（配合你本地浏览器/校园 VPN 下载）。
     - **【🔎 搜 arXiv】**：一键尝试抢救同名开放预印本。
     - **【📤 补传 PDF】**：点击或直接拖拽 PDF 文件到该行 → 立刻上传校验、抽图并送入待分析队列！
     - **【📝 转摘要速览】**：不想下 PDF 时一键走 A 级摘要分析。
     - **【🚫 忽略】**：归档隐藏。

---

## 7. Phase 13 验收测试要求（`tests/test_paywall.py`）

1. **域名过滤拦截测试**：
   - 构造一条 `pdf_url="https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=12345"` 的 TPAMI S 级论文（无 `arxiv_id`），运行下载流程：
     - 断言**不发起任何向 `ieeexplore.ieee.org` 的 HTTP 下载请求**；
     - 断言 `papers.access_type == 'paywall_blocked'` 且 `papers.status != 'FAILED'`；
     - 断言 `paywall_papers` 表自动新增记录（`publisher == 'IEEE Xplore'`, `manual_status == 'PENDING_MANUAL'`）。
2. **arXiv 开放版抢救测试**：
   - Mock arXiv API 返回与 IEEE 论文标题完全一致的预印本 → 断言抢救成功、回填 `arxiv_id` 并正常放行下载。
3. **动态 403/HTML 登录墙兜底测试**：
   - Mock 某未知域名返回 `403` 或 `text/html` 登录页 → 断言自动登记入 `paywall_papers`（`block_reason == 'http_403_login_wall'`）而非标记 `FAILED`。
4. **手动补传 PDF 与批量收件箱匹配测试**：
   - 用 `PyMuPDF` 生成真实测试 PDF（含标题/DOI 与图片），分别测试 `POST /api/paywall/papers/{uid}/upload-pdf` 与 `POST /api/paywall/scan-inbox`：
     - 断言校验 `%PDF` 成功、抽取文本与 WebP 图成功、`manual_status == 'PDF_UPLOADED'`、`papers.status == 'DOWNLOADED'`；
     - 上传非 PDF 伪造文件返回 `400` 拒绝。
5. **转摘要速览与域名名单动态修改测试**：
   - 测试 `fallback-abstract`、`export`（CSV/MD）、`GET/PUT /api/paywall/domains` 全部通过；
   - 运行全量 `pytest -v` 确认 Phase 1 ~ Phase 13 全部 100% 通过无回归。
