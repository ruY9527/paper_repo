---
paper_uid: arxiv_2611.26624
title: "PlayCraft: Designing Engaging Games from Agent Play Experience"
venue: "arXiv 2026"
year: 2026
tier: arXiv preprint (v1, 19 Nov 2026; cs.AI + cs.CV; not peer-reviewed)
tldr: "PlayCraft 让一个只看画面的 foundation-model 玩家反复玩一款游戏、每局写报告并跨局保留 lessons，再让一个 crafter agent 读这些报告估计初/中/高手表现、对标定好的表现锚点，改游戏代码补差距；在 10 款 2D/3D 游戏、3 档智能设置下，它把 macro 平均 learning gain 比初始游戏提高 2.7/14.0/21.9 个百分点，learning slope 在 Medium/High 提高 2.09/2.64，两个指标 macro 平均都超过 Code 与 Policy 基线。论文的视觉玩法协议本身是一个可迁移的 Agent+图像闭环范式，但论文并没有把它用到图像融合任务。"
tags:
  - game-design
  - foundation-model-agent
  - visual-game-playing
  - mastery
  - playtest-driven-revision
  - agent-memory
  - closed-loop-agent
  - image-fusion-relevance-indirect
code_url: "https://github.com/xt4d/PlayCraft"
paper_url: "https://arxiv.org/abs/2611.26624"
---


