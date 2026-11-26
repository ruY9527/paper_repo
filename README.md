# PaperFlow 2026

> 顶级期刊与会议论文 **采集 → 去重分级 → AI 自动解析 → 校验 → 知识聚合 → 发布上线 → 可视化运维** 的一站式本地流水线。

PaperFlow每天从 **CVPR / ECCV / ICCV / NeurIPS / ICLR / AAAI / TPAMI / TIP / IJCV** 九大顶会顶刊抓取最新论文，用个人兴趣画像做 S/A/B 分级，支持**研究方向精准检索**（今年优先、去年兜底、更早硬过滤）、**受限出版商过滤与手动补传**、**Claude CLI + DeepSeek Harness 双模式 AI 解析**、**Prompt 模板工作室**、**发布前 MkDocs 严格门禁**，最终一键发布到 GitHub Pages。全流程既可命令行操作，也可在浏览器控制台完成。

**在线博客（已上线）**：<https://ruy9527.github.io/paper_repo/>

---

## 单仓三分支架构与新机器还原

本项目使用同一个 GitHub 仓库 `git@github.com:ruY9527/paper_repo.git` 的三条独立分支，不使用 Git 子模块：

| 分支 | 内容 | 本地位置 |
| :--- | :--- | :--- |
| `backend` | PaperFlow 后端引擎、测试、示例配置与后端 CI | `paper_analysis/` |
| `main` | MkDocs 博客源文件与博客部署配置 | `paper_analysis/paper_repo/` |
| `gh-pages` | GitHub Pages 构建产物，由博客部署流程维护 | 无需单独克隆到后端工作区 |

`paper_analysis/` 与 `paper_analysis/paper_repo/` 是两个独立的 Git 工作区，各自拥有 `.git`。外层 `.gitignore` 忽略 `paper_repo/`，因此后端提交不会混入博客文件；后端 CI 也仅在 `backend` 分支触发，不影响 `main` 分支的博客部署。日常操作时不要在外层切换到 `main`，而应让内层工作区始终停留在 `main`。

在新机器上按顺序分别还原两个分支：

```powershell
# 1) 后端分支克隆到 paper_analysis
git clone -b backend --single-branch git@github.com:ruY9527/paper_repo.git paper_analysis
cd paper_analysis

# 2) 博客 main 分支克隆为独立的内层工作区
git clone -b main --single-branch git@github.com:ruY9527/paper_repo.git paper_repo

# 3) 准备本地配置并验证环境（真实 config.yaml 不进入 Git）
Copy-Item config/config.example.yaml config/config.yaml
pip install -e .
pytest -v

# 4) 确认双仓分支与远端隔离
git branch --show-current                         # backend
git remote get-url origin                         # git@github.com:ruY9527/paper_repo.git
git -C paper_repo branch --show-current           # main
git -C paper_repo remote get-url origin           # git@github.com:ruY9527/paper_repo.git
```

---

## 一、环境要求

| 项目 | 要求 |
| :--- | :--- |
| 操作系统 | Windows（脚本为 PowerShell） |
| Python | `>= 3.10`（当前实测 3.13） |
| Git | 需安装并加入 `PATH`（博客仓库提交推送） |
| 浏览器 | 现代浏览器（Web 控制台） |
| mkdocs | `mkdocs-material` + `pymdown-extensions`（`pip install -e .` 已含可选依赖需单独装） |
| AI 解析（可选） | 本地 `claude` CLI（已配 Kimi K3）；或 DeepSeek Harness Web（默认 `http://127.0.0.1:3080/`，可在【AI 解析中心】修改）。**模型列表自动读取本地 DSH 配置**（`~/.dsh/profiles/web/cordis.patch.yml`），在【AI 解析中心】下拉选择，共 27 个模型 / 4 提供方（kimi-code、workbuddy、google-gemini、volcengineark） |
| GitHub | `https://github.com/ruY9527/paper_repo`（SSH 免密推送） |

**安装**（在**项目根目录**执行，会注册 `paperflow` 命令）：

```powershell
cd E:\thesis-code\gemini_env\other_action_solution\paper_analysis
pip install -e .
# 若需博客构建 / 测试 / Web 上传：
pip install mkdocs-material pymdown-extensions pytest pytest-mock respx python-multipart
```

> 关键：项目是 `src/` 布局，必须先 `pip install -e .`。安装后 `paperflow <命令>` 与 `python -m paperflow <命令>` 均可。
> CLI 已在入口自动把 stdout/stderr 切为 UTF-8，Windows GBK 控制台也能正常输出 `✓`。

