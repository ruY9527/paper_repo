# Phase 15 验证证据

## Goal Closure
- Goal status：done。
- Success evidence：Fix 1～Fix 10 均有代码与隔离测试；最终 `python -m pytest -v` 为 240 passed, 1 warning in 72.66s；真实 `python -m paperflow build-check` 为 0 errors / 0 warnings / 1970ms，exit code 0。
- Stop state：done；无 Git commit/push（目录无 Git 元数据，且用户未要求）。
- Non-goals respected：未删除真实论文，未做计划外 UI 改版，未执行外部网络抓取或真实 LLM 解析。

## Targeted Verification
- `tests/test_pipeline_closure.py`：13 passed, 1 warning in 2.62s；覆盖跨天发布、单篇准备、Paywall 三入口、共享发布、清理器、图片路径、topic 重打分、dry-run、自动入队、topics pipeline、KPI、动态导航、热重载和日常脚本契约。
- Fix 1 相关：8 passed；Fix 2 相关：22 passed；Fix 3 修正后：9 passed；Fix 4 相关：64 passed；Fix 5 相关：7 passed。
- 写保护后新增的 6 个隔离修复：6 passed, 1 warning in 2.00s。
- 收尾对 `scripts/run_daily_fetch.ps1` 做 Windows PowerShell 5.1 `Parser.ParseFile` 检查，发现无 BOM UTF-8 导致 10 个编码解析错误；显式 UTF-8 `ParseInput` 为 0 错误，证明结构有效。已补 UTF-8 BOM（`EF-BB-BF`），随后 `ParseFileErrors=0`，并在闭环测试中加入 BOM 回归断言。

## Full Regression
- 修改前基线：227 passed, 1 warning in 65.30s。
- 第一轮全量：234 passed / 6 failed；失败全部来自 `tests/conftest.py` 写保护发现的既有测试真实路径写入。
- 修复 `tests/test_blog_pagination.py`、`tests/test_venue_links.py`、`tests/test_paywall.py`、`tests/test_preview_and_prompts.py` 后，最终全量：240 passed, 1 warning in 72.66s，exit code 0。
- 唯一 warning：`fitz` API deprecated，与本次功能改动无关。

## Real Build Gate
- 命令：`python -m paperflow build-check`。
- 目标：真实 `paper_repo/`，输出仍由 `MkDocsService` 导向 `workspace/tmp/`。
- 结果：通过；错误数 0，警告数 0，耗时 1970ms，exit code 0。

## Governance and Retirement
- 单篇发布唯一所有者：`src/paperflow/publisher/blog_articles.py:publish_one()`；`sync_blog.publish`、`web/routes/analyzer.py`、`web/routes/staging.py` 均调用它。
- 旧 `_fix_image_paths` 已退休；全 `src/` 搜索无残留，图片规则归一到 `src/paperflow/utils/figure_links.py`。旧格式兼容保留；退休触发条件为不再存在旧 staging Markdown。
- 配置重载唯一入口：`src/paperflow/web/task_manager.py:reload_config()`；settings/topics/paywall 均复用，无其他 `manager.config = load_config`。
- 待解析状态唯一常量：`PENDING_ANALYSIS_STATUSES`；Dashboard 与 analyzer 共用。
- 所有触及的维护文件均低于 800 行软压力线；新增 preparation/figure_links/conftest 责任单一。复杂度状态：within-budget。

## Fix 10 Data Cleanup
- 删除：`paper_repo/docs/papers/2026/CVPR/p0.md`、`p1.md`、`p2.md`、`p3.md`。
- 删除：`workspace/staging/2026-03-16/TODAY_DIGEST.md` 及为空的 `workspace/staging/2026-03-16/`。
- 写保护追加发现并删除：`workspace/inbox_pdfs/_processed/doi_abc123.pdf`、内容为 `# 测试修改` 的 `workspace/backups/prompts/topic_agent_20261126_164656.md`。
- 所有删除均先 Resolve-Path 并验证位于目标工作区；历史 Prompt 备份未批量删除。
- `tests/conftest.py` 自动拦截对真实 `workspace/`、`paper_repo/`、`config.yaml` 的 Path/open/shutil/sqlite 写入；读取真实模板仍允许。

## Evidence Boundary
- Evidence strength：A（针对用户指定的代码、隔离回归与真实 MkDocs 构建验收）。
- Covered scope：Phase 15 全部十项、240 项测试、真实 strict build。
- Uncovered scope：未执行真实外部出版商/arXiv 网络请求、未调用真实 LLM、未运行实际 `run_daily_fetch.ps1` 的日常生产任务；这些外部动作在隔离测试中 fake/mock。
- Residual risk：外部服务自身可用性与响应变化不属于本次离线验收取证范围。
