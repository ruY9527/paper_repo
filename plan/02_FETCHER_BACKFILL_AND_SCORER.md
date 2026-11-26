# Phase 2 & 3：多源论文采集、自动/手动补录引擎与兴趣分级

本文件定义 `src/paperflow/fetchers/`、`src/paperflow/pipeline/backfill.py` 与 `src/paperflow/pipeline/scorer.py` 的精确设计规格。

---

## 1. 统一采集器接口（`fetchers/base.py`）

定义统一的标准数据对象 `RawPaper`（Pydantic Model）和抽象基类 `BaseFetcher`：

```python
class RawPaper(BaseModel):
    title: str
    authors: list[str]
    affiliations: list[str] = []
    venue: str                     # 标准化简称: CVPR/ECCV/ICCV/NeurIPS/ICLR/AAAI/TPAMI/TIP/IJCV
    pub_year: int
    pub_date: str | None = None    # YYYY-MM-DD
    source: str                    # arxiv | openalex | openreview | manual
    doi: str | None = None
    arxiv_id: str | None = None
    openreview_id: str | None = None
    abstract: str = ""
    comment: str = ""
    paper_url: str = ""
    pdf_url: str = ""
    code_url: str = ""
    project_url: str = ""
```

`BaseFetcher` 必须内置：
- **通用 HTTP 客户端**：使用 `httpx.Client(timeout=30.0, follow_redirects=True)`，统一设置 `User-Agent: PaperFlow2026/1.0 (mailto:...)`。
- **请求限流器（RateLimiter）**：按每个源的 `rate_limit_seconds` 自动节流。
- **指数退避重试（`tenacity`）**：针对 `HTTP 429`、`5xx`、网络超时自动重试 3 次（退避 `2s → 4s → 8s`）。
- 抽象方法：`fetch_by_date_range(self, start_date: date, end_date: date, venues: list[str] | None = None) -> list[RawPaper]`。

---

## 2. 三个核心数据源实现规格

### 2.1 `ArxivFetcher`（每日新鲜论文主力源）
- **API 端点**：`https://export.arxiv.org/api/query`（Atom XML 解析，使用 `xml.etree.ElementTree`）。
- **查询构造**：
  - 分类过滤：`(cat:cs.CV OR cat:cs.LG OR cat:cs.AI OR cat:cs.CL OR cat:cs.RO)`
  - 时间过滤：`AND submittedDate:[YYYYMMDD0000 TO YYYYMMDD2359]`
  - 分页：每次 `max_results=100`，翻页直到返回空或达到 `max_results_per_slice`。
- **顶会/顶刊匹配逻辑**：
  - 检查每条记录的 `arxiv:comment` 和 `arxiv:journal_ref` 字段。
  - 遍历 `config.yaml` 中所有 9 个 Venue 的 `arxiv_patterns` 正则（忽略大小写）。
  - 命中后，校验年份：若为会议，正则已包含 2026（或 ICCV 2025/2026）；若为期刊（TPAMI/TIP/IJCV），只要 `submittedDate` 或 `updated` 在 2026 年即视为 2026 论文。
  - **过滤规则**：未命中任何目标 Venue 正则的普通预印本直接丢弃，不污染账本。
  - 自动构造 `pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"`。

### 2.2 `OpenAlexFetcher`（顶刊 TPAMI / TIP / IJCV 与正式发表权威源）
- **API 端点**：`https://api.openalex.org/works`
- **查询参数**：
  - 按 `config.yaml` 中期刊的 `issns` 聚合过滤：
    `filter=primary_location.source.issn:0162-8828|1939-3539|1057-7149|1941-0042|0920-5691|1573-1405,from_publication_date:YYYY-MM-DD,to_publication_date:YYYY-MM-DD`
  - 同时支持带 `mailto` 参数进入 Polite Pool。
  - 使用 `cursor=*` 游标分页，拉取完整结果集。
- **摘要还原**：OpenAlex 返回的是 `abstract_inverted_index`（倒排索引字典），需实现辅助函数 `reconstruct_abstract(inverted_index)` 按位置索引还原为完整英文摘要。
- **PDF 链接提取**：优先取 `best_oa_location.pdf_url`，其次取 `open_access.oa_url`。
- **机构提取**：从 `authorships[].institutions[].display_name` 去重汇总到 `affiliations`。

### 2.3 `OpenReviewFetcher`（ICLR 2026 / NeurIPS 2026 一手源）
- **API 端点**：`https://api2.openreview.net/notes`
- **查询逻辑**：
  - 读取配置中带 `openreview_venue_id` 的会议（如 `ICLR.cc/2026/Conference`、`NeurIPS.cc/2026/Conference`）。
  - 按 `content.venueid` 过滤已录用论文（跳过 Rejected / Withdrawn）。
  - 若会议尚未放榜（API 返回空列表或 404），**必须优雅降级**（记录 INFO 日志并返回 `[]`，绝不阻塞其他数据源）。
  - 从 `content.venue.value` 中保留 Oral / Spotlight / Poster 信息写入 `comment`。