---

## 二、5 分钟快速开始

```powershell
# 1) 安装 + 初始化（创建 workspace、SQLite 账本、paper_repo 骨架）
pip install -e .
python -m paperflow init

# 2) 打开本地 Web 控制台（自动开浏览器）
python -m paperflow ui --open
# 浏览器访问 http://127.0.0.1:8000

# 3) 建议顺序（Web 控制台里点，或命令行）：
python -m paperflow fetch                    # 拉取 9 大顶会顶刊最新论文（自动补录）
python -m paperflow topic-run                # 追新所有启用的研究方向订阅
python -m paperflow export-queue             # 导出待 AI 分析队列
python -m paperflow analyze                  # Claude CLI 全自动解析（可选）
python -m paperflow validate                 # 校验 staging MD、提取 metrics
python -m paperflow build-check              # 发布前 mkdocs --strict 门禁
python -m paperflow publish --clean --push   # 发布并推送上线
```

---

## 三、已完成功能（Phase 1–13）

### Phase 1–3：采集、去重、分级
- **多源采集**：arXiv（每日增量 + 顶会 comment 匹配）、OpenAlex（TPAMI/TIP/IJCV 及会议）、OpenReview（ICLR/NeurIPS），带限流（arXiv 3.1s / OpenAlex 0.5s / OpenReview 1s）与指数退避重试。
- **断点补录**：SQLite 水位线记录拉取进度，关机/断网后按天切片追赶；支持任意区间手动补录（Web【任务中心】带日期快捷预设、Venue/数据源标签多选、区间校验）。
- **方向 / 关键词补录**：任务中心补录中心可切换「按日期区间」与「按方向/关键词」；方向模式复用方向检索的「优先年份填满 → 兜底 → 硬过滤」策略，输入即显示该方向历史检索次数与上次新增数（检索台账），补录结果写 `topic_search_runs`，防无意义重复检索。
- **去重加固**：入库去重最优先按 `paper_uid`（DOI/arXivID/标题哈希强标识）判定，修复「同 UID、标题轻微变化导致 UNIQUE 冲突」漏洞；重复补录只补新论文、不覆盖原记录。
- **智能去重**：DOI > arXiv ID > OpenReview ID > 标题哈希，多源命中补全字段不覆盖状态。
- **兴趣雷达**：关键词加权、关注学者/机构、GitHub 代码嗅探、S（精读）/A（速览）/B（归档）分级。
- **单篇插队**：粘贴 arXiv 链接或 DOI，强制 S 级进入队列。

### Phase 4–5：PDF、抽图、队列、校验、清理
- **PDF 下载**：S 级原子下载（`.part` → `%PDF` 头校验 → `os.replace`），超限/反爬页拦截，失败降级 A 级。
- **资产抽取**：PyMuPDF 全文提取（截断 References）、前 4 页架构图转 WebP（≤1200px，质量 80）。
- **分析队列**：`workspace/queue/YYYY-MM-DD/<paper_uid>/` 输出 `meta.json` / `extracted_text.md` / `prompt.md` / `queue_manifest.json`。
- **严格校验**：Frontmatter 必填字段、UID 一致性、正文长度；`PAPERFLOW_METRICS_JSON` 自动入库（metrics 字段为任意嵌套 dict/list 时自动序列化，不会因模型输出结构不合规阻断发布）。校验通过时把精读笔记里的有效 `code_url` 回写账本（过滤「未列出代码链接」等否定文案），确保首页「带开源代码」统计准确。
- **用完即焚**：发布后安全删 PDF 与队列目录，路径越界硬保护（绝不删 `state.db` / `paper_repo/`）。

### Phase 6–7：博客发布与自动化
- **知识矩阵**：首页看板、Venue 年度总表（含受限标注；9 大顶会顶刊 + 数据中的其它来源如 arXiv 预印本）、**跨论文能力对照**、开源精选、周报、**方向专题页**。首页「各顶会/顶刊收录数量」按「今年 / 去年 / 往期 / 合计」分列统计，数字可点击跳转对应 Venue 年度页，总数与账本一致。能力对照页采用「一篇一卡、研究任务/方法骨架/数据集/核心结论/创新点分行」的可读布局，兼容 AI 输出的纯文本/list/嵌套 dict，长文本截断并链接原文，不再是不可读的宽表。所有指向论文精读页的链接只给**已发布**论文（有 `md_blog_path`），保证 `mkdocs build --strict` 零断链警告。
- **一键发布**：同步 MD/WebP 到 `paper_repo/`，Git 提交/SSH 推送，自动清理。
- **Windows 定时**：每天 08:00 `fetch → topic-run → export-queue`，`-StartWhenAvailable` 关机补跑。

