# Phase 12：发布前本地 MkDocs 严格门禁预览 & Prompt 模板工作室

> **背景说明**：本文件为增量增强规格书（Phase 12），在**不破坏 Phase 1 ~ Phase 11 现有功能**的前提下，补齐两个高频实战短板：
> 1. **博客构建门禁与本地实时预览**：推送 GitHub 前先在本地执行 `mkdocs build --strict` 拦截断链/公式/排版报错，并支持在 Web 控制台一键启动/停止 `mkdocs serve` 本地预览。
> 2. **Prompt 模板工作室（Prompt Studio）**：将原本写死在代码中的分析 Prompt 抽离为 `config/prompts/` 独立模板，支持按研究方向（如 `Agent`、`HSI-MSI 图像融合`、`Agent + 图像融合`）自动路由专属精读模板，并在 Web 端可视化编辑与真实论文试渲染预览。

---

## 模块 A：发布前本地 `mkdocs build --strict` 门禁与一键预览

### A.1 核心服务（`src/paperflow/publisher/mkdocs_service.py`）

封装 `MkDocsService(paper_repo_dir: Path, workspace_dir: Path, preview_port: int = 8001)`：

1. **虚拟环境安全调用（Windows 避坑）**：
   - 严禁假设 `mkdocs` 在全局 PATH 中；统一使用 `[sys.executable, "-m", "mkdocs", ...]` 调用，确保 100% 复用当前 Python 虚拟环境。
   - 所有子进程强制 `encoding="utf-8", errors="replace", shell=False`。
2. **严格构建门禁（`build_strict() -> BuildCheckResult`）**：
   - 构建目标目录指向临时目录：`workspace/tmp/mkdocs_strict_check/`（执行前清空，执行后自动删除），**绝对不在 `paper_repo/` 目录内生成或残留 `site/` 文件夹**。
   - 执行命令：`[sys.executable, "-m", "mkdocs", "build", "--strict", "--site-dir", str(temp_site_dir)]`，工作目录 `cwd = paper_repo_dir`，超时 60 秒。
   - 解析 `stdout + stderr`，正则提取所有 `WARNING` / `ERROR` 行及涉及的 `.md` 文件路径，返回：
     ```python
     class BuildCheckResult(BaseModel):
         ok: bool
         duration_ms: int
         error_count: int
         warning_count: int
         issues: list[dict]   # [{"level": "WARNING", "file": "...", "message": "..."}]
         raw_output: str
     ```
3. **发布流程强制门禁接入**：
   - 在 `config/config.yaml` 的 `publish` 下新增配置（默认值向后兼容）：
     ```yaml
     publish:
       require_mkdocs_strict_build: true   # 推送前强制本地构建校验
       preview_port: 8001                  # 本地预览端口（避开主控制台 8000）
     ```
   - 在 `sync_blog.py`（`publish`）与 `web/routes/git_ops.py`（`publish-and-push`）中：
     - 同步完 Markdown 与聚合页之后、执行 `git commit / push` 之前，自动调用 `build_strict()`（CLI 支持 `--skip-build-check`，Web 端支持可选跳过开关）。
     - **若 `ok == False`**：立即中止 `git commit` 与 `git push`，通过 SSE 日志与界面弹窗高亮展示具体出错的 Markdown 文件与原因，引导用户去【待审工作台】一键修复。
4. **一键本地实时预览（`start_preview()` / `stop_preview()` / `get_preview_status()`）**：
   - 使用 `subprocess.Popen([sys.executable, "-m", "mkdocs", "serve", "-a", f"127.0.0.1:{preview_port}"], cwd=paper_repo_dir, ...)` 后台启动。
   - 单实例管理：重复启动返回当前运行状态；启动后轮询检测 `127.0.0.1:{preview_port}` TCP 端口就绪（最多等待 10 秒）。
   - **进程清理保护**：在 FastAPI `lifespan` 关闭钩子和 `atexit` 中自动调用 `stop_preview()` 终止子进程，防止关闭控制台后残留僵尸 `mkdocs` 进程占住端口。

---

## 模块 B：Prompt 模板工作室（Prompt Studio — 按方向定制分析侧重点）

### B.1 外部化模板目录与内置模板（`config/prompts/`）

首次启动或运行 `paperflow prompts init` 时，若 `config/prompts/` 不存在则自动释放以下内置模板：

```text
config/prompts/
├── templates_meta.json              # 模板元数据与路由规则表
├── tier_s_default.md                # 通用 S 级精读默认模板
├── tier_a_default.md                # 通用 A 级速览默认模板
├── topic_agent.md                   # Agent 方向专属精读模板
├── topic_hsi_msi_fusion.md          # HSI-MSI / 图像融合方向专属精读模板
└── topic_agent_image_fusion.md      # Agent + 图像融合交叉方向专属精读模板
```