### 2.4 `SinglePaperAdder`（单篇链接临时插队：`paperflow add --url ...`）
支持用户随时手动录入一篇论文：
- 识别 `arxiv.org/abs/...` 或 `arxiv.org/pdf/...` → 提取 arXiv ID 调 arXiv API 获取元数据。
- 识别 `doi.org/...` 或纯 DOI 字符串 → 调 OpenAlex `/works/https://doi.org/...` 获取元数据。
- 支持 `--venue` 手动覆盖（如 `--venue CVPR`），且**自动强制标为 S 级**（因为是用户主动精选想看的论文），直接进入下载与分析队列。

---

## 3. 自动补录与手动补录引擎（`pipeline/backfill.py`）

这是保证“电脑关机几天也不漏数据”的核心模块。

### 3.1 自动补录算法（`paperflow fetch` 默认模式）
对每个启用的 `(source_name, venue_key)`：
1. 查询 `job_watermarks` 表获取 `last_success_date`。
2. 确定起始日期 `start_date`：
   - 若无历史水位线（首次运行）：`start_date = today - default_lookback_days`。
   - 若有水位线：`start_date = last_success_date + 1 day`。
   - 若 `start_date > today`：说明今天已拉取完毕，打印“已是最新”并跳过（除非用户传入 `--force`）。
3. **安全保护**：如果 `today - start_date > max_auto_catchup_days`（默认 60 天），打印警告并自动截断为最近 60 天，同时提示用户可用 `fetch --from ... --to ...` 手动分段补录更早日期。
4. **按天切片执行（Slice Loop）**：
   - 将 `[start_date, today]` 按 `max_slice_days`（默认 5 天）切分成若干连续子区间 `[s_i, e_i]`。
   - 逐个子区间执行拉取 → 去重入库 → 打分分级。
   - **关键事务原则**：**只有当整个子区间无异常完成时，才将水位线推进到 `e_i`**。若第 2 个子区间网络中断，水位线停留在第 1 个子区间的末尾，下次运行自动从断点续传。

### 3.2 手动补录模式（`paperflow fetch --from YYYY-MM-DD --to YYYY-MM-DD`）
- 允许用户指定任意历史时间区间和 `--venue CVPR,TPAMI`、`--source arxiv,openalex`。
- **注意**：手动补录历史区间时，**不要回退**现有的 `last_success_date` 水位线（仅当 `to_date > last_success_date` 时才向前推进）。

---

## 4. 代码嗅探与兴趣分级引擎（`pipeline/scorer.py`）

对所有状态为 `FETCHED` 的新论文执行以下步骤，完成后状态置为 `SCORED`（B 级直接置为 `SKIPPED`）：

### 4.1 开源代码与项目主页嗅探
- 在 `abstract` + `comment` 中用正则提取：
  - GitHub / GitLab / HuggingFace 代码链接 → 写入 `code_url`
  - `*.github.io` / 项目主页链接 → 写入 `project_url`
- **可选 Star 数查询**：若提取到 `github.com/<owner>/<repo>`，可调用 GitHub REST API 获取 `stargazers_count`（若配置了环境变量 `GITHUB_TOKEN` 则携带，否则匿名调用；遇 403 限流时静默跳过，绝不报错中断）。

### 4.2 多维度打分公式
将 `title + " " + abstract + " " + comment` 拼接并转为小写，计算总分 `score`：
1. **高优先级关键词**：每命中 1 个 `+30` 分（该项累计上限 `60` 分），记录到 `matched_tags`。
2. **中优先级关键词**：每命中 1 个 `+15` 分（该项累计上限 `30` 分），记录到 `matched_tags`。
3. **排除关键词**：每命中 1 个 `-50` 分。
4. **学者/机构雷达（Radar）**：
   - `authors` 命中 `tracked_authors` → `+25` 分，`is_radar_hit = 1`。
   - `affiliations` 命中 `tracked_affiliations` → `+15` 分，`is_radar_hit = 1`。
5. **额外加分项**：
   - `code_url` 非空 → `+15` 分。
   - `comment` 命中 `oral|spotlight|best paper|highlight`（忽略大小写）→ `+20` 分，`is_radar_hit = 1`。

### 4.3 S / A / B 三档分级与流向
- **`score >= 50`（或手动 `add`）→ `S` 级（精读）**：自动下载 PDF、提取文本与核心架构图，送入 DeepSeek Harness 深度拆解。
- **`25 <= score < 50` → `A` 级（速览）**：不下载 PDF，仅基于 Title + Abstract 生成结构化中文速览卡片。
- **`score < 25` → `B` 级（归档）**：状态标记为 `SKIPPED`，仅保留在 SQLite 账本与年度 Venue 总表中，不消耗分析 Token。

---

## 5. Phase 2 & 3 验收测试要求

1. `tests/test_fetchers.py`：使用 `respx` Mock arXiv Atom XML、OpenAlex JSON（含倒排索引摘要）和 OpenReview JSON，验证解析字段完整、无目标 Venue 的普通 arXiv 论文被正确过滤。
2. `tests/test_backfill.py`：模拟上次成功日期为 12 天前、`max_slice_days=5`，验证自动切分为 3 个批次执行；模拟第 2 批次抛异常时，水位线准确停在第 1 批次末尾，第 3 批次不被跳过。
3. `tests/test_scorer.py`：验证关键词打分、排除词降权、学者雷达标记、GitHub URL 提取以及 S/A/B 分级边界值完全符合预期。
