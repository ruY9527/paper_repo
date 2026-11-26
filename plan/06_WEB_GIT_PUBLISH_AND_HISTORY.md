# Phase 9：Web 端 Git 一键提交推送与提交历史可视化中心

本文件定义在本地 Web 控制台（PaperFlow Studio）中新增的 **Git 发布与提交中心**（后端 `git_service.py` + `routes/git_ops.py` + 前端 Page 7），充分利用本地已配置好的 **SSH 免密认证**，实现浏览器端**一键提交并推送博客仓库（`blog_repo/`）**、**变更 Diff 预览**、**SSH 连通性检测**以及**完整 Git 提交历史与推送审计记录查看**。

---

## 1. 安全边界与 SSH 免密运行规范

1. **仓库严格隔离**：所有 Git 命令的工作目录（`cwd`）必须强校验为 `config.project.blog_repo_dir`，且校验 `blog_repo/.git` 存在并与外层 `paper_analysis/` 不是同一个仓库，**绝不允许误提交本地脚本、SQLite 或 PDF**。
2. **SSH 免密非交互模式（防卡死核心）**：
   执行任何联网 Git 命令（`push` / `pull` / `ls-remote`）时，必须注入以下环境变量，确保自动复用本地 `~/.ssh/` 密钥，且异常时快速失败、绝不阻塞 FastAPI 线程：
   ```python
   GIT_ENV = {
       **os.environ,
       "GIT_TERMINAL_PROMPT": "0",
       "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10",
   }
   ```
3. **Windows 中文路径兼容**：所有涉及文件名的 Git 命令统一附加 `-c core.quotepath=false`，避免中文文件名被转义为 `\344\270...` 乱码；`subprocess.run` 强制使用 `encoding="utf-8", errors="replace", shell=False`。
4. **防命令注入校验**：
   - `commit_hash` 必须匹配正则 `^[0-9a-fA-F]{7,40}$`。
   - 查看单文件 Diff 时，`file_path` 必须通过 `(blog_repo / file_path).resolve().is_relative_to(blog_repo.resolve())` 校验。
5. **并发互斥**：所有写操作（`commit` / `push` / `pull`）统一走 `TaskManager` 全局任务锁，并通过 SSE 推送实时进度与终端日志。

---

## 2. 数据库扩展：推送审计表（`git_push_logs`）

在 `workspace/state.db` 中新增一张表，专门记录每次通过 Web 界面或 CLI 触发的 Git 推送操作（即使失败也留痕）：

```sql
CREATE TABLE IF NOT EXISTS git_push_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT,                     -- 关联 TaskManager 任务 ID
    trigger_source  TEXT NOT NULL,            -- web | cli
    branch          TEXT NOT NULL,
    remote_url      TEXT DEFAULT '',
    commit_hash     TEXT DEFAULT '',          -- 本次提交的完整 Hash
    commit_message  TEXT DEFAULT '',
    files_changed   INTEGER DEFAULT 0,
    pushed          INTEGER DEFAULT 0,        -- 1=已推送远端, 0=仅本地提交或推送失败
    status          TEXT NOT NULL,            -- SUCCESS | FAILED
    duration_ms     INTEGER DEFAULT 0,
    error_message   TEXT DEFAULT NULL,
    created_at      TEXT NOT NULL             -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_git_push_logs_created ON git_push_logs(created_at DESC);
```

同时在 `config/config.yaml` 的 `publish` 节点下新增可选展示字段：
```yaml
publish:
  auto_git_commit: true
  auto_git_push: false
  commit_message_template: "docs: publish {count} papers ({date})"
  blog_site_url: "https://<username>.github.io/<repo>/"   # 可选，用于页面一键打开在线博客
  git_remote_name: "origin"
```

---

## 3. 后端核心服务（`src/paperflow/publisher/git_service.py`）

封装 `BlogGitService(blog_repo_dir: Path, remote_name: str = "origin")`，提供以下方法：

### 3.1 仓库与工作区状态（`get_status()`）
返回结构化对象 `GitRepoStatus`：
- `is_git_repo: bool`
- `branch: str`（`git rev-parse --abbrev-ref HEAD`）
- `remote_url: str`（`git remote get-url origin`）
- `is_ssh_remote: bool`（判断是否以 `git@` 或 `ssh://` 开头）
- `ahead_count: int`、`behind_count: int`（`git rev-list --left-right --count HEAD...@{upstream}`，无 upstream 时优雅返回 `0, 0`）
- `changes: list[GitFileChange]`：解析 `git -c core.quotepath=false status --porcelain=v1 -uall`，每条含 `{path, status_code, category}`（`added` / `modified` / `deleted` / `untracked`）。
- `has_changes: bool`
- `last_commit: GitCommitSummary | None`（最新一条提交的短 Hash、标题、时间）。