各方向专属模板的差异化侧重点：
- **`topic_agent.md`**：重点拆解 Planning/Reasoning 机制、Tool Use 与环境交互接口、Memory 架构、Multi-Agent 协同方式、Agent 评测基准（如 OSWorld / SWE-bench / WebArena）与失败案例分析。
- **`topic_hsi_msi_fusion.md`**：重点拆解物理成像与空间-光谱退化模型（PSF / SRF）、网络核心模块（Transformer / Diffusion / Mamba / Unfolding）、损失函数设计、关键定量指标（PSNR / SAM / ERGAS / Q2n / SSIM）、数据集（CAVE / Harvard / Chikusei / Pavia / Real-world）与参数量/推理效率。
- **`topic_agent_image_fusion.md`**：重点拆解 Agent 在图像融合中的决策角色（动态算子调度 / 退化感知路由 / 自适应提示生成）、多模态工具链设计、端到端闭环反馈机制与融合质量提升来源。

`templates_meta.json` 单条记录结构：
```json
{
  "id": "topic_hsi_msi_fusion",
  "name": "HSI-MSI 图像融合专属精读",
  "tier": "S",
  "priority": 100,
  "match_topics": ["HSI-MSI 图像融合", "hsi-msi-fusion", "HSI-MSI图像融合"],
  "match_keywords": ["hyperspectral", "multispectral", "hsi-msi", "pansharpening", "image fusion"],
  "description": "侧重物理退化模型、光谱-空间交互与 PSNR/SAM/ERGAS 指标对比",
  "file": "topic_hsi_msi_fusion.md",
  "is_builtin": true
}
```

### B.2 模板管理与安全渲染引擎（`src/paperflow/pipeline/prompt_manager.py`）

1. **支持的模板变量占位符**：
   - `{{paper_uid}}`, `{{title}}`, `{{venue}}`, `{{year}}`, `{{pub_date}}`, `{{tier}}`
   - `{{authors}}`, `{{abstract}}`, `{{code_url}}`, `{{paper_url}}`
   - `{{figures_markdown}}`（已抽取的 WebP 架构图引用片段，无图时为空提示）
   - `{{bibtex}}`（预生成的标准 BibTeX）
   - `{{content}}`（S 级为去参考文献的全文，A 级为摘要）
2. **严禁使用 `str.format()`（关键避坑！）**：
   - 论文正文与 LaTeX 公式中大量包含 `{}` 花括号（如 `\frac{a}{b}`、`{"key": "val"}`）。
   - 渲染函数 `render_prompt(template_text, context)` **必须使用正则 `re.sub(r"\{\{(\w+)\}\}", ...)` 仅替换白名单内的 `{{var}}` 占位符**，绝不能对正文中的普通花括号做格式化解析。
3. **自动路由优先级（`select_template(paper, override_id=None)`）**：
   - 1) 若显式传入 `override_id`，直接使用该模板；
   - 2) 检查论文的 `topic_tags_json` 是否命中某模板的 `match_topics`（且 `tier` 兼容 `ALL` 或与论文一致），按 `priority` 降序取最高；
   - 3) 检查论文 `title + abstract + matched_tags` 是否命中某模板的 `match_keywords`，按 `priority` 降序取最高；
   - 4) 兜底返回 `tier_s_default`（S 级）或 `tier_a_default`（A 级）。
4. **安全修改与版本备份**：
   - 每次修改模板保存前，自动备份旧内容到 `workspace/backups/prompts/<id>_<YYYYMMDD_HHMMSS>.md`。
   - 保存时执行轻量契约提示检查（检查模板是否仍包含 Frontmatter `---`、`paper_uid`、`tldr` 要求；若缺失返回 `warnings` 列表提醒用户，防止生成无法通过 `md_validator` 的 Markdown）。
   - 内置模板支持一键 `reset_to_default(template_id)` 恢复出厂内容；自定义模板支持删除。
5. **与现有流水线无缝集成**：
   - 修改 `pipeline/queue_exporter.py`：导出 `prompt.md` 时调用 `PromptManager.select_template()` + `render_prompt()`，并在 `meta.json` 中写入 `"prompt_template_id": "<id>"`。
   - 修改 `analyzers/runner.py`（Phase 11）：支持按需指定 `template_id` 动态重渲染 Prompt 后送入 Claude CLI (Kimi K3) 解析。

---

## 模块 C：CLI 与 Web 控制台扩展

### C.1 CLI 新增命令（`src/paperflow/cli.py`）

| 命令 | 参数选项 | 功能说明 |
| :--- | :--- | :--- |
| `paperflow build-check` | 无 | 在本地运行 `mkdocs build --strict` 门禁检查并输出结构化问题列表 |
| `paperflow preview` | `--port 8001`, `--open` | 启动本地 `mkdocs serve` 实时预览博客 |
| `paperflow prompts-list` | 无 | 表格展示所有 Prompt 模板、优先级与方向匹配规则 |
| `paperflow prompts-init` | `--force` | 初始化（或重置）`config/prompts/` 内置默认模板 |

