# Phase 4 & 5：PDF 下载、架构图抽取、DeepSeek Harness 队列协议与“用完即焚”清理

本文件定义本地 AI 分析的上下游衔接协议，确保 **PaperFlow 引擎** 与 **DeepSeek Harness / WorkBuddy** 完全解耦、稳定协作，并在分析校验通过后安全释放磁盘空间。

---

## 1. S 级 PDF 原子下载器（`pipeline/downloader.py`）

- **作用对象**：`tier == 'S'` 且 `status == 'SCORED'` 且 `pdf_url` 非空的论文。
- **保存路径**：`workspace/tmp/pdfs/<paper_uid>.pdf`。
- **安全与容错规范**：
  1. 流式下载到 `<paper_uid>.pdf.part`，先检查 `Content-Length` 是否超过 `max_pdf_size_mb`（默认 50MB），超限则跳过并记录日志。
  2. 下载完成后校验文件头前 4 字节必须为 `%PDF`（防止把 HTML 登录页/反爬页当成 PDF 保存）。
  3. 校验通过后执行 `os.replace()` 重命名为正式 `.pdf`，更新数据库 `status = 'DOWNLOADED'`、`pdf_local_path`。
  4. 若下载失败（例如 IEEE 期刊无开放 OA PDF），**优雅降级为 A 级速览**（记录日志 `Fallback to abstract-only`，仍允许进入分析队列，不卡死流程）。

---

## 2. 文本提取与核心架构图抽取器（`pipeline/extractor.py`）

在删除 PDF 之前，利用 `PyMuPDF (fitz)` + `Pillow` 一次性把论文里最有价值的图文资产榨取出来：

### 2.1 干净全文文本提取（供 DeepSeek Harness 快速阅读）
- 逐页提取文本，按页标注 `--- PAGE {i} ---`，去除多余页眉页脚空行。
- 截断保护：保留完整正文（通常 1~12 页），过滤掉纯 `References` 之后的冗余长参考文献列表（通过匹配独立行 `References` / `REFERENCES` 自动截断），大幅节省 LLM Token。
- 保存为队列目录下的 `extracted_text.md`。

### 2.2 核心架构图 / Teaser 图自动提取（WebP 轻量压缩）
- 扫描 PDF 前 4 页的嵌入式图片（`page.get_images(full=True)`）：
  - 过滤掉过小的图标/Logo（要求原图宽 >= `400px` 且高 >= `200px`，宽高比在 `0.3 ~ 5.0` 之间）。
  - 按像素面积降序取前 `max_figures_per_paper`（默认 2 张，通常正好对应 Figure 1 Teaser 和 Method 架构图）。
  - 使用 Pillow 等比缩放至宽度 `<= 1200px`，转为 **WebP** 格式（质量 80，每张仅约 30~80 KB）。
  - 输出到 `workspace/staging/assets/<paper_uid>/fig_1.webp`、`fig_2.webp`。
- **兜底机制**：若 PDF 为纯矢量图导致 `get_images()` 为空，则跳过抽图不报错，记录 `figures = []`。

---

## 3. DeepSeek Harness + WorkBuddy 对接队列协议（`pipeline/queue_exporter.py`）

执行 `paperflow export-queue` 后，将所有待分析的 S 级（`DOWNLOADED`）和 A 级（`SCORED`）论文导出到标准目录：

```text
workspace/queue/YYYY-MM-DD/
├── queue_manifest.json              # 当日待分析任务总清单（供 Harness/WorkBuddy 一键遍历）
└── <paper_uid>/
    ├── meta.json                    # 论文完整元数据 + BibTeX + 已抽取的 WebP 图片相对路径
    ├── extracted_text.md            # S 级包含去参考文献的全文；A 级仅包含 Title + Abstract
    └── prompt.md                    # 已填充好上下文的标准化分析 Prompt
```

同时数据库将对应论文状态更新为 `QUEUED`。

### 3.1 DeepSeek Harness 输出契约（极其重要）
DeepSeek Harness / WorkBuddy 读取 `queue_manifest.json` 后，对每篇论文执行分析，并将结果写入：
- **目标文件路径**：`workspace/staging/YYYY-MM-DD/<paper_uid>.md`

生成的 `.md` 文件**必须严格遵守以下结构**：

