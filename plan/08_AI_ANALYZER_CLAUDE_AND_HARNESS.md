# Phase 11：AI 论文自动解析引擎（Claude CLI + Kimi K3 全自动 & DeepSeek Harness Web 协作桥接）

> **定位与背景**：
> 在 Phase 1 ~ Phase 10 中，系统已经完成了“**采集 → 去重打分 → 下载 PDF/抽图 → 导出 `queue/`**”以及“**校验 `staging/` → 在线批注 → 发布 `paper_repo` → 安全清理 PDF**”，但**中间最核心的“调用 AI 把 `queue/` 里的论文真正解析为 `staging/*.md`”这一步尚未自动化**。
>
> 本文件（Phase 11）专门补齐这一核心闭环，针对你的本地双环境提供**可插拔双模式解析引擎**：
> 1. **全自动主力模式（`claude_cli`）**：直接调用本地终端已配置好 **Kimi K3** 模型的 `claude` CLI，无人值守批量读取队列、生成标准 Markdown、自动清洗修复、自动校验入库。
> 2. **Web 协作桥接模式（`harness_web`）**：适配你本地部署的 **DeepSeek Harness Web 界面（WorkBuddy 免费模型）**，在 PaperFlow 控制台提供一键跳转、一键复制单篇/整批任务包、一键粘贴回填自动校验入库。
> 3. **可选扩展模式（`openai_api`）**：预留标准 OpenAI 兼容接口适配（若未来本地模型暴露 HTTP API 可零代码切换）。

---

## 1. 架构与新增目录结构

```text
src/paperflow/analyzers/
├── __init__.py
├── base.py                    # BaseAnalyzer 抽象基类、AnalysisResult 模型、Markdown 清洗器
├── claude_cli_analyzer.py     # 本地 Claude CLI（Kimi K3）非交互全自动解析器
├── openai_api_analyzer.py     # 可选 OpenAI 兼容 HTTP API 解析器
└── runner.py                  # 批量解析调度器（队列遍历、超时重试、校验自修复、进度回调）

src/paperflow/web/routes/
└── analyzer.py                # AI 解析中心 REST API + SSE 进度任务触发 + Harness 协作接口
```

---

## 2. 配置扩展（`config/config.yaml` 新增 `analyzer` 节点）

保持 100% 向后兼容（Pydantic 提供默认值，不影响旧配置）：

```yaml
analyzer:
  default_backend: "claude_cli"        # claude_cli | harness_web | openai_api
  max_input_chars: 60000               # 喂给模型的最大正文字符数（超长 PDF 智能截断保护）
  max_retries: 2                       # 格式校验失败或临时超时时的最大重试次数（含带报错自修复）
  timeout_seconds: 240                 # 单篇论文解析超时秒数
  cooldown_seconds: 3.0                # 批量解析每篇之间的间隔秒数（防触发 API 频率限制）
  auto_validate_after_analysis: true   # 每解析完一篇立刻运行 md_validator 校验并提取 metrics

  # 后端 1：本地 Claude CLI（已配置 Kimi K3）
  claude_cli:
    enabled: true
    executable: "claude"               # 支持绝对路径，如 "C:\\Users\\...\\claude.cmd"
    # 默认采用非交互纯文本模式：从 stdin 读入完整提示词+论文文本，stdout 输出纯 Markdown
    args: ["-p", "--output-format", "text"]
    model: ""                          # 留空则直接使用你本地 Claude CLI 默认配置好的 Kimi K3；填写时追加 --model <name>
    extra_env: {}                      # 可选额外环境变量（严禁硬编码密钥，敏感项走系统环境变量）

  # 后端 2：DeepSeek Harness Web（WorkBuddy 免费模型）协作桥接
  harness_web:
    enabled: true
    web_url: "http://127.0.0.1:3080"   # 你本地部署的 DeepSeek Harness Web 地址（可在页面修改）
    auto_watch_staging: true           # 若 Harness 具备写本地文件能力，自动扫描 staging 目录新增 MD

  # 后端 3：可选 OpenAI 兼容接口（预留扩展）
  openai_api:
    enabled: false
    base_url: "http://127.0.0.1:11434/v1"
    api_key_env: "PAPERFLOW_LLM_API_KEY"
    model: "kimi-k3"
```