### Phase 8：Web 控制台（PaperFlow Studio）
12 个可视化页面（与 CLI 共享内核）：

1. **总览仪表盘**：KPI、Venue 堆叠图、30 天趋势图、水位线提示。
2. **任务中心**：SSE 实时进度、终端日志、手动补录中心、历史记录。
3. **论文账本**：多维筛选、提权/降权/跳过、重试、BibTeX。列表分页（每页 20/30/50 可选，后端 total 驱动）。每行标题下展示**关键词标签 + 关键时间点**（📥 入库日期 / 📄 下载时间 / 🤖 解析时间）；「🚀 流水线」按钮打开处理流水线视图：采集入库 → 下载 PDF → AI 解析 → 发布博客四阶段，每步显示具体时间，已完成/当前/待进行一目了然，并给出「下一步建议」与直达入口。`papers` 表新增 `downloaded_at`（首次转 DOWNLOADED 自动记录、幂等迁移不覆盖），账本 API 一次查询补齐本页解析时间避免 N+1。
4. **AI 解析中心**：**引擎可插拔**——解析引擎为单个下拉选择（数据驱动自 `/api/analyzer/engines`，新增引擎只注册不改前端），当前含 Claude CLI 全自动、DeepSeek Harness headless 全自动（`dsh --profile headless`，stdin 喂 Prompt、stdout 收结果，选中模型通过临时 `--patch` 注入）、Harness Web 手动协作（复制 Prompt / 粘贴回填）。**论文队列、进度、结果、发布与引擎解耦，保持稳定**。按引擎能力自动切换操作区（全自动→解析按钮；手动→协作工具）。**模型下拉选择**：自动读取本地 DSH 的 27 个模型（kimi-code / workbuddy / google-gemini / volcengineark），按提供方筛选。**支持本地已下载 PDF 直接解析**：队列显示「已导出任务(QUEUED)」和「本地已下载 PDF(DOWNLOADED)」，可点「导入本地 PDF」或拖拽。**进度与断点**：队列顶部显示「解析中/已解析/失败/中断待续」分类统计，每行显示上次解析状态；解析开始即落 `RUNNING` 审计（含 stage 阶段），进程重启自动把遗留任务标记为 `INTERRUPTED`；「🔄 断点续传」跳过已成功论文续跑剩余。进度用 SSE + 每 3 秒轮询双通道防卡住。**解析结果闭环**：每行有「👁️ 结果」在本地弹窗查看 staging MD，「🌐 发布」一键同步到 `paper_repo/docs/papers/...`（含 WebP 图片，状态转 PUBLISHED）。
  > **Harness headless 模型说明**：headless 实际只加载 `dsh-base + dsh-headless + dsh-connect-workbuddy`，全自动解析固定走 **workbuddy/hy4flash（免费额度，已实测 13 节分析跑通）**。模型下拉选到 headless 不支持的 provider（kimi-code / google-gemini / volcengineark 仅 Web profile 可用）会自动回退到 workbuddy/hy4flash 并记日志；手动协作模式才用浏览器里选定的任意模型。
5. **待审工作台**：在线 Markdown 编辑 + 实时预览 + 个人批注 + WebP 缩略图。
6. **存储治理**：占用统计、Dry-Run 清理预览、一键清理。
7. **设置中心**：关键词/雷达/阈值可视化编辑、备份写入、重新打分（合并语义，不丢新节点）。
8. **Git 发布中心**：SSH 检测、Diff 预览、构建校验、本地预览、一键发布推送、提交历史/审计、Pages 状态提示。
9. **方向精准检索**：实时检索式预览、快捷方向、SSE 进度、2026/2025 分年展示、常驻订阅管理、检索历史。
10. **Prompt 工作室**：5 套内置模板 + 方向自动路由、变量快捷插入、真实论文试渲染、备份/恢复。
11. **受限论文清单**：出版商筛选、单篇上传/拖拽补传、搜 arXiv、转摘要速览、扫描收件箱、导出清单、域名名单管理。
12. **网站收录中心（网址收藏夹）**：收藏网址+名称、可选自动填名、编辑维护、搜索/分类/标签筛选、按星级/常用排序、一键打开与复制、批量收藏、分类管理、一键生成博客导航页。

