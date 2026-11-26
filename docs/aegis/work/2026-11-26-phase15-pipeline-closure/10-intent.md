# Phase 15 全链路闭环收口

## TaskIntentDraft
- Requested outcome：严格按 `plan/12_PIPELINE_CLOSURE_AND_BUGFIX.md` 完成 Fix 1→Fix 10，新增 `tests/test_pipeline_closure.py`，全量测试通过，真实仓库 `python -m paperflow build-check` 通过并逐项汇报。
- Parent authority：`plan/12_PIPELINE_CLOSURE_AND_BUGFIX.md`；用户明确要求逐项执行，不跳过。
- Scope：计划点名的 `src/paperflow/`、`scripts/run_daily_fetch.ps1`、`tests/`，以及明确命名的测试污染文件。
- Non-goals：不创建 Git commit/push；不重构无关模块；不删除真实 `arxiv_*`/`doi_*` 论文；不做计划外 UI 改版。
- Success evidence：针对性闭环测试、`pytest -v` 全量结果、真实 MkDocs strict build-check、逐项文件清单。
- Stop states：done / blocked / needs-verification / scope-exceeded。

## BaselineReadSetHint
- 已读：当前计划、README、pyproject、发布/校验/任务/解析路由、配置与数据模型。
- Baseline test：`python -m pytest -v`，227 passed，1 warning，65.30s（修改前）。
- TaskStartSnapshot：工作目录 `E:\thesis-code\gemini_env\other_action_solution\paper_analysis`；该目录及父级无 `.git`，无 branch/HEAD；未切换 worktree。
- Missing refs：无阻塞性缺失。Aegis helper 可执行文件未定位，按标准布局维护同一持久记录。

## ImpactStatementDraft
- 主要所有者：`publisher/blog_articles.py` 为唯一单篇发布内核；`pipeline/` 新增单篇准备辅助函数；`web/state.py` 或 `task_manager.py` 提供配置热重载唯一入口。
- 兼容边界：显式 `target_date` 仍只处理该日；批量发布仍只重建一次聚合页；旧 Markdown 图片写法继续兼容；测试与现有 API 默认行为尽量保持。
- Retirement evidence：最终搜索 `sync_blog.py` 与 `web/routes/analyzer.py`，确认没有残留独立单篇复制发布实现。