```markdown
---
paper_uid: "arxiv_2603.12345"
title: "论文原始英文标题"
venue: "CVPR 2026"
year: 2026
pub_date: "2026-03-15"
tier: "S"
tags: ["Video Understanding", "Action Recognition", "Multimodal"]
code_url: "https://github.com/xxx/xxx"
paper_url: "https://arxiv.org/abs/2603.12345"
tldr: "一句话中文总结本文最核心的方法与性能突破。"
---

# 论文原始英文标题

> **Venue**: CVPR 2026 | **Tier**: S 级精读 | **Code**: [GitHub](https://github.com/xxx/xxx) | **Paper**: [Link](https://arxiv.org/abs/2603.12345)

## 1. 一句话总结（TL;DR）
...

## 2. 研究背景与痛点（Motivation）
...

## 3. 核心方法拆解（Method）
（若 meta.json 中存在抽取的架构图，自动引用：`![核心架构图](../../assets/<paper_uid>/fig_1.webp)`）
（复杂流程可使用 Mermaid `flowchart LR` 绘制）

## 4. 关键实验与 SOTA 对比（Experiments）
...

## 5. 局限性与可借鉴的 Idea（Critical Thinking）
...

## 6. 复现与引用卡片（BibTeX & Links）
（折叠区块，包含标准 BibTeX 与 `git clone` 命令）

<!-- PAPERFLOW_METRICS_JSON
{
  "task": "Temporal Action Localization",
  "backbone": "ViT-L",
  "datasets": ["THUMOS14", "ActivityNet-1.3"],
  "sota_summary": "THUMOS14 mAP 72.4% (+2.1% over previous SOTA)",
  "innovation_tags": ["Zero-Shot", "Long-Video"]
}
-->
```

> **说明**：A 级速览论文使用精简版 Prompt，只需包含 `TL;DR`、`核心问题与思路`、`主要结论` 与 `BibTeX 卡片`，无需强求长篇方法拆解。

---

## 4. 分析结果严格校验器（`pipeline/md_validator.py`）

在允许删除 PDF 或发布到博客之前，必须通过 `paperflow validate`（也会被 `publish` 和 `clean` 自动调用）：

1. 扫描 `workspace/staging/` 下所有新增或修改的 `<paper_uid>.md`。
2. 逐项检查：
   - 文件可读（UTF-8）且非空。
   - YAML Frontmatter 合法，包含必填字段：`paper_uid`, `title`, `venue`, `year`, `tier`, `tldr`。
   - Frontmatter 中的 `paper_uid` 与文件名、数据库记录一致。
   - 去除 Frontmatter 后的正文长度 `>= min_valid_md_chars`（S 级默认 300 字符，A 级 120 字符）。
   - 若包含 `<!-- PAPERFLOW_METRICS_JSON ... -->` 注释块，解析 JSON 并写入 `paper_metrics` 表（解析失败只打 WARNING，不阻断发布）。
3. 校验通过：更新数据库 `status = 'STAGED'`、`md_staging_path`。
4. 校验失败：打印精确错误原因（如“缺少 tldr 字段”或“正文过短”），状态保持 `QUEUED`，**严禁删除对应 PDF**。

---

## 5. 每日人工速览与批注清单（`publisher/digest.py`）

`paperflow validate` 完成后，自动在 `workspace/staging/YYYY-MM-DD/TODAY_DIGEST.md` 生成当日汇总清单，方便你早上 5 分钟快速审阅：
- 列出今日 S 级精读列表（含标题、Venue、TL;DR、是否开源、本地文件链接）。
- 列出今日 A 级速览列表。
- 列出今日 B 级仅归档数量统计。
- 你可直接打开任意 staging 中的 `.md`，手动添加自己的灵感批注（如 `> 💡 个人批注：...`），或者直接删除某篇不想发布的 `.md`。

---

## 6. “用完即焚”安全清理引擎（`pipeline/cleaner.py`）

执行 `paperflow clean`（支持 `--dry-run` 预览，也可在 `publish --clean` 时自动触发）：

1. **安全查询条件**：仅筛选数据库中满足以下**全部条件**的论文：
   - `status IN ('ANALYZED', 'STAGED', 'PUBLISHED')`（默认仅清理 `PUBLISHED`，可通过 `--include-staged` 放宽）
   - `pdf_deleted == 0`
   - 对应的 `md_staging_path` 或 `md_blog_path` 文件真实存在且非空。
2. **执行删除**：
   - 删除 `workspace/tmp/pdfs/<paper_uid>.pdf`（若存在）。
   - 删除 `workspace/queue/*/<paper_uid>/` 临时目录（若存在）。
   - 若某天 `workspace/queue/YYYY-MM-DD/` 下已无未处理论文，清理该空日期目录。
3. **更新账本**：
   - `pdf_local_path = NULL`、`pdf_deleted = 1`；若原状态为 `PUBLISHED` 则流转至终态 `CLEANED`。
   - 写入 `run_logs` 记录本次释放的磁盘空间（MB）与清理篇数。
4. **绝对禁区**：代码层面硬编码校验待删路径必须严格位于 `workspace/tmp/` 或 `workspace/queue/` 之内（`path.resolve().is_relative_to(...)`），从根源杜绝任何误删风险。

---

## 7. Phase 4 & 5 验收测试要求

1. `tests/test_extractor.py`：用 `PyMuPDF` 动态生成一个测试 PDF（含文字 + 一张内嵌图片），验证文本正确抽取、References 后内容被截断、图片成功压缩为 `.webp`。
2. `tests/test_validator_and_cleaner.py`：
   - 合法 MD → 校验通过、`paper_metrics` 成功入库、`cleaner` 删除临时 PDF 并置 `pdf_deleted = 1`。
   - 非法/空 MD → 校验失败、`cleaner` **拒绝删除**对应 PDF。
   - 路径越界测试 → 传入 `workspace/state.db` 路径时清理器必须抛出安全异常拒绝删除。