**待审 → 发布 → 查看闭环**：待审工作台选中已通过校验的论文 → 点「🌐 发布到博客」单篇发布（写入 `paper_repo/docs/papers/<年份>/<Venue>/<uid>.md` + 复制 WebP，状态转 PUBLISHED）。**发布状态可见、防重复**：待审列表每项标注「🌐 已发布」，已发布论文的按钮变为「✓ 已发布 · 查看博客」且发布接口幂等（重复点击不改文件、返回 already_published），发布后自动刷新列表与已发布区。页面底部「已发布到博客」区以博客仓库实际文件为真相源列出所有文章（标题/路径/字数/Git 状态：已推送/已提交未推送/未提交），点「查看」可读全文。Git 推送审计见【Git 发布中心】提交历史。

### Phase 9：Git 发布与提交历史
SSH 免密非交互检测、彩色 Diff（中文路径不乱码）、一键发布推送、`git_push_logs` 审计、`pull --rebase` 冲突保护。

### Phase 10：方向精准检索与两年时效
- **时效策略**：2026 优先填满配额 → 不足才用 2025 补齐 → ≤2024 硬过滤并统计 `filtered_old_count`。
- **查询解析**：中英文/缩写/`+` 组合 → arXiv/OpenAlex 检索式，同义词词典扩展。**中文方向词自动英译**：首次走免费 MyMemory API（`api.mymemory.translated.net`，无需 key）翻译成英文并缓存到 `workspace/topic_translations.json`，后续同词直接命中缓存零网络；翻译后再查同义词典拿扩展词，API 失败保留原文不阻断检索。**查询解析采用词典最长匹配扫描**（不依赖枚举连接词）：从输入从左到右用同义词典 key 最长匹配切出概念，连接词/助词（与、和、以及、的、or…）按「最长优先」跳过，切不出词典 key 的中文片段才整段翻译，翻译失败则丢弃而非用中文污染英文检索式。因此换任何新词/新连接词都不会因「整词误译」零命中；`agent与图像融合`→agent + 图像融合两组，`HSI-MSI图像融合` 作为复合概念保持单组。
- **检索→下载→解析闭环**：方向检索勾选「自动下载 S 级 PDF」后，下载完成会**自动导出分析队列**（`download_s_papers` → `export_queue`），论文状态 SCORED→DOWNLOADED→QUEUED，可直接到 AI 解析中心解析，无需手动再导出。队列导出改为**合并式**（重复导出不清空已有 manifest），避免检索内自动导出与流水线队列步骤互相覆盖。
- **排除词豁免**：Topic 模式命中方向时豁免全局 `exclude_keywords`（如搜 HSI-MSI 不被 hyperspectral 扣分）。
- **常驻订阅**：3 个默认方向（Agent / Agent+图像融合 / HSI-MSI 图像融合），`topic-run` 批量追新。
- **自动打通**：检索后 S 级自动下载 PDF，与手动补录/队列/分析流程一致。

### Phase 11：AI 解析引擎
- **Claude CLI（Kimi K3）**：`Popen` 非交互 stdin→stdout，超时/取消保护，Markdown 清洗器（去思考前缀/围栏），校验失败带报错自修复重试。
- **DeepSeek Harness Web 协作**：一键复制 Prompt、粘贴回填自动校验入库、整批指令。
- **OpenAI 兼容 API**：预留适配（可选）。
- **解析审计与错误详单**：`analysis_runs` 表记录引擎/模型/耗时/重试/阶段/成功失败；下游 AI 解析出错时结构化记录 `error_detail`（错误类型、CLI stderr、HTTP 状态码、响应体片段、退出码）与 `errors_json`（校验错误列表），前端审计历史点「🔍 详情」查看完整错误现场。