---

## 3. 数据库扩展：解析审计表（`analysis_runs`）

在 `workspace/state.db` 中平滑新增 `analysis_runs` 表（记录每篇论文的解析过程、使用引擎、耗时与重试情况）：

```sql
CREATE TABLE IF NOT EXISTS analysis_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT,                     -- 关联 TaskManager 批量任务 ID
    paper_uid       TEXT NOT NULL REFERENCES papers(paper_uid) ON DELETE CASCADE,
    backend         TEXT NOT NULL,            -- claude_cli | harness_web | openai_api
    model_name      TEXT DEFAULT '',          -- 如 kimi-k3 / workbuddy
    attempt         INTEGER DEFAULT 1,        -- 第几次尝试
    status          TEXT NOT NULL,            -- SUCCESS | VALIDATION_FAILED | TIMEOUT | ERROR
    duration_ms     INTEGER DEFAULT 0,
    output_chars    INTEGER DEFAULT 0,
    error_message   TEXT DEFAULT NULL,
    created_at      TEXT NOT NULL             -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_paper ON analysis_runs(paper_uid, created_at DESC);
```

---

## 4. 核心引擎实现细节

### 4.1 本地 Claude CLI（Kimi K3）全自动解析器（`claude_cli_analyzer.py`）

1. **环境与连通性自检（`health_check()`）**：
   - 使用 `shutil.which(executable)` 检查 `claude` 命令是否存在（Windows 下自动兼容 `claude.cmd` / `claude.exe`）。
   - 执行 `[executable, "--version"]` 获取版本号。
   - 可选执行最小探针（传入 `"Reply with exactly: OK"`，超时 20s）验证 Kimi K3 模型响应正常，返回 `{ok, version, latency_ms, message}`。
