# Web 控制台「刷新按钮」Bug 修复记录

- **日期**：2026-11-21
- **模块**：`src/paperflow/web/static/index.html`、`app.js`（PaperFlow Studio 前端）
- **报告现象**：点击右上角【刷新】按钮后，页面表格、图表等出现"追加"/异常现象
- **结论**：已定位并修复 3 类根因，Playwright 真实浏览器回归确认零 JS 错误、DOM 稳定

---

## 一、复现与诊断方法

1. 启动本地服务：`python -m paperflow ui --port 8231`
2. 用 Playwright（`playwright.sync_api`）无头浏览器打开首页，监听 `pageerror` 与 `console.error`
3. 点击【刷新】按钮 N 次并切换所有视图，对比 DOM 快照：
   - `document.querySelectorAll('*').length`（总节点）
   - `canvas` / `.kpi-card` / `.nav-btn` / `table.tbl` / `tbody tr` / `template[x-for]` 数量

### 关键发现（第一次复现）

DOM 节点数**并未真正增加**，但控制台持续抛出 6 个 JS 异常：

```
TypeError: Cannot read properties of null (reading 'status')
TypeError: Cannot read properties of null (reading 'percent')
TypeError: Cannot read properties of null (reading 'stage')
TypeError: Cannot read properties of null (reading 'file_path')
TypeError: Cannot read properties of null (reading 'content')
TypeError: Cannot read properties of null (reading 'save')
```

这些异常导致 Alpine.js 在渲染中途抛错，DOM 更新被截断/残留，用户直观感受就是"表格、图表追加错乱"。所以**真正的 bug 是 JS 运行时异常，而不是简单的重复插入 DOM**。

---

## 二、根因分析

### 根因 1：`x-show` 不阻止子表达式求值 → null 属性访问（5 个错误）

Alpine.js 的 `x-show` 只是切换 CSS `display`，**不会**阻止内部绑定的求值。以下模板在初始状态（对应数据为 `null`）时仍被求值并抛错：

| 位置 | 表达式 | 初始状态 |
| :--- | :--- | :--- |
| 任务中心进度卡 | `activeTask.status` / `.percent` / `.stage` | `activeTask = null` |
| Git Diff 面板 | `diffData.file_path` / `.content` | `diffData = null` |
| 提交详情 | `commitDetail.files`（`x-for`） | `commitDetail = null` |

> 例：`<div class="panel" x-show="activeTask">...activeTask.status...</div>` —— 元素隐藏了，但 `x-text="activeTask.status"` 照样执行。

### 根因 2：Chart.js 对隐藏 canvas 绘制 → `reading 'save'`（第 6 个错误）

刷新按钮调用 `refreshAll()` → `setTimeout(renderCharts, 50)`。若此时不在仪表盘视图（或 canvas 处于 `display:none`），Chart.js 仍会 `new Chart(hiddenCanvas)` 并在动画绘制时调用 `ctx.save()`，而隐藏 canvas 的 2D context 为 `null`：

```
at Ie (chart.umd.min.js)
at _drawDataset / _drawDatasets / draw / _update
→ TypeError: Cannot read properties of null (reading 'save')
```

此外 `switchView('dashboard')` 与 `refreshAll()` 各自用固定 `setTimeout` 调度 `renderCharts()`，连续点击会叠加多次 `new Chart`，存在重复创建实例风险。

### 根因 3：刷新按钮功能不完整

`refreshAll()` 原来只刷新 KPI/summary，用户在其他视图点【刷新】时表格数据保持不变，表现为"刷新无效"。

---

## 三、修复内容

### 1. 模板 null 守卫（`index.html`）

- 任务进度卡：`<div x-show="activeTask">` → `<template x-if="activeTask">`（`x-if` 在 false 时不渲染内部节点，彻底不求值）
- Git Diff 面板：同样改为 `<template x-if="diffData">`
- 提交详情：`x-for="f in commitDetail.files"` → `x-for="f in (commitDetail && commitDetail.files || [])"`
- 进度条表达式补默认值：`activeTask.percent` → `(activeTask.percent||0)`

### 2. Chart.js 生命周期修复（`app.js`）

- 新增 `scheduleCharts()`：合并多次调度（清除上一个 timer），避免重复 `new Chart`
- `renderCharts()` 增加三重守卫：
  1. `this.view === 'dashboard'`
  2. canvas 元素存在且 `el.offsetParent` 非空（真实可见）
  3. 不满足则跳过；切走视图时调用 `destroyCharts()` 销毁实例
- 关闭图表动画（`animation:false`），避免隐藏/切换时的异步绘制异常

### 3. 刷新语义修复（`app.js`）

`refreshAll()` 现在按当前视图刷新对应数据：

```js
switch (this.view) {
  case 'tasks':    this.loadHistory(); break;
  case 'papers':   this.loadPapers(); break;
  case 'staging':  this.loadStaging(); break;
  case 'storage':  this.loadStorage(); break;
  case 'settings': this.loadSettings(); break;
  case 'git':      this.loadGitStatus(); this.loadCommits(); this.loadPushLogs(); break;
}
this.pollActive();
```

### 4. SSE 连接管理（顺带加固）

为任务 SSE 与 Git SSE 保存当前 `EventSource` 句柄（`_stream` / `_gitStream`），新建前先关闭旧连接，终态/出错时置空，杜绝连续任务时旧连接残留导致日志串台或重复追加。

---

## 四、验证结果

| 验证项 | 结果 |
| :--- | :--- |
| `node --check app.js` | EXIT=0 |
| Playwright 首页加载 + 7 个视图切换 | JS 错误数 **0**（修复前 6） |
| 连续点击刷新 5 次 + 跨视图切换 | JS 错误数 **0**；canvas 恒为 2、KPI 恒为 8、nav 恒为 7、表格恒为 4、`template[x-for]` 恒为 12 |
| 同一视图重复刷新 | DOM 节点数不增长（数据行仅随数据库内容变化，不随刷新叠加） |
| 全量 `pytest -q` | **77 passed** |

> 调试期间向 `state.db` 写入的 2 条 `arxiv_dbg_*` 测试论文已清理，账本恢复为 0 篇。

---

## 五、经验与预防

1. Alpine.js 中 **`x-show` ≠ 条件渲染**：凡数据可能为 `null` 的子表达式，必须用 `x-if`（`<template>`）或可选链/默认值保护。
2. Chart.js / ECharts 等画布库**禁止对 `display:none` 的 canvas 创建实例**；必须在可见性确认后创建，切走视图时 `destroy()`。
3. 定时调度类操作（图表重绘等）要做**去抖合并**，否则连续点击会叠加实例。
4. 纯前端 bug 建议用 Playwright 监听 `pageerror` 复现——DOM 数量有时正常，但异常会破坏后续渲染，仅靠肉眼判断"追加"容易误诊。