### Phase 12：构建门禁与 Prompt 工作室
- **MkDocs 严格门禁**：`[sys.executable, -m, mkdocs, build, --strict]`，输出到 `workspace/tmp/` 临时目录并清理，**绝不在 `paper_repo/` 残留 `site/`**；失败拦截 git commit/push 并高亮报错文件。
- **本地预览**：一键 `mkdocs serve :8001`，FastAPI lifespan + atexit 双保险清理子进程。
- **Prompt 模板**：5 套内置（通用 S/A、Agent、HSI-MSI 融合、Agent+图像融合），按方向自动路由；**S 级默认 13 节深度分析**（研究问题/背景/作者思考路径重建/Intuition/方法 pipeline/数学推导/实验设计/takeaways/脆弱假设/最小复现/反例/后续调研/follow-up idea），Karpathy + Kaiming He 风格，严格区分「论文声称/文献结论/合理推断/猜测」四类信息；渲染用**正则白名单替换 `{{var}}`，严禁 `str.format()`**（防 LaTeX/JSON 花括号报错）；修改自动备份到 `workspace/backups/prompts/`。Claude CLI 与 DeepSeek Harness 共用同一 `prompt.md`，改一处两端生效。**提示词完整性保证**：13 节提示词本体在任何输入预算下都完整送达下游 AI，超长论文只截断正文、不截提示词；CLI 下游通过 `communicate_once` 单次写入完整 prompt（杜绝旧实现重复写入导致的拼接乱码）。**S 级统一使用用户指定的提示词原文**（含 Karpathy/Kaiming 风格与 PDF 阅读指令），不再被方向模板覆盖。**PDF 一起送给下游**：解析前把本地 PDF 复制进任务包 `queue/<date>/<uid>/<uid>.pdf`，并把该文件的绝对路径写进提示词「本地 PDF 绝对路径」，agent 型下游（Claude CLI / Harness headless）可直接读取 PDF；抽取全文作为兜底。更新提示词后已入队论文的 prompt 也会自动重渲染。

### Phase 14：网站收录中心（网址收藏夹）与博客导航页
- **定位**：这是**网址收藏夹（Bookmark Hub）**——登记并维护常用网址供后续查找使用，**不抓取网站内容**。收录只需网址 + 名称，自动抓取仅为「可选：帮我填名称」，失败不影响入库。
- **URL 标准化去重**：去 `utm_*`/末尾斜杠/fragment、主机名小写、仅允许 http/https，防重复收藏。
- **批量收藏**：多行网址、Chrome/Edge `bookmarks.html`（H3 文件夹→分类映射，重复自动跳过），纯登记不抓取。
- **维护与使用**：编辑网址/名称/分类/标签/备注/星级/置顶/公开；搜索（名称/网址/标签/备注）、分类与标签筛选、按「最近/星级/常用/名称」排序；一键打开、复制网址、记录打开次数（常用优先排序）。
- **链接可用性（可选）**：HEAD 优先/405 回退 GET，并发探测 `OK/SLOW/DEAD`，仅作辅助工具，不影响收藏本身。
- **博客导航页（分享副产品）**：生成 `paper_repo/docs/sites/index.md`（`grid cards` 卡片 / `table` 表格，精选置顶区置顶），幂等更新 `mkdocs.yml`。**严格只渲染 `is_public==1`，私密书签绝不外泄**。

### Phase 15：一键全自动流水线与可插拔引擎
- **一键全自动**：【AI 解析中心】顶部「🚀 一键全自动」或 CLI `paperflow pipeline-run`，单任务串起 **采集 → 导出队列 → AI 解析（选定引擎）→ 校验发布 → 清理**，全程无人值守、SSE 实时阶段进度、可随时停止。
- **DeepSeek Harness 双模式**：「DeepSeek Harness」= headless CLI 全自动（stdin 提交提示词 + PDF 路径）；「Harness Web（附件模式）」📎 = PDF 作为附件上传 + 提示词原封不动提交——自动启动专用 `dsh web --port 0 --no-open` 捕获 token URL，Playwright 上传 PDF 附件并把 `config/prompts/paper_review_verbatim.md` 逐字填入发送，抓回复后补 frontmatter 回填。提示词原文含 13 节 + Karpathy/Kaiming 风格，绝不注入路径/正文/输出约束。
- **HTTP 环境兼容**：自动清理 Windows 畸形 `NO_PROXY`（`[::1]`），避免 httpx `InvalidURL`，采集/抓取不再因代理配置失败。

### Phase 13：受限出版商过滤与手动补传
- **事前过滤**：命中 IEEE/Springer/Elsevier/ACM/Wiley/T&F 域名且无 arXiv 开放版时，**不发起 HTTP 下载、不标 FAILED**，写入 `paywall_papers` 表。
- **OA 抢救**：arXiv 精确同名（标题归一化全等）自动放行下载。
- **动态兜底**：未知域名 401/403 或 HTML 登录页自动归入受限表。
- **手动补传**：单篇 `%PDF` 校验 + 抽文本/抽图 + 升级 DOWNLOADED；收件箱 `workspace/inbox_pdfs/` 按 UID→DOI→标题相似度自动匹配；导出 MD/CSV 待下载清单。
- **博客标注**：Venue 总表显示 `🔒 需登录/待补传`。

---

## 四、目录结构