2. **输入组装与智能截断**：
   - 读取 `workspace/queue/<date>/<paper_uid>/prompt.md` 与 `extracted_text.md`。
   - 若总长度超过 `max_input_chars`（默认 60,000 字符），优先保留前 75%（标题、摘要、引言、核心方法）+ 后 25%（主要实验与结论），中间插入 `\n...[中间部分因长度限制已省略]...\n`，避免撑爆上下文或超时。
   - **重要指令加固**：在发送给 `claude -p` 的末尾明确附加系统约束：
     > *“请直接输出最终完整的 Markdown 文档内容，必须以 `---`（YAML Frontmatter）开头，不要输出任何开场白、解释性废话，也不要用外层 ` ```markdown ` 代码块包裹整个文档。”*
3. **非交互安全调用（Windows UTF-8 兼容）**：
   - 使用 `subprocess.run(cmd, input=full_prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_seconds, shell=False)`。
   - **全程通过 stdin 传文本、stdout 拿结果**，不触发 Claude CLI 任何交互式权限弹窗，不依赖文件写入工具权限，最稳定可控。
   - 支持 `cancel_event`：建议用 `subprocess.Popen` 轮询（每 0.5s 检查一次 `cancel_event.is_set()` 与超时），一旦用户在 Web 端点击【停止任务】，立刻 `proc.terminate()` 释放进程！
4. **输出自动清洗器（`sanitize_markdown_output(raw_text)`）**：
   - 自动去除模型偶尔输出的思考前缀或外层 ```` ```markdown ... ``` ```` 围栏，定位第一个合法的 YAML Frontmatter `---` 起始位置。
   - 原子写入（先写 `.tmp` 再 `os.replace`）到 `workspace/staging/<date>/<paper_uid>.md`。
5. **校验驱动的自修复重试（Self-Healing Retry）**：
   - 写入后立刻调用 `md_validator.validate_single_file(md_path)`。
   - 若校验失败（例如缺少 `tldr` 字段、Frontmatter YAML 语法错误、或正文过短），自动将**具体校验报错信息**拼入下一次 Prompt（*“上次输出未通过格式校验，错误原因如下：... 请修复后重新输出完整 Markdown”*）重试，最多 `max_retries` 次。
   - 校验通过后：自动将论文状态更新为 `STAGED`、写入 `paper_metrics` 与 `analysis_runs`，并刷新当日 `TODAY_DIGEST.md`。

### 4.2 DeepSeek Harness Web（WorkBuddy）协作桥接（`web/routes/analyzer.py`）

针对你在本地部署的 DeepSeek Harness Web 界面（使用 WorkBuddy 免费模型），提供**丝滑的半自动闭环体验**：

1. **模式 A：单篇“一键复制 → 对话解析 → 一键粘贴入库”**
   - 在 PaperFlow Web 端选中某篇待解析论文，点击 **【复制完整解析 Prompt】**（后端拼接好 `prompt.md + extracted_text.md`，一键复制到剪贴板）。
   - 点击 **【打开 DeepSeek Harness】** 跳转到你的本地 Web 界面，粘贴给 WorkBuddy 生成 Markdown。
   - 复制生成的 Markdown，回到 PaperFlow 点击 **【粘贴并入库校验】** → 后端自动执行 `sanitize_markdown_output()` → 原子写入 `workspace/staging/<date>/<paper_uid>.md` → 自动校验并提取 `paper_metrics` → 状态直接流转为 `STAGED`！
2. **模式 B：整批目录协作指令（当 Harness 支持读写本地文件时）**
   - 提供 **【复制整批 Harness 执行指令】** 按钮，一键生成如下标准指令：
     > *“请读取 `workspace/queue/2026-11-21/queue_manifest.json`，逐篇阅读各子目录下的 `meta.json`、`prompt.md` 和 `extracted_text.md`，严格按照输出契约将分析结果写入 `workspace/staging/2026-11-21/<paper_uid>.md`。”*
   - Harness 执行完后，在 PaperFlow 点击 **【扫描并校验 Staging】** 即可一次性全部入库。

---

## 5. CLI 新增命令（`src/paperflow/cli.py`）

| 命令 | 参数选项 | 功能说明 |
| :--- | :--- | :--- |
| `paperflow analyzer-check` | `--backend claude_cli`, `--probe` | 检查 Claude CLI 可执行文件、版本号及可选 Kimi K3 真实连通性探针 |
| `paperflow analyze` | `--backend claude_cli\|openai_api`, `--date`, `--paper-uid`, `--tier S,A`, `--limit`, `--retry-failed`, `--dry-run` | 批量调用 AI 引擎自动解析待分析队列并校验入库 |

> **可选端到端串联**：在 `scripts/run_daily_fetch.ps1` 中预留可选开关 `-AutoAnalyze`，开启后每天早上自动完成 `fetch → export-queue → analyze (Claude CLI + Kimi K3)`，你打开电脑直接审阅成品！

---

## 6. Web 控制台新增页面：页面 9 — AI 论文解析中心（AI Analyzer）

在 `src/paperflow/web/static/index.html` 左侧导航栏新增 **【AI 解析中心】**（放在【待审工作台】之前，当存在 `QUEUED` 待解析论文时显示蓝色数字角标）：

### 6.1 新增 REST API（`src/paperflow/web/routes/analyzer.py`）

| Method | Path | 说明 |
| :--- | :--- | :--- |
| `GET` | `/api/analyzer/status` | 获取当前默认引擎、各后端配置状态、待解析队列数量（S/A 级统计） |
| `POST` | `/api/analyzer/check` | 执行 Claude CLI / OpenAI API 连通性检测（含版本号与响应延迟） |
| `GET` | `/api/analyzer/queue` | 获取所有待解析论文列表（含 `paper_uid`、标题、Venue、Tier、正文字符数、是否已抽图） |
| `POST` | `/api/analyzer/run` | **启动全自动批量解析任务**（支持传 `backend`、`paper_uids` 勾选列表、`limit`，走 `TaskManager` + SSE 实时进度） |
| `GET` | `/api/analyzer/prompt/{paper_uid}` | 获取单篇论文可直接复制给 DeepSeek Harness Web 的完整 Prompt+正文 |
| `GET` | `/api/analyzer/batch-instruction` | 生成给 DeepSeek Harness Web 的整批队列执行指令（`?date=...`） |
| `POST` | `/api/analyzer/import-md/{paper_uid}` | **粘贴回填接口**：接收用户在 DeepSeek Harness Web 复制回来的 Markdown，自动清洗、落盘 `staging/`、校验并提取 `metrics` |
| `GET` | `/api/analyzer/history` | 分页查询 `analysis_runs` 解析审计历史（引擎、耗时、重试次数、成功/失败原因） |

### 6.2 前端界面布局
1. **顶部引擎切换与状态卡片**：
   - 两个醒目模式标签：**`🤖 Claude CLI (Kimi K3 全自动)`** 与 **`🌐 DeepSeek Harness Web (WorkBuddy 协作)`**。
   - **Claude CLI 模式下**：显示 CLI 状态指示灯、**【检测 Kimi K3 连通性】** 按钮、单篇超时/重试参数提示、以及主按钮 **【🚀 一键全自动解析选中论文】**。
   - **DeepSeek Harness 模式下**：显示本地 Harness URL 配置框、**【🔗 打开 DeepSeek Harness Web】** 按钮、**【📋 复制整批队列执行指令】** 按钮与 **【🔄 扫描 Staging 目录并校验】** 按钮。
2. **实时解析进度面板（SSE）**：
   - 运行 Claude CLI 批量解析时，实时展示：`正在解析第 2/5 篇 [S级] — <论文标题>`、进度条、单篇实时耗时计时器、校验/自修复日志流、以及 **【停止解析】** 按钮。
   - 每完成一篇，右侧立刻弹出绿色勾号并附带 **【去待审工作台查看】** 快捷跳转。
3. **待解析队列操作表**：
   - 支持全选 / 仅选 S 级 / 单选勾选框。
   - 每行显示：Tier 徽章、Venue、标题、正文长度（如 `28.4k 字符`）、是否含架构图。
   - 每行右侧动作按钮：
     - **【Claude 解析】**（单篇立即跑）
     - **【复制 Prompt】**（一键复制到剪贴板去贴给 DeepSeek Harness）
     - **【粘贴结果入库】**（弹出大文本框，粘贴 WorkBuddy 输出的 Markdown，点击保存即自动清洗+校验入库）
4. **底部解析历史审计表（`analysis_runs`）**：
   - 展示每次解析的论文、使用的引擎（`claude_cli` / `harness_web`）、尝试次数、耗时、输出字数、状态与失败原因，失败条目支持一键 **【重新解析】**。

---

## 7. Phase 11 验收测试要求（`tests/test_analyzer.py`）

1. **Markdown 清洗器测试**：
   - 测试含前置废话 + ```` ```markdown ... ``` ```` 包裹的原始输出能被精准清洗为以 `---` 开头的合法 Markdown。
2. **Claude CLI 解析器 Mock 测试（离线可测，不消耗真实 Token）**：
   - Mock `subprocess.Popen` 返回合法 Markdown → 验证 `staging/<date>/<paper_uid>.md` 成功生成、状态流转为 `STAGED`、`paper_metrics` 入库、`analysis_runs` 记录 `SUCCESS`。
   - Mock 第 1 次返回缺少 `tldr` 的非法 Markdown、第 2 次返回修复后的合法 Markdown → 验证**自修复重试机制**生效（第 2 次 Prompt 包含报错信息，最终 `SUCCESS` 且 `attempt=2`）。
   - Mock `cancel_event` 触发 → 验证子进程被安全终止且不写入损坏文件。
   - Mock 超长文本（120,000 字符）→ 验证智能截断至 `<= max_input_chars` 且首尾核心内容保留。
3. **DeepSeek Harness Web 协作接口测试**：
   - 验证 `GET /api/analyzer/prompt/{uid}` 返回完整 Prompt+正文。
   - 验证 `POST /api/analyzer/import-md/{uid}` 接收带代码块包裹的 Markdown 后，能自动清洗、落盘、校验成功并记录 `backend='harness_web'`。
4. **全量回归测试**：
   - 运行 `pytest -v`，确保 Phase 1 ~ Phase 11 全部测试 100% 通过无回归。