<!-- BACK-TO-HOME -->
<style>
.pf-back-home{position:fixed;left:18px;top:76px;z-index:60;display:inline-flex;align-items:center;gap:6px;padding:7px 12px;border-radius:20px;background:rgba(99,102,241,.94);color:#fff;font-size:12px;font-weight:600;text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.22);transition:transform .15s,background .15s;backdrop-filter:blur(4px)}
.pf-back-home:hover{background:rgba(79,70,229,1);color:#fff;text-decoration:none;transform:translateX(-2px)}
.pf-back-home .pf-arrow{font-size:15px;line-height:1}
@media screen and (max-width:1220px){.pf-back-home{left:auto;right:18px;top:12px}}
@media screen and (max-width:760px){.pf-back-home{position:static;display:inline-flex;margin:0 0 14px;box-shadow:none}}
</style>
<a class="pf-back-home" href="../../../index.md" title="返回首页 · 最近发布的高价值论文">
  <span class="pf-arrow">←</span><span>返回首页</span>
</a>


# PlayCraft 深度解析：把 Agent 的"玩"变成设计证据

## 先把一件事说清楚：这篇论文和图像融合的关系

用户给的任务模板里写着"Agent 驱动图像融合论文分析"，并要求重点覆盖"Agent 在图像融合中的决策角色（动态算子调度 / 退化感知路由 / 自适应提示生成）、多模态工具链设计、融合质量提升来源"。我核对了 arXiv 原页（[arXiv:2611.26624](https://arxiv.org/abs/2611.26624)）与抽取全文，必须直说：**这篇论文不是图像融合论文，它做的是自动游戏设计**。全文没有出现 image fusion、退化感知路由、算子调度、融合指标（SSIM / PSNR / MSE）这些内容。论文里唯一的"视觉"成分是玩家 agent 看渲染帧来玩游戏（`3.2.2 Playing Stage`）。

所以本文按两件事来做：

1. 忠实拆解 PlayCraft 本身，不把游戏设计的事实硬说成图像融合的事实；
2. 在明确标注为"推断"的前提下，把它的**视觉闭环 Agent 范式**映射到图像融合场景，回答"如果把这个思路搬过来，Agent 在图像融合里能扮演什么决策角色"。这样既满足用户的侧重要求，又不伪造论文结论。

信息分级贯穿全文：【论文明确声称】= 原文写了；【文献已有结论】= 论文引用或我搜索到的外部工作结论；【合理推断】= 基于证据的迁移推理；【猜测】= 没有证据，仅作为假设。

---

## 1. 论文提出并解决什么问题？为什么重要？

### 1.1 问题本身

【论文明确声称】最近 AI agent 能从人类指令生成可玩的游戏（`Huang et al., 2026`），但生成出来的游戏不一定"engage"。论文抓住 engagement 的一个具体来源：**mastery（精通）**。Mastery 指玩家通过练习发展策略与技能来克服挑战的过程（`Koster, 2004`）。一个支持 mastery 的游戏，表现为玩家起初成功有限，但随着熟练度提升，结果显著变好（`§1 Introduction`）。

这里的关键约束是：设计 mastery 需要大量真人试玩和调参，成本高。论文要解决的问题因此可以精确表述为：

> 给定一款已经可玩但未必支持 mastery 的初始游戏 G0，能否自动把它改写成 G1…GK，使玩家在重复尝试中的表现有明显上升，而且这个上升来自更好的决策和执行，而不是来自游戏被改简单了？

### 1.2 为什么重要

【论文明确声称 + 文献已有结论】三层价值：

- **理论层**：`Koster (2004)` 认为游戏乐趣来自玩家学习游戏模式并获得精通；`Ryan et al. (2006)` 的自我决定理论把 enjoyment 和继续玩与 perceived competence 联系起来。 mastery 是衡量"engaging"的可操作抓手。
- **方法层**：过去用计算玩家（computational players）指导游戏设计，但这些玩家的行为不写真人；用试玩反馈改游戏的方法又只看整体质量，不显式看玩家通过练习变强这件事。
- **成本层**：真人试玩昂贵，自动化反复试玩可以显著降低设计迭代成本。

### 1.3 从我搜索到的后续文献看为什么这个方向在升温

我用 arXiv API 做了实际检索（2026-11-22 的快照）：
- `all:PlayCraft` 只返回 1 条，就是本文 v1（[query](https://export.arxiv.org/api/query?search_query=all:PlayCraft&start=0&max_results=20&sortBy=submittedDate&sortOrder=descending)）。说明它刚发布，还没有引用它的后续工作。
- `all:"learning gain" AND all:game AND all:agent` 返回 2 条，另一条是 `Agentic Knowledge Tracing`（[2606.25358](https://arxiv.org/abs/2606.25358)），用多 agent + BKT 从游戏事件里估计玩家的金融素养 mastery，与 193 名 K-12 参与者的学习增益显著相关（r=0.276, p=0.0001）。这侧面说明"从游戏行为里学 mastery 信号"是活跃问题。
- `all:"learn" AND all:"play" AND all:"bench" AND all:agent` 返回 25 条，包括 `CL-Bench`（[2606.05661](https://arxiv.org/abs/2606.05661)）、`PTCG-Bench`（[2605.29653](https://arxiv.org/abs/2605.29653)）、`MMG2Skill`（[2606.01993](https://arxiv.org/abs/2606.01993)）等，说明"agent 从经验中改进"本身是热点。

---

## 2. 之前有人解决过吗？为什么不够？

【文献已有结论，主要来自论文 `§2 Related Work`，我的搜索补充在括号内标注】

### 2.1 用计算玩家指导设计

- `Togelius & Schmidhuber (2008)` 演化小网格游戏规则，用神经控制器"学会玩的速度"当 fun 的代理。
- `Browne & Maire (2010)` 用 self-play 评估桌游质量；`Jaffe et al. (2012)` 用受限博弈的精确博弈论值看平衡；`Liu et al. (2017)`、`Todd et al. (2024)` 用强 agent 对弱 agent 的胜率当深度代理。
- `Nasir et al. (2026)` 的 Mortar 把这个思路用在游戏代码上，用 LLM 驱动的质量-多样性搜索演化机制，奖励"固定 agent（不同预算 MCTS、random、no-op）按预期技能顺序排位"的游戏。
- `Zook et al. (2025)` 的 Fly, Fail, Fix 用预训练 DQN 玩 Flappy Bird，再用 GPT-4.1 根据指标和帧条调管道参数。

**不足**（论文明确分析）：依赖搜索或游戏专用训练的计算玩家，行为和人不同；学陌生游戏要大量计算；几乎不解释自己的决策和困难。Mortar 用的是固定 agent，无法反映"玩家通过练习变强"的过程。

### 2.2 用试玩反馈修改生成的游戏

- `Huang et al. (2026)` 的 Play2Code：HTML 游戏生成与 rubric-blind GUI agent 试玩交替，返回 gameplay traces 和可操作反馈。
- `Wu et al. (2026)` 的 RSIGame：针对性试玩诊断问题、验证修改，另有 monitor 比较版本并保留最好的。
- `Chen et al. (2026a)` 的 Recursive Game Creator：Designer / Builder / Player / Reviewer 角色，Player 写可复用 policy 通过程序接口操作，Reviewer 用轨迹推断偏好并建议改动。

**不足**（论文明确声称）：这些方法目标是整体游戏质量，没有把"玩家通过练习提升表现"作为显式优化目标。

### 2.3 视觉游戏 agent 与经验学习

- 视觉游戏 agent：`Tan et al. (2024)`、`SIMA Team (2024)`、`Yu (2026)` 在 LOLPlay 用截图完成 9/36 个 LOL 任务、`Wang et al. (2026)` 在 GameHorizon-Bench 在线轨完成 9/20 个 Minecraft 多步任务、`Aggarwal & Welleck (2026)` 在 Gym-Anything-RT 实时通过 9%、暂停后通过 75% 的小游戏。
- 经验学习：`Reflexion (Shinn et al., 2023)` 把试验教训带入后续尝试；`Voyager (Wang et al., 2023)` 存技能复用；`Learn2Play Bench (Li et al., 2026)` 用 learning gain 衡量文本游戏里跨尝试的改进。

**不足**：这些能力此前没有被拉到一起用来"设计游戏"。PlayCraft 的空位就在这里。

---

## 3. 重建作者的思考路径（不用论文贡献当前提）

这一节模拟 2026 年 11 月之前，一个研究者看着已有技术能想到的路线。

### 3.1 观察到的失败模式

想象作者手上有两类工具，各自有明确缺陷：

**工具 A：搜索/训练型玩家。** 给它一款新游戏，它靠 MCTS 或专门训练找策略。问题是：它找到的策略和真人形成策略的路径未必一样。举具体例子：一个 MCTS agent 在 Breakout 里可能穷举出某种极精确的挡板微移打法，真人第一次玩根本发现不了。用它来指导"游戏是否支持学习"，等于用一个不学的人当学习样本。而且它几乎不说"我为什么这么做"，只给胜负。

**工具 B：LLM 游戏生成器 + 试玩反馈。** 生成一款游戏，让 GUI agent 点一遍，返回"这游戏不错/按钮太小/难度高"。反馈是整体质量导向的。具体失败模式：一个生成器可以做出一款画面完整、规则清楚、玩起来也"还行"的 Flappy Bird，但玩家第一局和第十局分数几乎一样。这游戏不 engage，因为没给"变强"留空间。现有反馈不会指出这一点，因为反馈里没有"我第几局开始会了"。

### 3.2 经验观察

作者同时看到 2026 年的视觉 foundation-model agent 已经能做三件事：
1. 从截图推断机制，用和真人一样的键鼠控制开始玩一个陌生游戏；
2. 跨尝试保留记忆、检验假设、改进策略（`Reflexion` / `Voyager` / `Learn2Play Bench` 的路线）；
3. **能用自然语言报告自己遇到什么情况、为什么这么决策、哪里困惑**。

第 3 点是关键。前面那些计算玩家给不出这个。如果 agent 能说出"我在第 3 局发现靠近靶子时风的影响变小，所以后面都先跑近再射"，这条信息对设计者是有用的：它告诉你玩家实际上是怎么学的，卡在哪里。

### 3.3 直觉跳跃

把这两边接起来：

> 如果玩家 agent 会学、会报告，那么它的**学习轨迹本身**就是一种比胜负更丰富的设计证据。既然 `Learn2Play Bench` 已经能用 learning gain 衡量 agent 有没有在学，那反过来，能不能用这个信号去**改游戏**，让这个 gain 变大？

再往下推一步：要让 gain 变大，不能只把游戏改简单。你需要一个目标结构。游戏设计理论里已有 mastery 的定义（初期成功有限，后期明显变好）。把它量化成"新手/中级/高手相对于高手参考结果的百分比锚点"，就有了可优化目标。

于是路线成型：**玩 → 报告 → 诊断差距 → 改游戏 → 再玩**，循环若干轮。这就是 PlayCraft。

### 3.4 为什么用视觉界面而不是内部状态

【合理推断】从论文 `§3.2.2` 的设定看，作者刻意让 player agent 只能看渲染帧、不能看代码、不能上网，通过模型推理产生控制动作。这样做的好处是：agent 面对的视觉线索和控制负担与真人一致，它的"困难"才可能是真人的困难。如果用内部状态（像 Policy 基线那样），agent 会看到真人看不到的东西，诊断就会偏向"信息充分条件下的最优策略"，而不是"玩家从画面能推断出的策略"。这一点在 `§4.3` 里被作者明确用来解释 PlayCraft 为什么超过 Policy。

---

## 4. 方法的 Intuition

一句话版本：

> **让一个会学、会说的视觉 agent 替你试玩十局，把它的经验报告当作游戏设计证据；再让另一个 agent 按"新手/中级/高手应该分别达到多少分"的锚点去诊断和改代码，把玩家表现的成长空间做出来。**

更小一点的版本，三类信息在循环里流动：

- ** observation（画面）** → player agent 形成 lessons 和 reports；
- **reports（自然语言plays）** → crafter agent 估计能力、预测三档表现、找差距；
- **design proposal（自然语言）** → 代码实现成新游戏 Gk+1，下一轮再玩。

这个循环的关键不是"agent 会玩游戏"，而是**两阶段分工 + 报告作为接口**：玩家负责产生"人在学什么"的一手证据，工匠负责把证据转成代码改动。两者用自然语言报告解耦，所以玩家不需要懂代码，工匠不需要重新玩。

映射到图像融合的直觉（**推断**）：把这个循环里的"游戏"换成"融合流水线"，"玩家报告"换成"融合 agent 对当前退化条件、算子选择、失败原因的报告"，"crafting"换成"调算子路由/提示/参数"，就得到一个端到端自改进的融合系统。论文没做这件事，但结构上是同构的。

---

## 5. 具体方法：完整 pipeline，用一个真实例子走一遍

### 5.1 整体结构

【论文明确声称，`§3.2.1` 与 Figure 1】

输入：初始可玩游戏 G0。
输出：修订后的游戏 GK（实验里 K=3）。
每轮 k = 0…K−1 有两个阶段：

- **Playing stage**：player agent 在 Gk 上玩 E=10 个 episode，跨 episode 保留 memory，每局写 report，汇总成 play record。
- **Crafting stage**：crafter agent 读 play record，诊断 → 提方案 → 实现，产出 Gk+1。

### 5.2 Playing stage 的细节

**Setup（`§3.2.2`）**
- 玩家上下文只有简短游戏说明：目标、基本规则、可用控制。
- 只能看渲染帧，不能看游戏代码，不能上网。
- 每个控制动作都由模型推理生成，不写程序控制游戏。

**交互循环**
- 一轮 run 包含 E 个 episode；episode 在游戏结束或活跃游戏预算 T 用尽时终止。
- 帧按间隔 O 捕获，决策按间隔 W 发生。
- 每次决策，agent 收到前一个决策间隔捕获的帧，返回下一个间隔的 action plan。
- plan 是 A 个控制动作序列，每个持续 W/A。控制动作是按键、鼠标按钮、鼠标移动的组合，也可以为空。
- plan 执行期间游戏推进并渲染帧；**模型生成 plan 时游戏计时器和动画暂停**，所以推理延迟不吃活跃游戏时间。这个设计很实际，否则 agent 想 30 秒，游戏就过了 30 秒。
- 每次 plan 同时报告可见结果（如当前分数）和简短观察笔记。

**实验参数（`§4.1.1`）**：O=200ms，W=1000ms，每次决策请求含前间隔的 5 帧，A=50 个动作（每个 20ms），T=60 秒，E=10 局。动作规划用 GPT-6.1 Sol medium reasoning，episode review 用 xhigh reasoning。

**跨 episode 学习**
- 一个 run 内保持单一对话。游戏每局重置，玩家保留记忆。
- 每局后写报告，覆盖 6 项：①起始条件；②进展（milestones 与 failures）；③最终结果；④关键决策与考虑过的替代方案；⑤对游戏的感知（机制理解、困惑点、感知难度、预期与实际结果的差异）；⑥学到的教训。
- 然后更新一份合并的自然语言 lessons：保留被支持的，合并重叠的，修改或删除被反证的。
- 所有 episode 的报告构成 play record，传给 crafting stage。

### 5.3 Crafting stage 的细节

**设计目标（`§3.2.3`）**
1. 每个熟练度层级达到对应表现目标。高手应能在预算 T 内完成目标；无目标的游戏应在 T 内体验核心循环与主要挑战。高手结果定义为 100% 参考。新手和中级分别达到 r0% 和 r1%，r0 < r1。这些结果必须来自"即使没有时间限制也仍然有利"的策略（防止靠时间限制刷分）。
2. 给玩家通过更好决策和执行来改进的有意义机会：游戏要让不同选择的收益、成本、风险清晰，且预期表现随技能继续上升。

**活跃预算 T**：论文假设玩家有有限活跃游戏预算 T，可任意设大。引入 T 是为了给表现一个参考范围，让 crafter 能找差距。改 T 会影响结果，因为 crafter 用 T 内观察到的玩法当证据。

**诊断（Diagnosis）**
- 读游戏说明、所有可用 run 的 play record、早期迭代的归档历史。
- 因为 E 局未必够玩家达到专家级，crafter 不能直接从记录里读 100% 参考。它先估计玩家在玩之前的**基线能力**，包括屏幕感知、控制执行、策略发现。论文强调：没玩过这个游戏不代表玩家不熟练。
- 从基线能力和观察到的玩法，估计当前游戏里 beginner / intermediate / expert 的预期结果，与锚点比较。
- 偏离时诊断原因，考虑：入门难度、理解/感知/执行的要求、策略选择机会、奖励结构、挑战递进、表现天花板。
- 若之前有 proposal，还检查新记录支持/反驳/未检验了其中哪些预期，决定是延续还是改方向。

**提案（Proposal）**
- 写聚焦的设计 proposal。优先做能带来新策略和有意义选择的显著改动，同时保留游戏的核心交互。
- 保持设计连贯简单，权衡每条规则的学习收益与它增加的复杂度。
- 挑战建立在玩家基线能力上，而不是假设"机制陌生"就会限制新手。
- 修订后的游戏必须视觉清晰，通过呈现和行为传达对象、动作、后果，而不是加指标 UI。
- proposal 描述每个改动及动机，并陈述新手/中级/高手的预期体验与结果，以及估计的依据和不确定性。

**实现（Implementation）**
- 在单独 session 里实现。对每个改动，先定义玩家可见的预期结果和可观察的验收检查。
- 改代码：先做基础改动，再做依赖它的改动。
- 验证：跑 build 和自动检查，实操受影响的玩法，在真实渲染器里检查受影响视觉，然后修正差异。
- 记录与 proposal 的偏离及原因；更新游戏说明，只写目标、基本规则、可用控制，其余留给玩家发现。

**实验参数（`§4.1.1`）**：锚点设新手 10–30%、中级 50–70%（相对专家在 T 内的预期结果）。design 与 implementation 分 session，都用 GPT-6.1 Sol，design xhigh reasoning，implementation max reasoning。每个初始游戏做 3 轮。

### 5.4 走一遍具体例子：Breakout

【论文明确声称，`§4.4 Qualitative Analysis`，这里按 pipeline 顺序重排】

**输入 G0**：移动挡板接球、把球弹向砖块，砖块一击即碎。

**Playing stage（PlayCraft）**：player agent 已经有意识地瞄准反弹，但清理孤立砖块需要精确的后续击球。

**第 1 轮 crafting**：crafter 读了报告后加入"护甲"机制：从下方击中会保留伤害，一发可以为后一发做准备。

**第 2 轮**：后续报告里玩家说球打到了与预期不同的列，且一连串击球只清掉很少砖。crafter 据此把挡板短按的移动速度调慢，把从下方打破砖块所需次数提高到 3；侧面或顶部命中也能清除同一行相邻的受损砖。

**第 3 轮**：crafter 让反弹角度对球击中挡板中心附近的微小位置变化不那么敏感；球第三次从下方命中时可以穿过砖块。玩家可以准备一条直穿墙的路径，或沿墙横扫的路径。

**输出 G3**：Medium/High 玩家从"安全的近垂直回球打开列"进步到"把球打进开口获得更大清除"；Low 玩家的改进主要来自更早拦截和受控清列。

**对照基线做了什么**（同一 section）：Code 用代码分析改挡板机制，让接球前停住挡板会扩大 cutting area，可把球送进砖墙底部中央通道。Policy 用控制器轨迹找到从上方进墙的有用路径和长回程，改成从上方破砖会削弱同列剩余砖，且球破坏砖后继续前进。结果上 Code 玩家早期靠停挡板进步大，后期受漏接限制；Policy 玩家学会打暴露的顶/侧并利用弱化列，但碰撞后预测误差仍导致漏接。PlayCraft 玩家在三个档位都领先，被作者归因于"better interception at Low + 更有效利用准备好的开口 at Medium/High"。

### 5.5 另一个更体现"报告驱动"的例子：Drone Delivery

**输入 G0**：按顺序收集并投递包裹，选择省电航线，接近平台时减速。

**PlayCraft 的迭代链**：
1. 玩家很快定下一条干净航线。crafter 加入高空风。
2. 玩家找到沿街道平静空气的可重复航线。crafter 把避风处限制在建筑背后。
3. 玩家报告长时间滑行会卡住进度。crafter 追到代码里的一个速度限制：进入逆风时可能突然减速。玩家还报告两次投递损伤更小但得分相同。
4. 第 3 轮：让无人机带着动量进逆风，阻力渐进减速；每次投递按剩余电量和低损伤给奖励。玩家可以先在避风处蓄速，再滑过暴露段；即使只完成部分路线，保持较好机况也能得分。

这个例子的价值在于：**"得分相同"这条报告直接暴露了奖励结构的问题**，这类信息从胜负日志里读不出来。

### 5.6 映射到图像融合：如果照搬这个 pipeline

【合理推断，非论文内容】

假设目标是把"退化图像对"融合成高质量图像，初始系统是一套手工规则或固定权重的融合流水线：

| PlayCraft 组件 | 图像融合里的对应物（推断） | Agent 的决策角色 |
|---|---|---|
| player agent 看渲染帧 | 融合 agent 看输入图像、中间融合图、质量图 | 退化感知：识别模糊/噪声/低光/错位/伪影区域 |
| 每局写 report | 每次融合写 report：哪里失败了、为什么选这个算子 | 可解释决策日志 |
| E 局跨 episode lessons | 跨样本积累"什么退化该用什么算子"的 lessons | 动态算子调度策略库 |
| crafter 读 report 诊断 | meta-agent 读 report 诊断融合缺陷 | 退化感知路由的重新设计 |
| 锚点 r0/r1/100% | 质量分层目标：差退化下达到基线分，中等退化达到目标分，简单退化达到饱和分 | 自适应提示/参数生成的优化目标 |
| 改游戏代码 | 改算子组合、提示词、网络参数、融合权重 | 端到端闭环反馈 |
| fresh run 评估 | 独立测试集上测 PSNR/SSIM/下游任务指标 | 泛化验证 |

**Agent 在图像融合中的决策角色（推断，分三类）**：

1. **动态算子调度**：面对一张具体图像，agent 根据退化区域的空间分布决定哪块用哪种融合算子（例如纹理区用细节保持分支、平滑区用加权平均分支、配准差的区域先对齐再融合）。这对应 PlayCraft 里 player 每 1 秒根据当前帧决定下一秒动作。
2. **退化感知路由**：agent 先判断"这张图主要退化是什么"，再决定走哪条处理路径。这对应 crafter 的诊断阶段：估计基线能力后判断差距原因。
3. **自适应提示生成**：当使用扩散/生成式融合模型时，agent 根据图像内容动态写提示（"保留左侧边缘的锐利纹理，抑制右侧的低光噪声"）。这对应 proposal 阶段：把诊断转成自然语言指令。

**多模态工具链设计（推断）**：视觉输入（原图、中间结果、质量热图）+ 结构化工具调用（算子库、配准工具、质量评估器）+ 文本报告接口（决策理由）。关键是像 PlayCraft 一样，**推理时暂停"环境时钟"**：在融合场景里就是工具调用和 LLM 思考不计入实时预算，只在真正执行算子时计成本。

**融合质量提升来源（推断，必须说明论文未验证）**：如果按上面映射实现，提升可能来自三处：①退化分类更准带来的路由收益；②跨样本 lessons 带来的算子选择改进；③闭环反馈让错误被下一轮修正。论文里对应的消融是 Code / Policy 两个基线（见第 7 节），但那是在游戏上的消融，不是融合质量消融。

---

## 6. 核心数学推导

### 6.1 论文里唯一的正式数学：两个评估指标

论文没有提出新模型或新损失函数，核心数学在 `§4.2` 的评估指标。数学基础很浅，我从头讲。

**背景：归一化。** 改游戏会改变可达的表现范围。比如初始 Flappy Bird 最高分 50，改完后最高分 200。直接比原始分会偏向改后的游戏。论文对每个游戏和方法的 90 个 outcome（3 档智能 × 每档 3 次 run × 每次 10 局）取最大值，把每个 outcome 除以它。这是 min-max 里的 max-only 归一化，把不同量纲压到 [0,1] 附近。

**Learning gain（学习增益）。** 直觉：比较一个 run 的前 3 局和后 3 局，看平均涨了多少。

设 ze 是第 e 局的归一化表现。前段均值：

$$
zB = (1/3) · Σ(e=1..3) ze
$$

后段均值：

$$
zL = (1/3) · Σ(e=8..10) ze
$$

学习增益：

$$
Mgain = 100 · (zL − zB)
$$

单位：百分点（percentage points）。为什么乘 100？因为归一化后在 0–1 之间，乘 100 变成人类好读的分数。为什么用 1–3 和 8–10？这是 `Learn2Play Bench (Li et al., 2026)` 的约定，避开中间局，取早期和晚期两个稳定段。

举例（论文 Table 2，Medium 档）：PlayCraft T-Rex Runner 的 Mgain = 60.3，意思是后 3 局归一化均值比前 3 局高 60.3 个百分点。

**Learning slope（学习斜率）。** 直觉：gain 只看首尾两段，斜率看全部 10 局的趋势。做法是对 (e, ze) 做带截距的最小二乘直线拟合，取斜率。

普通最小二乘斜率公式：

$$
Mslope = 100 · [Σ(e=1..10)(e − ē)(ze − z̄)] / [Σ(e=1..10)(e − ē)²]
$$

其中 ē = 5.5（1 到 10 的平均），z̄ = (1/10)·Σ ze。

**一步步理解这个公式：**
1. (e − ē) 是第 e 局离中间局有多远。第 1 局是 −4.5，第 10 局是 +4.5，第 5、6 局是 −0.5、+0.5。
2. (ze − z̄) 是这局表现偏离整体均值多少。
3. 两者相乘：如果靠后的局表现高（正 × 正）或靠前的局表现低（负 × 负），乘积为正，说明上升趋势；反之下降。
4. 除以 Σ(e−ē)² 是把斜率归一化到"每局变化多少"，这个分母对固定的 1..10 是常数。
5. 乘 100 转成百分点每局。

论文还说明：因为每个 run 的局索引相同、拟合权重相同，"先每个 run 拟合再平均"和"先平均每个局的表现再拟合"结果一样。这是一个省事的计算性质。

**宏观平均（macro-average）**：对每个智能档，先在每个游戏内平均 3 次 run 的指标，再对 10 个游戏等权平均。这样每个游戏权重相同，不会被分数尺度大的游戏主导。

### 6.2 论文没有的数学：为什么没有可推导的理论保证

【论文明确声称】crafter 的能力估计和锚点比较都是 agent 用自然语言做的判断，没有形式化模型。论文没有给出"为什么这样改一定会提升 learning gain"的定理，也没有收敛性分析。这点在第 9 节会作为脆弱性讨论。

映射到图像融合（**推断**）：如果要把这个范式用到融合，你也不会得到一个闭式解。它本质是一个 search + feedback 的框架，靠评估指标引导，而不是靠优化目标的可微推导。这一点要和做融合的朋友说清楚：这不是一个新的融合 loss，是一个自动调融合系统的 meta 框架。

---

## 7. 实验设计与结果

### 7.1 提出什么问题 → 设计什么实验 → 答案是什么

我把论文实验按这个三段式整理，不堆表格细节。

**问题 Q1：PlayCraft 改出来的游戏，玩家表现是否真的随练习上升更多？**

- **设计**：10 款 Three.js 浏览器游戏（5 款 2D 复刻：Flappy Bird、T-Rex Runner、Breakout、Snake、Pac-Man；5 款 prompt 生成的 3D：Archery Hunting、Desert Racing、Robotic Arm、Drone Delivery、Space Shooter）。对比初始游戏 G0 与 3 轮修订后的最终游戏。fresh independent runs，3 档智能，每档 3 次 run，每次 10 局。用 learning gain 和 learning slope 衡量。
- **答案**：【论文明确声称】PlayCraft 在 3 档的 macro 平均 learning gain 都最大。相对初始游戏分别 +2.7（Low）、+14.0（Medium）、+21.9（High）个百分点；8/10、9/10、8/10 的游戏 gain 更高。learning slope 上 Medium +2.09（9/10 游戏更高）、High +2.64（7/10 更高）；Low 档 1.95 vs 初始 1.96，几乎持平，7/10 游戏更陡。

**问题 Q2：PlayCraft 是否比"只看代码"或"只看内部状态玩家"的改法更好？**

- **设计**：两个基线。`Code`：coding agent 只做代码分析，不用 player agent 证据。`Policy`：生成 10 个访问内部游戏状态的 policy controller 收集试玩证据，不跨尝试保留经验（改编自 Recursive Game Creator 的 generated-policy 思路）。两者用相同设计目标、proposal/implementation 流程、模型设置，都做 3 轮。
- **答案**：【论文明确声称】三档下 PlayCraft 两个指标的 macro 平均都高于两个基线。gain 上 Low +6.3 vs Code、+1.4 vs Policy；Medium +8.0 / +15.3；High +18.2 / +11.9。slope 上 Low +0.80 / +0.13；Medium +1.13 / +1.99；High +2.41 / +1.54。

**问题 Q3：智能档位如何影响结果？**

- **设计**：3 档配置（Table 1）：Low = GPT-6.1 Terra，action planning medium、episode review xhigh；Medium = GPT-6.1 Sol，medium / xhigh；High = GPT-6.1 Sol，xhigh / max。
- **答案**：【论文明确声称】gain 和 slope 通常随智能上升。从 Low 到 High，PlayCraft gain 升 20.5 个百分点（Code 8.7、Policy 10.0、初始 1.4），slope 升 2.78（Code 1.17、Policy 1.38、初始 0.14）。但 Medium→High 的提升（gain +2.8，slope +0.13）远小于 Low→Medium（gain +17.8，slope +2.66）。作者给出一个具体解释：PlayCraft 用 Medium 配置收集指导修订的 play record，High 玩家更容易应对 resulting challenges；前 3 局 High 的归一化表现均值 47.3%，Medium 是 38.2%，起点更高导致后期改进空间更小。

**问题 Q4：迭代过程中指标怎么变化？有没有反例？**

- **设计**：Figure 3 追踪 0/1/2/3 轮的 gain 和 slope。
- **答案**：【论文明确声称】两个指标一般随轮次上升，有波动。最终 9/10 游戏两个指标都超过初始值。最明显反例是 Robotic Arm：第 1 轮后两个指标都大幅下降，第 2 轮部分恢复。作者解释：第 1 轮加入"负载下腕部晃动"和"罐子起始位置变化"，使转移更难稳定执行。

**问题 Q5：为什么 PlayCraft 的证据优于基线证据？**

- **设计**：`§4.4` 定性分析 4 个游戏（Breakout、Archery Hunting、Robotic Arm、Drone Delivery），比较三种方法拿到的证据如何塑造设计选择。
- **答案**：【论文明确声称】Code 用代码/间隙分析，Policy 用控制器轨迹，PlayCraft 用与真人同界面、跨局学习、能报告策略和困难的 agent 经验。举 Archery Hunting 的细节：PlayCraft 第 1 轮加入掩体与目标因噪音撤退，安静命中金色弱点不会惊动附近目标；第 2 轮允许把目标从一个掩体赶到另一个，暴露时间延长到 4 秒；第 3 轮把接近逃生口的路径移到掩体下，目标在岔口按最近探测到的扰动选逃生路线，安静命中可让下一个目标保持路线，故意制造扰动可把目标引到可拦截的开口，普通命中现在给出箭相对金色弱点的落点反馈。玩家学会了放弃无望的追击、为更清晰的开口准备射击、用方向反馈 refinement。

**问题 Q6：这个范式依赖什么假设？有没有证伪检查？**

- **设计**：论文没有做真人对照实验，只在 `§5 Conclusion` 的 Limitations 里声明假设。
- **答案**：【论文明确声称】假设 agent 的玩法和学习模式类似真人。论文明确说这个假设"remains unverified"，未来工作要把 agent 玩法与人类行为对齐，并比较决策、困难、学习模式来验证。第二个限制是长 run 的成本：增加活跃预算会增加游戏时间和模型推理，更高效的观察和动作规划才能让更长 run 实用。

---

## 8. Take aways

1. **把"学习轨迹"当设计证据，而不是只看胜负。** 这是论文最实的一点。一个 agent 的第 1 局和第 10 局之间的差，比单一胜负分包含更多可用于改进的信息。
2. **两阶段分工 + 报告作为接口是有效的解耦。** 玩家只管玩和说，工匠只管读和改。玩家不需要代码能力，工匠不需要重玩。这个结构让两边可以用不同 reasoning effort（action planning medium、episode review xhigh、design xhigh、implementation max）。
3. **视觉界面不是装饰，是证据质量的保证。** 只能看帧、只能用和人一样的控制，才让 agent 的困难有可能对应人的困难。Policy 基线用内部状态，效果更差，是这个判断的间接证据。
4. **推理时间不计入游戏时间是关键的工程细节。** 没有这个设计，慢模型会把 60 秒预算耗在思考上，实验根本没法做。类比到图像融合：工具调用的 wall-clock 成本要和"融合质量预算"分开算。
5. **锚点设计必须防作弊。** 论文要求新手/中级的结果来自"没有时间限制也仍然有利"的策略，这是防止 crafter 靠改时间限制刷指标的护栏。
6. **结果不是全胜，反例有信息量。** Robotic Arm 上 PlayCraft 输给基线且低于初始游戏，原因是第一次修订加入了破坏可重复执行的扰动。这说明"增加挑战"和"破坏学习曲线"之间只差一步。
7. **映射到你关心的方向时要诚实：论文没有做图像融合。** 可迁移的是"视觉 agent 闭环 + 报告驱动诊断 + 锚点目标 + fresh run 验证"这套范式，不是任何具体的融合算子或融合指标。

---

## 9. 这篇论文最脆弱的假设是什么？

最脆弱的假设是：**agent 的学习与困难模式能代表真人**。

论文自己在 Limitations 里承认它未经验证，但它的破坏力比"第二限制（成本）"大得多，因为整个方法的价值主张都建立在这上面：

- 如果 agent 的"困难"是 LLM 特有的（比如对像素级快速反应不擅长，而对语义规划很擅长），那么 crafter 会针对 agent 的弱点改游戏，结果可能对真人无效甚至有害。
- 论文用 3 档智能配置部分缓解了这个风险（观察 gain 随智能上升），但这只是同一类 agent 内部的变化，不是跨物种（agent vs human）验证。
- 具体可疑点：Low 档用 GPT-6.1 Terra，High 用 Sol + 更高 reasoning。这些模型共享训练数据和架构先验，它们的"学习模式"可能高度相关。三个档位未必提供三个独立的样本。

第二个层面的脆弱性：**基线能力估计是 LLM 的自由文本判断**。crafter 要从报告里"估计玩家在玩之前的基线能力"，再"估计新手/中级/高手的表现"，再和锚点比。这一整条链没有可验证的中间量。如果估计偏了，后面所有设计都基于错误前提。论文没有给出这个估计的准确率或校准检查。

第三个层面（和图像融合迁移相关）：**归一化指标按每个游戏/方法的 90 个 outcome 的最大值归一化**。这意味着如果某个方法偶然产生一个极高的异常值，所有其他 outcome 都会被压低，learning gain 和 slope 都会受影响。论文没有报告异常值处理。

---

## 10. 一周能做的最小复现实验

**目标**：只验证最核心的一条 claim —— "视觉 agent 的 play record 比代码分析更能指导修订，从而产生更大的 learning gain"。不要试图复现全部 10 个游戏。

**做法**：

1. **选 1 款游戏**，建议 Breakout 或 Flappy Bird（规则简单、分数连续、论文里 PlayCraft 表现强）。用论文公开仓库 `https://github.com/xt4d/PlayCraft` 的初始游戏代码（如果有）或自己用 Three.js 写一个等价版本。
2. **固定评估协议**：O=200ms，W=1000ms，A=50，T=60s，E=10。至少 3 次独立 run。
3. **只做 1 轮 play–craft**，不做 3 轮。这样成本可控。
4. **对比两个条件**：
   - `Code` 条件：让 coding agent 只看代码改游戏（复现基线）。
   - `PlayCraft-lite` 条件：让一个视觉 agent 玩 10 局、写报告，再让 crafter 读报告改游戏。
   - 用同一个模型、同一套锚点（新手 10–30%、中级 50–70%）。
5. **测什么**：只测 learning gain（Mgain = 100·(后3局均值 − 前3局均值)），用同样的 max 归一化。记录每局分数。
6. **判定**：如果 PlayCraft-lite 的 Mgain 在 3 次 run 上稳定高于 Code，就算复现了核心 claim 的方向。如果相反或不稳定，你发现了一个有价值的边界条件。

**关键控制**：两个条件必须用**同一个初始游戏代码**、**同一个评估 agent 配置**、**同一个随机种子/初始状态序列**。否则差异可能来自噪声。

**可以顺手做的图像融合版最小实验**（如果你真想验证迁移假设）：选一个公开融合数据集（例如 MSRS 或 M3FD）的一个子集，把"退化类型/场景"当游戏，让一个视觉 agent 看输入图像和融合结果写报告（"哪里融合失败、可能原因"），再让一个 meta agent 根据报告调一个简单融合 baseline 的参数（比如不同区域的权重）。对比"只看指标调参"和"看报告调参"在 PSNR/SSIM 上的 gain。这属于**推断性验证**，论文本身没有这个实验。

---

## 11. 如果反对它，怎么设计反例

### 反例 A：agent 的困难与真人困难正交

**设计**：做一个游戏，它的挑战分成两类。A 类是语义规划挑战（LLM 擅长，例如"先收集钥匙再开门"），B 类是快速感知-动作挑战（LLM 不擅长，例如精确时机的小目标拦截）。初始游戏里 B 类占主导且设计良好。PlayCraft 的 agent 会因为 B 类困难而报告"太难"，crafter 于是削弱 B 类、加强 A 类。结果：agent 的 gain 上升，但真人玩家原本喜欢的 B 类挑战被破坏。测量：找一组真人玩初始版和修订版，看主观 engage 评分与继续玩的比例。如果真人评分下降而 agent gain 上升，就证伪了"agent 经验代表真人"这个假设。

### 反例 B：锚点本身诱导同质化

**设计**：人为把锚点设得极窄（比如新手必须 45–50%、中级 50–55%），看 crafter 是否会把所有游戏都改成相似的"平缓曲线"，牺牲了游戏的独特性和 high skill ceiling。测量：不同游戏修订后的机制多样性、专家玩家的上限分数。如果多样性塌缩，说明"按锚点改"会损害 games 的 identity，而论文只说"保留核心身份"但没有量化检查。

### 反例 C：归一化指标可被操纵

**设计**：构造一个修订，它只把某个边缘场景的分数推得极高（比如加一个可刷分的彩蛋），使 max 归一化分母变大，从而让其他所有 outcome 的归一化值都下降，但因为 early/late 的下降比例不同，Mgain 可能被人为抬高。测量：检查每局原始分数而不只是归一化值。这是对指标稳健性的攻击。

### 反例 D：报告可以"幻觉"出进步

**设计**：让 player agent 的记忆/lessons 被注入一段错误但合理的"经验"（例如"第 5 局发现某策略有效"，实际无效）。看 crafter 是否会据此改游戏。如果会，说明系统对报告真实性没有检验，整个链条建立在 self-report 的可信度上。论文没有交叉验证报告与真实轨迹。

### 反例 E（针对图像融合迁移）：退化标签错误级联

【推断】如果按第 5.6 节映射到图像融合，agent 的退化感知一旦误判（把运动模糊当离焦模糊），路由和提示都错，闭环会不断强化错误。设计一个包含混合退化的测试集，看 agent 报告里的退化分类与真实退化参数的吻合度。如果吻合度低，闭环反而放大误差。

---

## 12. 后续研究调研

我做了实际搜索（2026-11-22），如实报告结论。

### 12.1 直接后续：暂时没有

- arXiv API 查 `all:PlayCraft` 只返回本文 v1，提交于 2026-11-19。距搜索日仅 3 天。
- 查 `all:"designing engaging games"` 返回 2 条，另一条是无关的 THRIVE（康复游戏平台，[2608.14462](https://arxiv.org/abs/2608.14462)）。
- Semantic Scholar API 返回 429（限流），无法拿到引用列表。
- DuckDuckGo HTML 端点返回人机验证挑战，未能获取网页结果。

**结论**【基于证据的判断】：目前没有可检索到的、明确扩展或反驳 PlayCraft 的后续工作。任何"后续研究"的说法都必须标注为相关方向，而非本文的直接后继。

### 12.2 相关方向的新认知

我找到几篇与 PlayCraft 共享机制或挑战的工作，它们给出了间接的"认知更新"：

1. **CL-Bench**（[2606.05661](https://arxiv.org/abs/2606.05661)）：首个专家验证的 continual learning benchmark，覆盖软件工程、信号处理、疾病预测、战略游戏等。发现前沿 agent 经常过拟合即时观察、无法跨实例复用知识，而且**专用 memory 系统并不比朴素 ICL 好**。这对 PlayCraft 是个提醒：它依赖的"跨 episode 保留 lessons"机制未必真带来可靠学习；它的 gain 可能部分来自模型本身随 reasoning effort 的变化，而不是 lessons。

2. **MMG2Skill**（[2606.01993](https://arxiv.org/abs/2606.01993)）：闭环框架，把网页指南编译成可编辑技能，用轨迹级 root-cause feedback 修订技能，不使用 benchmark 分数。在 6 个 VLM backbone 上 macro 平均提升 12.8–25.3 个百分点；消融显示**原始指南直接提示会掉性能，结构化技能构建和轨迹驱动修订都必要**。这支持 PlayCraft 的"报告/lessons 作为接口"设计，但强调需要结构化表示，而不是自由文本。

3. **PTCG-Bench**（[2605.29653](https://arxiv.org/abs/2605.29653)）：用宝可梦卡牌游戏评估 LLM agent 的复杂决策与自我演化，发现**稳定自我演化仍然困难，且性能对 harness 设计敏感**。这提示 PlayCraft 的 3 档智能结果可能受 harness 影响较大。

4. **Agentic Knowledge Tracing**（[2606.25358](https://arxiv.org/abs/2606.25358)）：多 agent + BKT 从游戏事件估计 mastery，193 名 K-12 参与者上与学习增益 r=0.276。它用**结构化事件日志 + 形式化知识追踪**，与 PlayCraft 的自由文本报告形成对比。这暗示 PlayCraft 的一个自然改进方向是把自然语言报告补上结构化 mastery 状态。

5. **Simulator Collapse**（[2608.12253](https://arxiv.org/abs/2608.12253)）：形式化了"单一模拟器模式坍缩"问题，训练出的策略会利用模拟器的 mode 行为，迁移差。解法是 Verbalized Sampling 和 Co-Training，在真实用户上也有提升。这直接映射到 PlayCraft 的核心风险：**用单一 foundation model 当玩家 simulator，crafter 可能学到利用这个特定模型弱点的设计**。论文用 3 档配置部分缓解，但没有做 population 式的多 agent 采样。

6. **SWE-Growth**（[2611.23876](https://arxiv.org/abs/2611.23876)）：teacher-guided adaptive self-play，用验证过的 Teacher 结果识别学习机会，按 Student 能力动态选任务。这个"按学生当前能力动态生成任务"的思路，与 PlayCraft 的"按基线能力设计挑战"是同构的，但多了验证过的 teacher 信号。

**综合新认知**【合理推断】：PlayCraft 处在一个更大的趋势里 —— 用 agent 的经验闭环自动生成/调整任务与环境。这个趋势的共同瓶颈是：**经验的真实性与结构化程度**。自由文本报告好用但难验证；结构化日志可验证但信息稀疏。谁先把两者可靠地结合起来，谁就可能给出比 PlayCraft 更稳的方案。

---

## 13. 一个 novel 的 follow-up idea

### 名字：Calibrated Co-Evolution（校准式协同进化）

**从方法缺陷出发**：PlayCraft 把单一 foundation-model agent 的 self-report 当真人代理，且没有验证报告真实性。Simulator Collapse 告诉我们单一 simulator 会被利用；CL-Bench 告诉我们 memory 机制未必真有效；Agentic Knowledge Tracing 告诉我们结构化 mastery 信号可以用。三个缺陷指向同一个空缺：**缺一个独立于自报告的、可校准的能力模型，以及一个防止 crafter 过拟合特定 player agent 的机制**。

### 核心思路

不是再做一个"更好的 player agent"，而是把玩家侧改成**一个带真人校准锚点的 agent 群体**，把 crafter 的优化目标从"最大化 agent gain"改成"最大化在保留真人校准约束下的跨群体 gain"。

具体三层：

**第一层：结构化能力状态 + 校准。**
- player agent 每局除了自然语言报告，还输出一个结构化状态向量：感知准确率、执行精度、策略发现进度（对应论文 `§3.2.3` 已经提到的 baseline abilities 三类，但论文只让 agent 用文本估计，没有显式化）。
- 用一小批真人试玩数据（比如每款游戏 5 人 × 10 局）校准这个状态到真人 mastery 的映射。校准不要求大样本，只要求锚定三个点，对应论文的 beginner/intermediate/expert 锚点。
- 这样把论文"未经验证的假设"变成一个可测量的校准误差。

**第二层：多玩家群体 + 反利用约束。**
- 不用单一 player agent，用 N 个异质 player（不同 backbone、不同 reasoning effort、不同 memory 机制）产生 play records。
- crafter 的目标函数不再是单个 agent 的 gain，而是群体 gain 的**下分位数**（例如 worst-20% agent 的 gain）。这直接防止它设计出只适合某个模型弱点的游戏，对应 Simulator Collapse 的解法思路。
- 加一个"策略多样性"约束：修订后游戏里，群体发现的策略集合不能比修订前显著变窄。

**第三层：报告真实性交叉验证。**
- 把每局的 self-report 与该局的**可验证轨迹事实**对照：报告说"我发现了策略 X"是否伴随着对应行为的出现？报告说"困惑于机制 Y"是否在后续局中表现为相关错误下降？
- 不一致的报告被降权或标记，不让 crafter 直接吃幻觉。这对应我第 11 节的反例 D。

### 为什么这是 novel 而不是增量

- 它改变的是**证据的可信度模型**，不是换一个更大的 LLM 或多做几轮迭代。
- 它把论文明确承认的未验证假设（agent ≈ human）变成系统的一个可优化、可测量的组成部分。
- 它引入了一个论文完全没有的优化目标：跨异质玩家群体的鲁棒 gain（下分位数 + 多样性约束），而不是单一配置的平均 gain。

### 可验证的预测

如果 idea 成立，应该观察到：
1. 在校准真人数据上，Calibrated Co-Evolution 修订的游戏比 PlayCraft 修订的游戏有更高的真人 learning gain；
2. 跨 backbone 迁移时性能下降更小；
3. self-report 与轨迹事实的一致性率上升，且 crafter 的设计对不一致报告不敏感。

### 映射到图像融合的版本【推断】

同样的三层可以直接搬：
- 结构化能力状态 → 每张图的退化向量（噪声/模糊/低光/错位的量化估计）+ 校准用的小标注集；
- 多玩家群体 → 多种融合 backbone 或多种退化条件的 agent，优化最差情况的融合质量而不是平均；
- 报告真实性 → agent 说的"这块融合失败"必须由局部质量图或下游任务表现验证。
这样得到的融合系统不会"只对某类图像好"，而且它的每一步决策都可追溯。这正好回应了用户要求的"动态算子调度 / 退化感知路由 / 自适应提示生成 + 端到端闭环反馈"，但我要再次强调：**这是基于 PlayCraft 范式的推断性设计，不是论文内容**。

---

```yaml
# PAPERFLOW_METRICS_JSON
task: "Automatic game revision for mastery (play–craft loop); indirectly maps to agent-driven image-fusion orchestration"
backbone:
  player_agent_action_planning: "GPT-6.1 Sol (medium reasoning); Low setting uses GPT-6.1 Terra"
  player_agent_episode_review: "GPT-6.1 Sol (xhigh reasoning); High setting max"
  crafter_design: "GPT-6.1 Sol (xhigh reasoning)"
  crafter_implementation: "GPT-6.1 Sol (max reasoning)"
  codebase_agent: "Codex 0.162.1"
  framework: "PlayCraft (visual playing + diagnosis/proposal/implementation)"
datasets:
  games: 10
  two_d_recreations: ["Flappy Bird", "T-Rex Runner", "Breakout", "Snake", "Pac-Man"]
  three_d_prompt_generated: ["Archery Hunting", "Desert Racing", "Robotic Arm", "Drone Delivery", "Space Shooter"]
  evaluation_runs_per_game_per_setting: 3
  episodes_per_run: 10
  intelligence_settings: ["Low", "Medium", "High"]
  image_fusion_datasets: null
sota_summary:
  metric_definitions:
    learning_gain: "Mgain = 100*(mean of episodes 8-10 normalized - mean of episodes 1-3 normalized), percentage points"
    learning_slope: "Mslope = 100*OLS slope of normalized performance on episode index, percentage points per episode"
    normalization: "divide by max of 90 outcomes (3 settings x 3 runs x 10 episodes) per game and method"
  macro_average_learning_gain:
    Low: {Initial: 11.0, Code: 7.4, Policy: 12.3, PlayCraft: 13.7}
    Medium: {Initial: 17.5, Code: 23.5, Policy: 16.2, PlayCraft: 31.5}
    High: {Initial: 12.4, Code: 16.1, Policy: 22.3, PlayCraft: 34.3}
  macro_average_learning_slope:
    Low: {Initial: 1.96, Code: 1.15, Policy: 1.82, PlayCraft: 1.95}
    Medium: {Initial: 2.52, Code: 3.49, Policy: 2.62, PlayCraft: 4.61}
    High: {Initial: 2.10, Code: 2.32, Policy: 3.20, PlayCraft: 4.74}
  claims:
    - "PlayCraft has largest macro-average learning gain at all three intelligence settings"
    - "PlayCraft has largest macro-average learning slope at Medium and High; nearly tied with Initial at Low"
    - "Final revision exceeds initial values on both metrics in 9 of 10 games"
    - "Robotic Arm is the clear negative case: PlayCraft trails baselines and initial game on both metrics"
  image_fusion_sota: "not applicable: paper contains no image-fusion task or fusion metrics"
innovation_tags:
  - "vision-based foundation-model player with human-like interface"
  - "cross-episode memory and consolidated natural-language lessons"
  - "play-report as design evidence interface between player and crafter agents"
  - "proficiency-level performance anchors (beginner 10-30%, intermediate 50-70% of expert)"
  - "crafter diagnosis/proposal/implementation with archived-iteration history"
  - "mastery-oriented objective via learning gain and learning slope"
  - "fresh-run evaluation across three agent intelligence settings"
  - "transferable paradigm for agent-driven image fusion (inferred, not implemented)"

---

<!-- AI-GENERATED-NOTICE -->
!!! note "内容由 AI 生成，请审慎甄别"
    本站的论文解读、摘要速览与网站点评均由人工智能自动整理生成，仅用于学习与快速检索。
    AI 输出可能存在事实偏差、理解误差或信息滞后，涉及关键结论、数据与观点时，
    请以论文原文及官方来源为准，并自行判断其准确性。