```text
paper_analysis/
├── config/
│   ├── config.yaml / config.example.yaml    # 主配置（11 个节点）
│   └── prompts/                             # 5 套 Prompt 模板 + templates_meta.json
├── src/paperflow/
│   ├── cli.py                               # 25 个 CLI 命令
│   ├── config.py                            # Pydantic 严格配置
│   ├── sites/                               # 网站收录：抓取/书签导入/巡检/博客渲染
│   ├── db/                                  # 10 张 SQLite 表 + 仓储
│   ├── fetchers/                            # arxiv/openalex/openreview/single/topic
│   ├── pipeline/                            # 去重/补录/打分/下载/抽图/队列/校验/清理/
│   │                                        # paywall_filter / manual_pdf / prompt_manager / topic_query
│   ├── analyzers/                           # AI 解析引擎（base/claude_cli/openai_api/runner）
│   ├── publisher/                           # 聚合/同步/git_service/mkdocs_service/digest
│   ├── utils/                               # 日志/BibTeX/通知
│   └── web/                                 # FastAPI + 12 页面 + routes/
├── workspace/                               # 运行时数据（gitignore）
│   ├── state.db                             # 永久账本（8 表）
│   ├── logs/  tmp/pdfs/  queue/  staging/   # 日志/临时PDF/队列/待审
│   ├── inbox_pdfs/                          # 手动补传收件箱
│   └── backups/prompts/                     # 模板备份
├── paper_repo/                              # 独立公开 Git 仓库（博客，已上线）
├── scripts/                                 # run_daily_fetch / install_task / start_ui / enable_pages
├── tests/                                   # pytest（117 项）
└── plan/                                    # 11 份设计文档（Phase 1–13）
```

**隔离红线**：本地引擎/`state.db`/PDF 永不进入 `paper_repo/`；清理器只删 `workspace/tmp/` 与已入库的 `workspace/queue/`。

---

## 五、CLI 命令全表

| 命令 | 常用参数 | 说明 |
| :--- | :--- | :--- |
| `init` | `--config` | 初始化工作区、数据库、模板 |
| `fetch` | `--from --to --venue --source --force --dry-run` | 拉取/补录（Venue 盲扫） |
| `add` | `--url --venue` | 单篇 arXiv/DOI 插队（强制 S） |
| `export-queue` | `--date --limit` | 导出分析队列 |
| `validate` | `--date` | 校验 staging、提取 metrics、生成速览 |
| `publish` | `--push --clean --dry-run --no-push` | 发布（含构建门禁） |
| `clean` | `--dry-run --include-staged` | 安全清理 |
| `status` | `--venue --failed` | 看板 |
| `retry-failed` | `--max-retries` | 失败重试 |
| `topic-search` | `QUERY --limit --only-primary-year --top-venues-only --download --dry-run` | 方向精准检索（默认自动下载） |
| `topic-run` | `--topic --download --dry-run` | 批量跑常驻方向订阅 |
| `topic-list` | 无 | 方向/同义词/收录统计 |
| `analyzer-check` | `--backend --probe --model --list-models` | 检查连通性 / 列出本地 DSH 模型 |
| `analyze` | `--backend --date --paper-uid --tier --limit --retry-failed --dry-run --model` | AI 批量解析（可选模型） |
| `build-check` | 无 | `mkdocs --strict` 门禁检查 |
| `preview` | `--port 8001 --open` | 本地博客实时预览 |
| `prompts-list` | 无 | 模板列表 |
| `prompts-init` | `--force` | 初始化/重置模板 |
| `paywall-list` | `--status --publisher` | 受限论文清单 |
| `paywall-rescue` | `--paper-uid --all-pending` | arXiv 同名抢救 |
| `paywall-attach` | `UID PDF_PATH` | 手动补传 PDF |
| `paywall-scan-inbox` | 无 | 扫描收件箱自动匹配 |
| `paywall-export` | `--format md\|csv --output` | 导出待下载清单 |
| `site-add` | `URL --category --title --note --tags --pin --private --no-fetch` | 收录单个网站（自动抓元信息） |
| `site-list` | `--category --public-only --dead-only --q` | 已收录网站列表 |
| `site-check` | `--category` | 死链巡检并更新状态 |
| `site-sync` | `--layout cards\|table` | 重新生成博客导航页并挂载 mkdocs |
| `pipeline-run` | `--engine --model --steps --push --clean --dry-run` | 一键全自动（采集→队列→解析→发布） |
| `ui` | `--host --port --open` | 启动 Web 控制台 |

示例：