### 3.2 SSH 免密连通性检测（`test_ssh_connection()`）
- 执行 `git ls-remote --heads origin`（超时 10 秒，带 `GIT_ENV`）。
- 返回 `{ok: bool, remote_url: str, latency_ms: int, message: str}`。
- 失败时给出清晰中文诊断（如“SSH 密钥未加载或权限被拒绝”、“网络连接超时”、“未配置 origin 远端”）。

### 3.3 待提交 Diff 预览（`get_diff(file_path: str | None = None)`）
- 若 `file_path` 为空：返回 `git -c core.quotepath=false diff --stat` + 未跟踪文件列表。
- 若指定 `file_path`：
  - 已跟踪文件返回 `git -c core.quotepath=false diff -- <file_path>`。
  - 新建的未跟踪 `.md` 文件直接读取前 300 行内容展示；二进制图片（`.webp`）返回 `[Binary image file: xxx KB]` 提示。
  - 单次返回截断在 500 行以内，防止大文件撑爆浏览器。

### 3.4 一键提交与推送（`commit_and_push(...)`）
参数：`message: str, push: bool = True, pull_rebase_first: bool = False, progress_cb=None`

执行步骤（每步通过 `progress_cb` 向前端 SSE 广播进度）：
1. **前置检查（10%）**：校验仓库合法、`message` 非空；若工作区无改动且 `ahead_count == 0`，直接返回“无待提交变更”。
2. **可选拉取变基（25%）**：若 `pull_rebase_first=True` 且 `behind_count > 0`，执行 `git pull --rebase origin <branch>`；若发生冲突，自动执行 `git rebase --abort` 恢复现场并抛出明确错误提示。
3. **暂存变更（45%）**：若有工作区改动，执行 `git add -A`。
4. **本地提交（65%）**：若有暂存改动，执行 `git commit -m <message>`，并获取新生成的 `commit_hash`（`git rev-parse HEAD`）。
5. **SSH 免密推送（85% → 100%）**：若 `push=True`，执行 `git push origin <branch>`；实时将推送输出（如 `To github.com:...`）写入 SSE 日志流。
6. **审计落库**：无论成功或失败，均写入 `git_push_logs` 表，记录耗时、变更文件数、Hash 与错误信息。

### 3.5 Git 提交历史查询（`get_commits(limit=30, offset=0, search=None)`）
- 使用 `git -c core.quotepath=false log` 配合自定义分隔符（如 `\x1f` / `\x1e`）与 `--shortstat` 解析：
  - `hash`, `short_hash`, `message`, `author`, `date_iso`, `relative_time`
  - `files_changed`, `insertions`, `deletions`
  - `is_pushed: bool`（通过对比 `git rev-list @{upstream}..HEAD` 准确标记每条记录是“已推送”还是“仅本地未推送”）
- 支持 `--grep=<search>` 关键词检索提交记录，支持 `skip` + `max-count` 分页。

### 3.6 单条提交详情（`get_commit_detail(commit_hash)`）
- 校验 `commit_hash` 格式后执行 `git -c core.quotepath=false show --name-status --format=... <commit_hash>`。
- 返回该次提交的元信息 + 变更文件清单（新增/修改/删除了哪些 `.md` 论文与 `.webp` 图片）+ 可选 Diff 摘要。

---

## 4. 新增 REST API 接口（`src/paperflow/web/routes/git_ops.py`）

| Method | Path | 说明 |
| :--- | :--- | :--- |
| `GET` | `/api/git/status` | 获取 `blog_repo/` 分支、SSH 远端、ahead/behind、待提交文件列表与最近提交 |
| `POST` | `/api/git/test-ssh` | 一键检测本地 SSH 免密连接到 GitHub 是否畅通 |
| `GET` | `/api/git/diff` | 获取待提交变更概览或指定文件 Diff（`?path=...`） |
| `POST` | `/api/git/commit-push` | **仅 Git 一键提交并推送**（异步任务，返回 `task_id` 供 SSE 订阅） |
| `POST` | `/api/git/publish-and-push` | **全流程一键发布**：同步 Staging → 刷新聚合表 → Git Commit & SSH Push → 清理 PDF（返回 `task_id`） |
| `POST` | `/api/git/pull` | 执行 `git pull --rebase` 同步远端更新（冲突自动 abort 保护） |
| `GET` | `/api/git/commits` | 分页查询 Git 提交历史（支持 `?limit=30&offset=0&q=...`） |
| `GET` | `/api/git/commits/{commit_hash}` | 查看某条提交的详细文件变更列表与 Diff |
| `GET` | `/api/git/push-logs` | 查询 SQLite `git_push_logs` 历史推送审计记录 |

---