### C.2 新增 REST API（`src/paperflow/web/routes/blog_preview.py` & `prompts.py`）

| Method | Path | 说明 |
| :--- | :--- | :--- |
| `POST` | `/api/blog/build-check` | 运行本地 `mkdocs build --strict`，返回构建结果与具体报错文件列表 |
| `GET` | `/api/blog/preview/status` | 查询本地 `mkdocs serve` 预览进程是否运行及预览 URL |
| `POST` | `/api/blog/preview/start` | 启动本地 `mkdocs serve` 预览（返回 `http://127.0.0.1:8001`） |
| `POST` | `/api/blog/preview/stop` | 停止本地 `mkdocs serve` 预览进程 |
| `GET` | `/api/prompts` | 获取所有模板列表与路由规则 |
| `GET` | `/api/prompts/{template_id}` | 读取指定模板元信息与完整正文 |
| `POST` | `/api/prompts` | 新建自定义方向 Prompt 模板 |
| `PUT` | `/api/prompts/{template_id}` | 保存模板修改（自动备份旧版 + 返回契约检查提醒） |
| `POST` | `/api/prompts/{template_id}/reset` | 恢复内置模板为默认内容 |
| `DELETE` | `/api/prompts/{template_id}` | 删除自定义模板（内置模板禁止删除，返回 400） |
| `POST` | `/api/prompts/{template_id}/preview` | 传入 `paper_uid`，用真实论文数据试渲染并返回最终 Prompt 与预估字符数 |

### C.3 Web 前端集成位置

1. **【Git 发布中心】顶部栏 & 推送面板增强**：
   - 增加 **【🔍 本地构建校验 (`mkdocs --strict`)】** 按钮：点击后展示绿色通过徽章或红色具体报错文件列表。
   - 增加 **【👁️ 启动本地预览 / 打开预览 (`:8001`)】** 与 **【⏹ 停止预览】** 按钮。
   - 【一键发布并推送】勾选框新增 `推送前强制本地构建校验`（默认勾选），失败时自动拦阻推送。
2. **新增左侧导航页：页面 10 — 【Prompt 模板工作室】**：
   - **左侧模板目录**：分组展示通用模板（S/A 级）与方向专属模板（Agent / HSI-MSI 融合 / Agent+图像融合 / 自定义），带优先级与匹配方向标签。
   - **右侧编辑器**：
     - 顶部元信息栏（名称、Tier、优先级、匹配方向 Tag、匹配关键词 Tag）。
     - 变量快捷插入条（点击 `{{title}}`、`{{figures_markdown}}`、`{{bibtex}}`、`{{content}}` 直接插入光标处）。
     - **【🧪 用真实论文试渲染】** 抽屉：从账本下拉任选一篇论文，立即预览最终发给 Claude CLI / DeepSeek Harness 的完整 Prompt 与总字数。
     - 底部按钮：**【保存模板】**、**【新建方向模板】**、**【恢复默认】**、**【删除】**。

---

## 模块 D：Phase 12 验收测试要求（`tests/test_preview_and_prompts.py`）

1. **MkDocs 严格构建门禁测试**：
   - 正常 `paper_repo` 构建返回 `ok=True`，且断言 `paper_repo/site` 目录**不存在**（无垃圾残留）。
   - 在临时 `paper_repo/docs/` 写入包含断链图片 `![](non_existent.webp)` 的 `.md`，断言 `build_strict()` 返回 `ok=False` 且能解析出告警信息；验证 `publish` 门禁开启时成功拦截 Git 提交与推送。
2. **Prompt 自动路由测试**：
   - 带 `topic_tags=["HSI-MSI 图像融合"]` 的 S 级论文 → 命中 `topic_hsi_msi_fusion`。
   - 带 `topic_tags=["Agent"]` 的 S 级论文 → 命中 `topic_agent`。
   - 普通无方向标签的 S 级论文 → 兜底命中 `tier_s_default`；A 级论文 → 命中 `tier_a_default`。
3. **LaTeX / JSON 花括号渲染安全测试**：
   - 论文正文含 `\mathcal{L}_{fusion} = \frac{1}{N}\sum_{i=1}^N` 与 `{"psnr": 42.1}` 时，`render_prompt()` 正常替换 `{{title}}` / `{{content}}` 且**绝不抛出异常**、原样保留 LaTeX 与 JSON 内容。
4. **模板备份与恢复测试**：
   - 修改内置模板后验证 `workspace/backups/prompts/` 生成备份文件；调用 `reset_to_default` 后恢复原内容；尝试删除内置模板返回 `400`。
5. **Web API 与全量回归测试**：
   - 验证 `/api/blog/build-check`、`/api/blog/preview/status`、`/api/prompts/*`（CRUD + 试渲染）全部通过；最后运行全量 `pytest -v` 确认 Phase 1 ~ Phase 12 全部 100% 通过无回归。