```powershell
python -m paperflow topic-search "HSI-MSI图像融合" --limit 20   # 方向检索（2026 优先）
python -m paperflow topic-run --download                       # 追新订阅并下载 S 级
python -m paperflow analyzer-check --probe                     # 验证 Kimi K3 连通
python -m paperflow analyze --tier S                           # 全自动解析 S 级论文
python -m paperflow paywall-scan-inbox                         # 批量补传校园网下载的 PDF
python -m paperflow site-add "https://huggingface.co" --pin     # 收录网站并置顶
python -m paperflow site-check                                  # 死链巡检
python -m paperflow site-sync --layout cards                    # 同步博客导航页
python -m paperflow build-check                                # 发布前构建门禁
```

---

## 六、配置说明

`config/config.yaml`（模板 `config.example.yaml`），11 个节点：

| 配置段 | 关键字段 | 作用 |
| :--- | :--- | :--- |
| `project` | `target_year`、`paper_repo_dir` | 目标年份、博客仓库路径 |
| `sources` | `enabled`、`rate_limit_seconds` | 数据源与限流 |
| `backfill` | `default_lookback_days`、`max_slice_days` | 补录策略 |
| `interest_profile` | 关键词/雷达/`thresholds` | S/A/B 分级 |
| `storage` | `max_pdf_size_mb`、`max_figures_per_paper` | 下载与抽图 |
| `publish` | `auto_git_push`、`require_mkdocs_strict_build`、`preview_port`、`blog_site_url` | 发布门禁/预览 |
| `notifications` | `windows_toast`、`webhook_*` | 通知 |
| `topic_search` | `recency_policy`、`synonym_dict`、`subscriptions` | 方向检索/订阅 |
| `analyzer` | `default_backend`、`claude_cli`、`harness_web`、`openai_api` | AI 解析 |
| `download_policy` | `paywall_domains`、`enable_paywall_filter`、`manual_inbox_dir` | 受限过滤/补传 |

> 所有写配置的 Web 接口（设置/订阅/域名）均采用**合并语义 + .bak 备份**，不会因旧前端回传不完整配置而丢失新节点。
> 敏感信息（Webhook / Token）走环境变量 `PAPERFLOW_WEBHOOK_URL` / `GITHUB_TOKEN`，不写进仓库。

---

## 七、Windows 定时任务与常用脚本

```powershell
# 注册每天 08:00 定时任务（需管理员权限）
powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1
# 任务流程：fetch（Venue 盲扫）→ topic-run（方向追新）→ export-queue → 日志 → 播报
# -StartWhenAvailable：关机错过后开机补跑

# 其它脚本
.\scripts\start_ui.ps1        # 一键启动 Web 控制台
.\scripts\enable_pages.ps1    # 诊断/开启 GitHub Pages（404 排查）
```

- 任务名：`PaperFlow_Daily_Fetch`
- 日志：`workspace/logs/daily_YYYY-MM-DD.log`

---

## 八、典型工作流

1. **每天自动**：08:00 定时 `fetch → topic-run → export-queue`。
2. **AI 解析**：`paperflow analyze`（Claude CLI 全自动）或在 Web【AI 解析中心】用 DeepSeek Harness 复制 Prompt/粘贴回填。
3. **人工审阅**：Web【待审工作台】批注/剔除，`validate` 校验。
4. **发布**：`build-check` 门禁 → Web【Git 发布中心】一键发布推送（或 `publish --clean --push`）→ GitHub Actions 自动渲染。
5. **受限论文**：命中付费墙自动登记 → Web【受限论文清单】校园网下载后拖拽补传或扫描收件箱。
6. **存储回收**：发布后 PDF 自动删除；也可【存储治理】手动预览清理。

---

## 九、测试与验收

```powershell
python -m pytest -v                                   # 全量 117 项
python tests/smoke_e2e.py                             # 端到端冒烟
python -m mkdocs build --strict -f paper_repo/mkdocs.yml
python -m paperflow analyzer-check --probe            # AI 解析连通
```

当前状态：**227 passed**；论文账本默认每页 20 条，筛选变更自动回到第 1 页，翻页越界自动回退末页。端到端冒烟通过；`mkdocs build --strict` 零警告；在线博客 <https://ruy9527.github.io/paper_repo/> HTTP 200。

所有公开页面底部统一注入「内容由 AI 生成，请审慎甄别」声明（幂等、重建不重复），提示读者关键结论以论文原文与官方来源为准。