## 5. Web 前端页面设计：页面 7 — Git 发布与提交中心（Git Center）

在 `src/paperflow/web/static/index.html` 左侧导航栏新增 **【Git 发布中心】** 入口（当 `blog_repo/` 有未提交变更时，导航项旁显示橙色数字角标提示待提交文件数）：

### 5.1 顶部仓库状态条
- **分支与远端徽章**：显示 `main` 分支、`git@github.com:xxx/xxx.git`（SSH 绿色锁图标）。
- **同步状态徽章**：`↑ 待推送 N 条` / `↓ 远端新增 M 条` / `✅ 已与远端同步`。
- **快捷按钮组**：
  - **【检测 SSH 免密】**：点击后 1~2 秒内显示连通性结果与延迟（如 `✅ SSH 连接正常 (420ms)`）。
  - **【拉取远端 (Pull)】**：当 `behind_count > 0` 时高亮提醒。
  - **【打开在线博客】**：配置了 `blog_site_url` 时，一键在新标签页打开 GitHub Pages 站点。

### 5.2 核心操作面板：一键提交与推送
- **待提交变更文件区**：
  - 统计摘要（新增 X / 修改 Y / 删除 Z），按目录折叠或列表展示变更文件。
  - 点击任意文件名可在右侧抽屉/弹窗查看彩色语法高亮的 **Diff 预览**（或新建 `.md` 内容预览）。
- **提交配置与一键按钮**：
  - **Commit Message 输入框**：自动按模板预填（如 `docs: publish 4 papers (2026-11-21)`），支持随时手改。
  - 勾选框：`推送前自动拉取远端更新 (pull --rebase)`、`发布完成后自动清理本地 PDF`。
  - 主按钮 1（高亮主色）：**【🚀 一键发布并推送 GitHub（全流程）】**（合并 `publish` + `git commit & push` + `clean`）。
  - 主按钮 2（次级按钮）：**【📤 仅 Git 一键提交并推送】**（适用于你手动修改了 `mkdocs.yml` 或调整了某篇博客后直接推送）。
- **实时进度反馈**：
  - 点击后直接在卡片下方展开 **SSE 实时进度条 + 终端输出框**。
  - 推送成功后弹出成功提示条：*“✅ 已推送至 GitHub（Commit `a1b2c3d`），GitHub Actions 通常在 1~2 分钟内自动完成博客渲染。”*

### 5.3 双标签历史记录区
- **Tab 1：Git 提交历史（Commit History）**
  - 搜索框（按 Commit 信息筛选）+ 刷新按钮。
  - 时间线列表展示每条 Commit：
    - 短 Hash（点击一键复制）、提交信息、提交时间（相对时间 + 悬浮完整时间）、变更统计（`+186 / -12, 5 files`）。
    - 状态标签：`已推送`（绿色）或 `待推送`（琥珀色）。
  - **点击展开详情**：展示该次提交新增/修改/删除了哪些论文 `.md` 与架构图，支持继续点击查看单文件 Diff。
- **Tab 2：推送审计记录（Push Audit Logs）**
  - 表格展示来自 `git_push_logs` 的每次操作记录：时间、触发方式（Web / CLI）、Commit Hash、变更文件数、耗时、状态（成功/失败）；若某次因断网推送失败，直接展示完整报错信息，方便排查。

---

## 6. Phase 9 验收测试要求（`tests/test_git_ops.py`）

使用 `pytest` 在临时目录创建一个真实的本地 **Bare Git 仓库**（模拟远端 `origin`）+ 克隆的 `blog_repo/`，完全离线验证全链路（不依赖外网）：

1. **状态与变更检测**：在 `blog_repo/docs/` 新增中文文件名与英文文件名 `.md`，验证 `GET /api/git/status` 正确识别新增文件、无中文乱码、`has_changes=True`。
2. **Diff 预览与路径安全**：验证 `GET /api/git/diff?path=...` 返回正确内容；传入 `../state.db` 越界路径时必须返回 `400/403`。
3. **一键提交并推送 + SSE**：调用 `POST /api/git/commit-push`，验证：
   - 远端 Bare 仓库成功收到新 Commit；
   - `git_push_logs` 表新增 `status='SUCCESS', pushed=1` 记录；
   - `GET /api/git/status` 变为 `has_changes=False, ahead_count=0`。
4. **提交历史与详情**：调用 `GET /api/git/commits` 与 `GET /api/git/commits/{hash}`，验证返回的变更文件列表、增删行数与 `is_pushed=True` 准确无误；传入非法 Hash（如 `abc; rm -rf`）必须返回 `400/422`。
5. **远端领先冲突保护**：在另一临时克隆向 Bare 仓库先推一条提交，验证 `behind_count == 1`，调用 `POST /api/git/pull` 后自动同步成功且不丢失本地修改。