**标签双语展示**：首页「最近发布的高价值论文」新增「标签」列，从精读笔记 frontmatter 的 tags 读取，中英**拆开呈现、各自可复制**：英文 slug 用行内代码包裹（`` `agent` ``），中文释义单独放在后面（`` `agent` · 智能体 ``），标签之间用 `｜` 分隔；内置常用学术标签词典 + 词根推断，未收录的英文 slug 原样保留不臆造。

**数学公式渲染**：提示词要求 AI 用 `$...$` / `$$...$$` 包裹公式；同时在解析入库与博客写盘时经 `math_fix` 保守兜底——把独占成行的裸方程包成 `$$...$$`、行内「变量=(元组)」包成 `$...$`（幂等、不碰代码块与普通文本），修复 AI 常输出无定界符类 LaTeX 导致 MathJax 不渲染的问题。

**列表分页与返回**：首页「最近发布的高价值论文」超过 8 篇时自动启用客户端分页（上一页 / 下一页，零第三方依赖）；每篇精读页注入「← 返回首页」按钮，**固定在页面左侧（top:76px / left:18px），不随正文滚动**，自带内联样式（圆角胶囊、悬停反馈、窄屏自适应移到右上、手机端回归行内），自包含无需改 mkdocs.yml。

---

## 十、时间与时区约定

全项目时间统一为 **Asia/Shanghai（GMT+8）**，唯一时间源为 `src/paperflow/utils/timeutil.py`：
- 时间戳（`created_at`/`updated_at`/任务日志等）：ISO 8601 带 `+08:00`，秒精度，如 `2026-11-22T14:38:32+08:00`
- 纯日期（`fetch_date`/水位线/导航页日期）：GMT+8 当天 `YYYY-MM-DD`
- 前端展示：所有日志时间统一格式化为 `YYYY-MM-DD HH:MM:SS`（GMT+8），Z 串与 +08:00 串显示一致

历史函数名 `utc_now_iso()` 保留兼容但语义已改为 GMT+8，不再返回 UTC(Z)。

## 十一、常见问题

- **页面改动没生效 / 报错「不支持的解析后端」/ AI 解析中心看不到已下载论文**：`paperflow ui` 不会热重载代码。改过 Python/JS 后必须**关闭旧进程再重启**（`paperflow ui --open`）。控制台现在会自动检测代码指纹：若后端仍是旧进程，顶部会弹出红色横幅提示重启，按提示操作即可；也已加 no-cache 头避免浏览器缓存旧 JS，若仍异常按 `Ctrl+F5` 强刷。
- **在哪里看已获取的论文**：Web【论文账本】列出账本全部论文（含 S/A/B、各状态）；【AI 解析中心】队列显示所有可解析论文，含 `📦 队列`（已导出）与 `📄 本地PDF`（已下载待解析）两类来源。
- **`No module named paperflow`**：先在项目根目录 `pip install -e .`。
- **输出 `✓` GBK 报错**：CLI 已自动切 UTF-8；极旧终端执行 `chcp 65001`。
- **首次 `fetch` 报配置不存在**：复制 `config.example.yaml` 为 `config.yaml`。
- **在线博客 404**：GitHub Pages 需在仓库 Settings → Pages 选 gh-pages/root 开启；Web【Git 发布中心】的 Pages 状态提示与 `scripts/enable_pages.ps1` 可辅助排查。
- **Git 推送卡住**：用【Git 发布中心】「检测 SSH 免密」诊断；联网命令均非交互（`BatchMode=yes`）不会阻塞。
- **中文文件名乱码**：Git 命令已加 `-c core.quotepath=false`。
- **AI 解析连通失败**：`python -m paperflow analyzer-check --probe` 检查本地 claude CLI（Kimi K3）。
- **可选哪些模型**：`python -m paperflow analyzer-check --list-models` 列出本地 DSH 全部模型；Web【AI 解析中心】也有下拉框。模型来自 `~/.dsh/profiles/web/cordis.patch.yml`，你在 DSH 设置里增删模型后 PaperFlow 自动同步（点「刷新模型」）。
- **方向检索没下载**：`topic-search`/`topic-run` 默认自动下载 S 级，确认未传 `--no-download` 且配置未关闭。
- **模板备份**：修改 Prompt 模板后旧版自动存 `workspace/backups/prompts/`，可恢复默认。
- **误删担忧**：清理器路径越界硬校验，`state.db` 与 `paper_repo/` 永不被触碰。

---

_设计规格见 `plan/` 目录（00 总纲 + 01–10 共 11 份文档，覆盖 Phase 1–13）。_
