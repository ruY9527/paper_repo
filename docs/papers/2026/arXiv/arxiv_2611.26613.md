---
paper_uid: arxiv_2611.26613
title: "AgentRoboCritic: Understanding the Capability of Frontier Agents on Direct Robot Control"
venue: arXiv 2026
year: 2026
tier: preprint
tldr: "用'局部意图'把前沿多模态 Agent 的机器人控制轨迹从 episode 级评价拆到 action 级评价：策略每步输出数值动作和一句本地意图，critic 对照意图与前后多视角帧判定 Achieved/Failed/Partial/Unverifiable 和七类失败模式。结论是 GPT-6 Astra 这类 Agent 有闭环恢复、可靠语义 grounding 和强 zero-shot 操作能力；瓶颈集中在 GRASP/ALIGNMENT 等低层物理精度。释放 12,844 条标注动作、400 条人工测试集和微调后的 Muse-Glimmer-30B critic，把失败模式准确率从 32.58% 拉到 74.24%。"
tags:
  - agentic-robot-control
  - action-level-critique
  - intent-grounded-evaluation
  - failure-attribution
  - vision-language-action
  - multimodal-agent
  - closed-loop-recovery
  - zero-shot-manipulation
  - image-fusion-analogy
code_url: "https://github.com/cxcscmu/AgentRoboCritic"
paper_url: "https://arxiv.org/abs/2611.26613"
project_url: "https://adu2021.github.io/blog/AgentRoboCritic/"
dataset_url: "https://huggingface.co/collections/cx-cmu/agentrobocritic"
critic_model_url: "https://huggingface.co/cx-cmu/AgentRoboCritic-Muse-Glimmer-30B"

---

先说清楚一件事：这篇论文不是图像融合论文。它研究的是 frontier multimodal language agent 直接输出低层数值动作控制机器人，也就是把 GPT-6 Astra 这类模型当成 robot policy 用。用户给的"Agent+图像融合方向专属侧重"要求覆盖动态算子调度、退化感知路由、自适应提示生成、多模态工具链、端到端闭环反馈、融合质量提升来源。原文没有这些内容。我不会把这些写成论文主张。能做的是把它的真实机制形式化，再在明确标注为"迁移推断"的前提下，讨论它如何映射到图像融合的 Agent 化设计。凡是论文没说的，我都会写清楚来源层级。

信息标签约定：
- 原文声称：论文正文或项目页明确写出。
- 文献结论：引用工作或社区已建立的结论。
- 合理推断：基于论文证据和工程常识的推导，不等于论文结论。
- 不确定猜测：可能性设想，证据不足。

## 1. 论文提出并解决的研究问题是什么？为什么重要？带来哪些价值？

**原文声称**：论文要解决的问题不是"让机器人更强"，而是"怎么看清楚 frontier agent 在直接机器人控制里到底怎么成功、哪里失败"。现有 benchmark 只报 episode-level success rate：一个 episode 成功记 1，失败记 0，或者报 aggregate progress score。这种评价看不到单个动作层面的因果链。

问题的具体形式在 Introduction 里说得很直白：机器人操作是多峰的，同一个全局任务可以用很多条不同轨迹完成。只看目标 G，判断某一步动作 a_t 是否成功是 ill-posed 的。比如任务 "pick up the cup"，一步动作可能是 "lower to the cup"，也可能是 "close on the cup"，还可能是 "reopen and lower"。同一个物理位移，意图不同，判定就不同。论文 Figure 1(a) 用这个例子说明全局目标不足以评判单个动作。

这件事重要，因为 frontier agent 直接控制机器人已经跑出了很强的结果。原文称 GPT-6 Astra 这类模型不需要 high-level primitives，不需要 task-specific fine-tuning，就能在多个 manipulation benchmark 上超过专门的 VLA 和 WAM。可是如果评价粒度停留在 episode level，我们只知道"成了"或"没成"，不知道它靠什么成，也不知道失败集中在抓、对准、碰撞、任务效果还是选择错误。这样后面就无法做针对性改进。

论文带来的价值分成三层：

1. **评价方法价值**：AgentRoboCritic 让 policy 在每一次 tool call 里同时输出 low-level action a_t 和一句自然语言 local intent g_t。critic 输入是 (G, g_t, O_t)，输出动作结果 y_t、失败模式 m_t 和一段物理证据说明 e_t。这样每个动作都有一个可验证的局部契约。
2. **科学发现价值**：action-level 标注暴露出 episode-level 看不到的三点能力——闭环恢复、语义 grounding、zero-shot 操作；也暴露出物理执行瓶颈——GRASP、ALIGNMENT、INTERFERENCE 等，以及失败恢复不均衡。
3. **工程资产价值**：释放 12,844 条带 critic 标注的动作数据、400 条人工标注测试集，以及微调后的开源 critic Muse-Glimmer-30B。项目页给出了代码、数据集和模型链接。原文 Table 1 显示微调把 failure-mode accuracy 从 32.58% 提到 74.24%，推理成本降到 GPT-6 Astra 的 1/30 以下。

放到图像融合语境里看，**合理推断**：图像融合领域长期也有类似评价错位。PSNR、SSIM、MSE 这类全图指标把很多局部失败平均掉了；一个融合结果可能在纹理细节上很好、在小目标上丢失、在伪影集中区域崩坏，但总体分数只掉一点点。 AgentRoboCritic 的启发是把"融合算子动作"也配上局部意图和局部验证，例如"这一步要用 infrared 的细节补足 visible 的阴影区域，同时不能把 hot target 的边界抹掉"，再做区域级、步骤级的判定。这个映射是我基于论文方法的迁移推断，论文没有做图像融合实验。

## 2. 这个问题之前被解决了吗？之前的研究为什么存在不足？

**文献结论 + 原文声称**：相关工作有三条线，都碰到了这个问题的一部分，但没解决完整。

第一条线是 frontier agents as robot policies。语言模型接机器人有几种做法：planning over pretrained skills，代码生成调用 perception/control API，以及近年直接生成数值动作的 frontier multimodal agents。原文指出前两者把执行交给 skills 和 primitives，测到的是"模型 + 原语"的组合能力。GPT-6 Astra 这类 direct control 则把动作本身写成结构化文本，能反映模型自身的 embodied ability。

第二条线是 frontier agents 的评价。论文列出大量 benchmark：RoboDojo 42 个任务、RoboMME 记忆任务、RoboLab-120 pick-and-place、真实双臂桌面任务、UniVTAC/OpenViTac 视觉触觉任务、RoboColiseum 跨模型评测、GPT-GEAR 深度/触觉/几何约束探测、Embodied First Exam 开放 harness。这些工作推进了"能不能做"和"哪个模型更强"的回答。原文明确说它们都在 episode level，用 binary success rate 或 aggregate progress score，不告诉人们哪个动作坏掉。

第三条线是 robot failure detection and reasoning。REFLECT 总结机器人经验做解释与修正；AHA 用程序化扰动的示范训练 critic；RoboFAC 把失败数据、分析和纠正结合；ViFailback 研究真实 VLA 失败并给文本/视觉纠正指导；FailBench 评 VLM 判断任务成功的可靠性。原文说 AgentRoboCritic 的区别是关注 frontier-agent trajectories 里自然出现的失败，并把 action-level critique grounded in the agent's local intent。

之前的不足可以拆成四个具体点：

- **粒度不足**：episode-level label 没有动作定位能力。成功 episode 里可能藏着多次失败，失败 episode 也不知道失败从哪一步开始。
- **可验证性不足**：只看全局目标时，单动作成功与否依赖未声明的隐含子目标。论文消融显示，去掉 local intent 后 GPT-6 Astra 把大量动作标成 Unverifiable，outcome accuracy 从 79.25% 掉到 25.25%，failure-mode accuracy 从 80.68% 掉到 25.00%。
- **失败归因不足**：现有 critic 多是 task-success judge，或者针对扰动示范/特定失败数据训练。论文想要的是自然轨迹里每个失败动作的 physical cause，例如夹爪闭合时只碰到物体边缘、搬运中掉落、碰撞干扰、未完成的复位动作等。
- **成本与封闭性不足**：用最强 frontier model 当 critic 准确但贵。原文 Table 1 里 GPT-6 Astra 在 400 个动作上的推理成本是 26.06 美元；开源零样本模型 failure-mode accuracy 大多只有 32% 左右。需要一个可复用的开源 critic。

**迁移到图像融合的合理推断**：这个领域已有不少"融合质量评价"和"退化感知融合"工作，但多数是固定流程：融合网络训练好，全图指标评价；或者用退化估计模块指导网络。不足与论文里机器人情况相似：没有把"某一步为何选这个算子/参数/提示"作为可验证对象记录下来，所以事后不能判断是退化估计错、算子选错、参数错，还是评价区域错。**不确定猜测**：可能存在未检索到的 agentic fusion 工作做了类似 local intent 记录，但本次搜索没有找到可核验的直接对应论文。

## 3. 在正式讲方法前，先重建作者可能的思考路径

这一步只用论文之前的背景、失败模式、经验观察和相关工作，不拿论文贡献当前提。

作者面对的现实是：2025-2026 年出现了一批 frontier multimodal agents，它们在机器人控制上呈现出和 VLA/WAM 不同的行为。已有评测报告说它们 zero-shot 成功率很高，跨模型研究也开始跑统一 harness。实验室里如果亲自跑 rollout，会看到一个很奇怪的现象：有些 episode 最终成功，但中间明显失败过。比如夹爪第一次没抓到杯子，张开、重新下降、再抓，最后把任务做完。用 episode success rate 记，这只是一条成功；用人的观察记，这里包含一次失败和一次恢复。

接着作者会遇到第二个问题：想把 episode 拆成动作来评，但评不动。机器人操作天然多解。同一个"手向左移 3 毫米"的动作，如果意图是接近杯口，它可能成功；如果意图是插入孔位，它可能失败；如果意图只是测试稳定性，它也可能成功。这里和 VLA 评测常见做法不一样：VLA 的 benchmark 通常有明确的任务完成状态，但单动作没有。作者不可能回头给每个动作人工写 gold sub-goal，那样昂贵且不可扩展。

第三条线索来自 frontier agent 自己的接口。Direct control 下，agent 不是输出一个黑箱张量动作，而是通过 structured tool call 输出位移、关节角、夹爪开合等文本化命令。既然它本来就在生成结构化文本，那么要求它额外写一个 note 字段，说明"我这一步要干什么"，在工程上成本很低。这里的关键直觉是：agent 已经具备用自然语言表达中间目标的能力，而且这个表达可以和动作同一次生成，避免事后 retrofit 一个端到端 VLA 去解释自己的动作。

第四条线索来自 failure analysis 文献。REFLECT、AHA、RoboFAC 等工作说明 critic 可以有用，但它们多依赖总结、扰动示范或特定失败数据。作者面对的 frontier agent 失败是自然产生的，而且动作失败的原因有明确物理结构：夹爪没抓住、空间对准没到位、运动碰到别的东西、工具没有产生预期效果、动作没做完、目标选错。只要评的是"动作是否满足它自己的意图"，这些模式就可以在一个统一框架下分类。

把这些放在一起，作者的思路大概是这样：先承认 episode-level 不够；再承认全局目标下的 action-level 也不够；然后注意到 frontier agent 能低成本地为每个动作生成一句局部意图；于是把这句局部意图当成评价锚点；再用一个强 VLM 配合前后多视角帧当 critic；最后用人工标注验证 critic 是否可信，并把 critic 的标注能力蒸馏到开源模型里降低成本。这是一条从评价粒度问题出发、借助 agent 可解释接口、再用模型规模换标注质量的路线。

**迁移到图像融合的类似思考路径**（合理推断）：如果导师让我分析"Agent 在图像融合中到底有没有用"，我会先看到融合流程里很多决策点——选源图像、配准、退化估计、选融合算子、调权重、后处理、质量评价。现有论文多半只报最终 SSIM/PSNR，决策过程不透明。然后会发现这些决策如果事后只看最终目标"得到高质量融合图"，同样不可验证：某个局部锐化操作在边缘区域是好动作，在纹理平滑区域可能是伪影放大器。于是可以让 agent 在每次调用融合算子前写一句局部意图，例如"消除 visible 图中的运动模糊，但保留 infrared 目标的热对比"，再由 critic 对照区域前后状态判断。这一步是迁移推断，不是论文事实。

## 4. 方法的 Intuition 是什么？

核心 idea 一句话：**不要问"这个动作对全局任务有没有用"，要问"这个动作有没有做到它声称要做的那一步"。**

论文把机器人控制看成闭环序列。每个决策时刻 t，策略 π 从全局任务 G、当前动作前观测 O_pre_t、历史 h_t 中生成两样东西：数值动作 a_t 和局部意图 g_t。机器人执行 a_t 后得到动作后观测 O_post_t，必要时还有短时后续帧 O_aux_t。critic C 只看 G、g_t 和这一小段观测窗口 O_t，输出三件事：结果标签 ŷ_t、失败模式 m̂_t、诊断说明 ê_t。

这里的关键不是多写一句话，而是改变了评价的数学良定性。全局目标 G 约束的是整条轨迹，一条动作 a_t 可能对应无数种有效中间状态；局部意图 g_t 把这一步的成功条件压缩成一个局部契约。比如"把夹爪下降到杯子上缘并闭合，形成可保持的抓取"，这个契约就可以用闭合后的抬升帧验证：杯子有没有跟着夹爪起来。

第二个直觉是**接触感知的时间窗口**。不是所有动作都看同样长的视频片段。接近和对准动作只需要动作前后两帧；夹爪闭合动作必须看随后的 lift check，因为闭合瞬间看起来接触了，物体未必真的被抓住。论文在 critic protocol 里明确要求这种 observation window 与 g_t 的物理语义匹配。

第三个直觉是**局部有效性独立于 episode 结局**。一次早期抓失败即使后来恢复，也仍然标为 Failed；一个故意测试稳定性的小动作如果满足了 g_t，仍然标为 Achieved。这样标签才是动作级因果，不会被最终成败污染。

第四个直觉是**失败归因要有证据边界**。每个 Failed 动作必须落进七类之一，并写一句说明，点明哪只手臂、哪个目标物体、什么接触几何、什么时候出错。这能减少 critic 凭语言先验编原因。

**迁移到图像融合的核心直觉**（合理推断）：把每个融合操作也看成一个带局部意图的动作。一个"When to fuse / what to fuse / how to fuse"的决策不再是黑箱网络权重，而是 agent 写出的契约。critic 判断的是区域级物理证据，例如"红外小目标在融合后仍可见、可见光纹理没有被抹平、没有引入新的伪边缘"。这和论文的"局部契约 + 观测窗口 + 证据归因"同构。

## 5. 具体方法是什么？结合一个真实例子讲解：输入、处理、输出完整 pipeline

论文方法分三段：意图 grounding 的轨迹采集、意图 grounding 的 critic 与失败归因、人工验证 benchmark。下面按原文 Figure 2 的流程，用一个具体硬币任务串起来。

### 5.1 任务与策略端：每步动作都附一句 local intent

**原文声称**：全局任务是 "Pick up the coin from the holder and insert it precisely into the coin bank."。在某个决策时刻 t，frontier agent policy π 收到 G、动作前多视角观测 O_pre_t、交互历史 h_t。它输出一个 tool call，例如：

```text
move_eef(
  pose=[x, y, z, ...],
  gripper=close,
  note="I am lowering three millimetres and closing on its exposed upper portion."
)
```

这里 `pose`、`gripper` 是低层数值控制命令，`note` 是本地意图 g_t。执行 harness 强制要求 note 字段，缺少 local intent 的 tool call 会被自动拒绝，让 agent 重新发出合规命令。论文强调 frontier agent 本来就用 structured tool calls，所以这个扩展是自然的；对端到端 VLA 或 WAM 做同样的事并不简单。

### 5.2 执行端：记录动作边界和辅助帧

机器人执行 a_t 后，系统记录：
- O_pre_t：动作执行前的多视角相机观测。
- O_post_t：动作执行后的多视角相机观测。
- O_aux_t：可选的短时后续帧。原文例子中 gripper closure 后要跟一个 lift check，用来验证物体是否真被捕获并保持。

论文把这些合并成观测窗口 $O_t = (O_pre_t, O_post_t, O_aux_t)$。轨迹 τ = {(O_pre_t, a_t, g_t, O_post_t)}。注意公式里 τ 没把 O_aux_t 写进去，但 critic 输入 O_t 包含它。

### 5.3 critic 端：对照局部意图给判定

critic 用 GPT-6 Astra，输入三件东西：全局目标 G、本地意图 g_t、观测窗口 O_t。输出三元组 (ŷ_t, m̂_t, ê_t)。

结果标签 Y = {Achieved, Failed, Partial, Unverifiable}。论文说在完整动作上可化为二分类；Partial 用于有意的分段动作；Unverifiable 用于遮挡或录制截断。

失败模式 M 有七类：
- GRASP：物体没有被获取或保持，导致意图失败。
- ALIGNMENT：被抓物体或预期接触没有命中局部目标关系。
- INTERFERENCE：非预期碰撞、扰动或位移导致失败。
- EFFECT：工具在控制之下，但没产生声明的效果。
- INCOMPLETE MOTION：命令的运动、张开或复位没完成，且没有更具体模式。
- CHOICE：执行与 g_t 里声明的物体、顺序或类别相反。
- UNRESOLVED：动作失败，但证据不能确定模式。

回到硬币例子。critic 看到 g_t 是"下降三毫米并闭合在暴露的上部"，但 lift check 里硬币没有随夹爪抬起，输出：
- ŷ_t = Failed
- m̂_t = GRASP
- ê_t = "The upper-edge closure does not establish a retaining grasp of the coin."（上边缘闭合没有形成可保持的抓取）

这就是一个完整样本。数据集里的每条 annotated action 都包含原始 local intent、commanded action、给 critic 看的帧、outcome、failure mode、grasp sub-category 和 failure reason。

### 5.4 critic 的三条标注原则

**原文声称**：
1. **Contact-aware temporal windows**：评价窗口要匹配 g_t 的物理语义。reaching 和 alignment 看动作边界帧；gripper closing 要看闭合后的抬升帧。
2. **Decoupling local validity from episode outcomes**：动作只对其局部意图和可见状态转移负责。后来恢复不改变当前动作失败标签；诊断性小动作只要满足 g_t 就是 Achieved。
3. **Evidence-bounded failure attribution**：Failed 动作必须选一个模式，并写说明，具体指明 active arm、target object、contact geometry 和 failure timing。

### 5.5 人工验证与开源 critic 训练

论文构建 400 条人工标注动作，34% 成功、66% 失败。标注者在 web interface 上看到和 critic 相同的 (G, g_t, O_t)，独立标 outcome 和 failure mode。GPT-6 Astra 在这些标签上做验证，并和其他 proprietary/open-source critic 比较。

开源 critic 方面，原文称用 12,844 条标注动作微调 Muse-Glimmer-30B。项目页给出训练细节：LoRA rank 32，base weights frozen，2 epochs，batch size 32，max context 65,536，学习率 5×10^-5，25 warmup steps，cosine schedule；推理 temperature 0，最多 1,024 输出 token，非法 JSON 算错。目标是四字段 JSON：outcome、failure mode、grasp sub-category、short failure reason。

### 5.6 多模态工具链与闭环反馈：真实边界

**原文声称**：direct robot control 本身是闭环的，因为执行 a_t 后返回 O_post_t，agent 在下一turn 继续观察。tool call 里强制 note 字段，harness 拒绝无意图命令。

**原文没有声称**：论文没有做"按失败模式动态调度工具""退化感知路由""自适应提示生成"的控制器。critic 在论文里主要用于事后标注和分析，不是在线反馈给 policy 自我修正的模块。虽然第 4.3 节说 action-level critic 可以作为 online monitor 报告掉落，但这是讨论性表述，实验里没有把 critic 接回策略形成在线纠错闭环。

**迁移到图像融合的工具链设计**（合理推断）：如果把 AgentRoboCritic 映射成图像融合系统，可能的多模态工具链会是：
- 感知/诊断工具：退化估计、配准质量检查、区域显著性/目标检测、噪声/模糊/伪影分类。
- 决策工具：选择融合算子、选择源图像权重、选择对齐策略、生成局部提示。
- 执行工具：调用传统算法或深度融合模型，对区域或频带做操作。
- 验证工具：critc VLM 对照局部意图判断区域前后变化；无参考指标或有参考指标补充。
- 记忆工具：记录每一步局部意图、失败模式、证据帧，供后续 replay 和训练。

动态算子调度、退化感知路由、自适应提示生成可以对应到论文的 (G, g_t, O_t) → (y_t, m_t, e_t)：G 是用户融合目标，O_t 是退化诊断和中间融合结果，g_t 是这一步为什么选算子/参数，critic 输出的是区域级成功/失败与原因。这个对应是我提出的迁移设计，不是论文实验结论。

## 6. 核心数学推导过程

这篇论文没有提出新的优化目标或理论定理。它有几个简单但关键的建模公式，值得一步步拆开。

### 6.1 直接机器人控制的策略公式

论文 Equation (1)：

$$
a_t ~ π(· | G, O_pre_t, h_t)
$$

含义：在第 t 个决策 turn，策略 π 根据全局任务指令 G、当前动作前观测 O_pre_t、交互历史 h_t，采样一个低层控制命令 a_t。a_t 可以是 6-DoF end-effector pose、joint configuration、gripper opening 或 primitive motion trajectory。

和普通 VLA 的差别在表达形式：frontier agent 把这些数值动作写成 structured text，通过语言生成接口输出，不需要额外 action head 或连续 policy decoder。

### 6.2 加局部意图后的策略与轨迹

论文 Equation (2)：

$$
(a_t, g_t) ~ π(· | G, O_pre_t, h_t)
$$

$$
τ = {(O_pre_t, a_t, g_t, O_post_t)}_{t=1}^T
$$

这一步只是在输出里多了一个 g_t。g_t 是自然语言 local intent，说明 a_t 的 immediate sub-goal。轨迹 τ 每一步记录动作前观测、动作、意图、动作后观测。

从评价角度看，这个改动把"动作评价"从条件在 G 上变成条件在 g_t 上。形式上可以写成对比：

没有 g_t 时：判断 a_t 是否推进 G。问题是 P(success | a_t, G) 对中间路径不敏感，多个物理状态都可能算推进，评价不可判定。

有 g_t 时：判断 a_t 是否实现 g_t。g_t 是一个局部命题，例如"夹爪闭合后硬币被保持"，它能用 O_t 里的视觉证据直接验证。

这就是论文说的 well-posed。

### 6.3 critic 映射

论文 Equation (3)：

$$
(ŷ_t, m̂_t, ê_t) = C(G, g_t, O_t)
$$

其中 $O_t = (O_pre_t, O_post_t, O_aux_t)$。

ŷ_t ∈ Y，m̂_t ∈ M ∪ {∅}，成功时 m̂_t = ∅。ê_t 是诊断说明。

这个映射没有可微分训练目标；主实验里 C 是 GPT-6 Astra 通过 prompt 和 protocol 实现的。开源 critic 才用监督微调，把 C 蒸馏成 Muse-Glimmer-30B。

### 6.4 局部意图消融为什么有效：一个信息论式理解

论文没有写信息论证明，这里给一个直观版本，标为**合理推断**。

把 critic 的输入记为 X。去掉 g_t 后，输入是 X0 = (G, O_t)；加上 g_t 后，输入是 X1 = (G, g_t, O_t)。判定目标是 Y = 动作结果，M = 失败模式。

如果 O_t 中同一个视觉转移 ΔO 可以对应多个意图，那么：

P(Y | X0) 混合了多种可能契约。例如 ΔO 是"夹爪靠近某物并闭合"，可能是成功抓取，也可能是失败抓取，还可能是有意的稳定性测试。critic 没有观察到区分这些情况的变量 g_t，只能把它当隐变量。模型为了避免误判，倾向输出 Unverifiable。

加入 g_t 后，条件分布 P(Y | X1)  sharper：g_t 指定了当前动作应达到的物理关系，O_t 只需要验证该关系是否出现。论文消融数据支持这个直觉：无 g_t 时 outcome accuracy 25.25%、failure-mode accuracy 25.00%；有 g_t 时分别是 79.25% 和 80.68%。

### 6.5 恢复率与任务成功的相关性

原文 Figure 5(d) 报告：跨 12 个 benchmark，失败恢复率和含失败 episode 的官方成功率 Pearson r = 0.81，Spearman ρ = 0.86，项目页给出 p = 0.001。项目页还给出恢复判定细节：12,163 个带失败模式的失败动作中，6,435 个被直接修复，589 个通过不同路径绕过，5,139 个未恢复；10 个动作内恢复 4,734 个（38.9%），episode 结束前恢复 7,024 个（57.7%）。

这是相关性，不是因果证明。**原文声称** recovery 和 task success "closely associated"。**合理推断**：这个相关可能来自共同原因，比如任务越简单，失败越容易恢复，成功率也越高；也可能来自真实因果，即恢复能力提高成功率。论文设计没有区分这两种解释。

## 7. 论文如何设计实验验证方法和 claim？

按"提出什么问题 → 设计什么实验 → 答案是什么"来总结。

### 7.1 问题一：episode-level 评价是否掩盖了 agent 的真实行为？

**设计**：在 12 个 manipulation benchmark 上用 GPT-6 Astra 采集/摄入 rollouts，用 AgentRoboCritic 对动作逐条标注。benchmark 包括 RoboDojo、StationeryBench、Astranomy、UniVTAC、OpenViTac、ContactBench 1.0、LIBERO-MAX、Meta-World+、DexJoCo、RoboWits、RoboTwin 2.0、YAMLab。七个 benchmark 新采轨迹，并强制每步记录 local intent；五个使用已发布的 GPT-6 Astra traces，通过对齐适配器配对 intent notes 和前后帧。

**答案**：原文 Figure 5(a) 显示 49.8% 的成功 episode 至少含一个失败动作。也就是说，接近一半成功不是一路顺畅完成的。episode-level label 把这些恢复过程压成了一个 1。

### 7.2 问题二：frontier agents 能否从局部失败中闭环恢复？

**设计**：对每个失败动作，沿轨迹向后找第一个可验证恢复动作。恢复有两类：修复原子目标，或换路径绕过。项目页定义：漏抓后重新抓住并抬起算恢复；抓杯中球失败后改为抓杯并抬起以准备倾倒，算不同路径恢复；后续动作只完成自己的意图（例如漏抓后抬起空夹爪）不算。统计 10 个动作内恢复率和 episode 结束前恢复率，并算恢复率与含失败 episode 成功率的相关。

**答案**：10 个动作内恢复 38.9%，episode 结束恢复 57.7%。恢复率越高的 benchmark，含失败 episode 的官方成功率越高，r = 0.81。有 1-2 个失败的 episode 成功率 40.3%，无失败 episode 成功率 75.1%。这说明失败会显著压低成功率，但 agent 确实能修正不少失败。

### 7.3 问题三：frontier agents 的语义 grounding 是否可靠？

**设计**：用 CHOICE 失败模式衡量。定义是执行与 g_t 中声明的物体、顺序或类别相反。统计 CHOICE 在所有失败动作中的占比，并看单 benchmark 最高值。

**答案**：CHOICE 只占全部失败动作的 0.2%，任何单个 benchmark 最多 3.3%。原文据此声称 frontier agents 在有新物体实例和视觉干扰时，仍按意图中的物体、顺序、类别执行。注意这是失败动作中的占比，不是所有动作中的错误率。

### 7.4 问题四：zero-shot  direct control 是否优于专门 VLA/WAM？

**设计**：在同一 zero-shot 协议下比较 GPT-6 Astra、π0.5 和 InternW0-Δ，不做 task-specific fine-tuning。主要给 RoboTwin 2.0 和 YAMLab 的 head-to-head 成功率，并展示同初始状态的配对 rollout。

**答案**：GPT-6 Astra 在 RoboTwin 2.0 成功 91%，YAMLab 成功 90%；π0.5 分别 6% 和 0%；InternW0-Δ 都是 0%。项目页还补充了决策延迟：跨 74 个匹配任务，GPT-6 Astra 每次决策 33.3 ± 27.9 秒，π0.5 是 0.12 ± 0.02 秒。这个延迟代价论文没有隐藏，说明 zero-shot 成功不是免费午餐。

### 7.5 问题五：失败集中在哪些物理瓶颈？

**设计**：统计七类失败模式在各 benchmark 失败动作中的分布，并对 GRASP 做子类分析。

**答案**：GRASP 在十个非触觉 benchmark 中的九个是最频繁失败模式。视觉触觉 benchmark UniVTAC 和 OpenViTac 上主瓶颈转为 ALIGNMENT，分别占失败动作 75% 和 86%。杂乱或多阶段任务里 INTERFERENCE 上升。LIBERO-MAX 和 StationeryBench 有高比例 INCOMPLETE MOTION。GRASP 子类里，五分之三发生在夹爪闭合时，常见错误是只夹到边缘、在物体旁边闭合、在物体上方闭合；捕获后的 transfer/release 只占 1.5%；还有 9.5% 是夹爪已空但仍发出抬升或搬运命令。

### 7.6 问题六：不同失败模式的恢复是否均衡？

**设计**：按失败模式分层统计 episode 结束前的恢复率。

**答案**：INCOMPLETE MOTION 68.2%、GRASP 63.7%、INTERFERENCE 59.1%、ALIGNMENT 35.7%、EFFECT 29.6%。ALIGNMENT 和 EFFECT 在 30 个后续动作后提升不到 3 个百分点。结论是闭环恢复更擅长修物体获取和运动类错误，对精度受限和接触效果错误帮助有限。

### 7.7 问题七：critic 自己可信吗？

**设计**：400 条人工标注动作，34% 成功、66% 失败。所有 critic 得到相同 (G, g_t, O_t)。指标包括 outcome accuracy、Cohen's κ、failure-mode accuracy、overall accuracy（两者都对）、推理成本。

**答案**：GPT-6 Astra 最高：outcome 79.25%、failure mode 80.68%、overall 71.25%。去掉 local intent 后崩到 25.25%、25.00%、24.50%。Claude Fable 5.2 接近：78.25%、72.73%、71.00%。开源零样本模型多在 52%-62% outcome 和 32%-43% failure mode。微调后的 Muse-Glimmer-30B 达到 76.25%、74.24%、67.75%，成本 0.79 美元。

项目页还做 self-preference bias 检查：GPT-6 Astra 同时当 policy 和主 critic，可能偏向把自家失败标成功。在 264 个人工判失败的动作中，它只把 19 个标成 Achieved，是最少的；Claude Fable 5.2 是 75 个。微调 Muse-Glimmer-30B 后，把失败标成功的数量从 67 降到 34。

### 7.8 关于"融合质量提升来源"的诚实结论

**原文没有图像融合实验，也没有融合质量指标。** 论文中的"质量提升"只有 critic 的标注质量提升：GPT-6 Astra 作为标注器，把失败模式 accuracy 从开源模型的约 32% 提升到 80.68%；通过数据蒸馏，把 Muse-Glimmer-30B 从 32.58% 提到 74.24%。这不是图像融合质量提升。

**迁移到图像融合的合理推断**：如果把这套 critic 用到融合任务，质量提升可能来自三处，但需要新实验证明：一是局部意图减少评价歧义；二是失败模式分类把"哪里坏"定位到退化估计、配准、算子选择或后处理；三是 critic 信号反馈给算子调度器，减少无效重试。论文只证明了第一处在机器人动作评价里成立，后两处属于迁移假设。

## 8. Take aways

1. **单动作评价必须有局部契约。** 只看全局任务 G，动作成功与否不可判定。g_t 不是装饰性解释，而是让 critic 有明确验证对象的必要条件。消融从 79.25% 掉到 25.25% 是最硬的证据。

2. **action-level 标签会改写我们对 episode-level 成功的解释。** 49.8% 的成功 episode 含至少一个失败动作。成功率相同的技术路线，可能有完全不同的自我纠错动态。

3. **frontier agent 的优势和短板都落在物理层之外/之内的边界上。** 它语义选择几乎不出错（CHOICE 0.2%），zero-shot 表现强；但 GRASP、ALIGNMENT 这类毫米级接触/定位问题仍是主要瓶颈。

4. **闭环恢复不是万能的。** 它能修运动获取类错误，对 ALIGNMENT 和 EFFECT 帮助有限。能力评价要按失败模式分层，不要只报一个 recovery rate。

5. **critic 是可蒸馏的。** 用 frontier model 生成标注，再微调开源 VLM，可以把昂贵标注能力迁移到低成本模型。这个结论对很多"LLM-as-judge"场景有工程价值，但要注意 teacher bias 和 annotator agreement。

6. **公开资产比单个指标更重要。** 12,844 条 annotated actions、400 条人工 benchmark、开源 critic，使后续研究能直接复现和扩展 action-level analysis。

7. **对图像融合的直接启示是方法同构，不是结论可搬运。** 可以把融合步骤写成带局部意图的动作，用区域级前后观测做判定，但必须重新定义动作单元、失败模式和质量证据，不能把 GRASP/ALIGNMENT 生硬套过去。

8. **延迟和成本是 frontier agent 控制的硬约束。** 33.3 秒一次决策对比 0.12 秒的 VLA，说明当前路线适合对 zero-shot 和泛化要求高、对实时性要求相对低的场景。

## 9. 这篇论文最脆弱的假设是什么？

最脆弱的假设是：**策略自己生成的 local intent g_t 是一个可靠、可验证的评价契约。**

这个假设贯穿整个方法。critic 输入依赖 g_t，失败模式定义依赖 g_t，恢复判定依赖 g_t，最终所有能力和瓶颈结论也依赖 g_t。问题在于 g_t 由同一个 policy 生成，可能趋同、模糊、事后合理化，甚至错误描述动作真实目标。如果 g_t 写成"close on the coin"而实际动作偏移，critic 判 GRASP；如果 g_t 写成"test stability"，同一个偏移可能判 Achieved。论文通过执行 harness 强制 note 存在，但没有证明 note 的语义忠实于策略内部目标。

这个脆弱性有几个具体表现：

- **自述偏差**：policy 可能倾向写容易完成的意图，让 critic 更容易给 Achieved。论文检查了 GPT-6 Astra 当 critic 时是否偏袒自家 policy，发现它反而最严格；但这个检查只针对 critic 偏向，没有检查 policy 写 intent 的策略性偏差。
- **粒度依赖**：动作单元在不同 benchmark 定义不同。RoboDojo 是一次 executed call，StationeryBench 是一次物理 move_to，Astranomy 是一次 native action chunk，UniVTAC/OpenViTac 是一组 primitives。g_t 的语义宽窄因此不一致，跨 benchmark 统计可能混入粒度差异。
- **证据可见性限制**：UNRESOLVED 和一些 GRASP 子类在部分 benchmark 占比很高，说明多视角帧未必足够。如果关键接触被遮挡，critic 的归因就是有限证据下的猜测。
- **循环论证风险**：用 GPT-6 Astra 生成轨迹和 intent，再用 GPT-6 Astra 当 critic 标注，再用人工小样本验证 critic。人工集只有 400 条，并且论文说 annotators 在复核分歧时接受了 critic 的大部分 critique。这个流程合理，但无法排除共同模型偏差在某些细分类别上仍然存在。

第二脆弱的假设是：**视觉帧足以归因物理失败。** 对 GRASP、ALIGNMENT 这类接触问题，视觉只能看到外部表现。原文自己承认 visuo-tactile benchmark 在 vision-only 设置下 ALIGNMENT 暴增，说明触觉信息缺失会改变失败结构。批评者可以说，某些 ALIGNMENT 失败其实来自触觉闭环缺失，而不是 agent 空间推理能力不足。

**迁移到图像融合的脆弱假设**（合理推断）：如果把 local intent 搬过去，最脆弱点会变成"局部意图是否真的对应一个可验证的区域目标"。融合任务里的"保留纹理""增强目标"经常没有唯一真值，多个相互冲突的局部目标都可能算合理。这样 critic 容易变成审美裁判，而不是物理证据裁判。

## 10. 如果我有 1 周时间，能做一个最小复现实验验证它的哪一点？

建议复现**最关键、成本最低、结论最硬的消融：local intent 是否让 action-level critique 从不可判定变成可判定。**

不要一开始复现 12 个 benchmark 和 GPT-6 Astra 直接控制。那需要机器人仿真/真机、工具链和大量 API 预算。最小实验可以用论文公开资源做 critic-side replication。

### 实验设计

**目标**：验证同一 critic 在有无 g_t 两种输入下，对人工标注动作的结果判定和失败模式判定是否显著下降。

**资源**：
- 从项目页/Hugging Face 下载 400 条 human-annotated benchmark。
- 调用一个可复现的开源 critic，优先用发布的 Muse-Glimmer-30B critic；如果算力不够，用任意强多模态模型做 prompt 版 critic，并明确这不是原模型复现。
- 按论文 Table 1 计算 outcome accuracy、failure-mode accuracy、overall accuracy，以及 Unverifiable 比例。

**步骤**：
1. 输入 A：给 critic (G, g_t, O_t)，按论文协议让它输出 JSON：outcome、failure mode、grasp sub-category、reason。
2. 输入 B：隐藏 g_t，只给 (G, O_t)，同样输出。
3. 对照人工标签计算指标。
4. 额外统计输入 B 中 Unverifiable 的比例，看是否像论文所说那样大量出现。
5. 抽样 20 个 B 判错的动作，检查是否属于"同一视觉转移在不同 g_t 下应有不同判定"的案例。

**预期**：如果论文核心成立，A 的 outcome accuracy 应明显高于 B，failure-mode accuracy 差距更大，B 的 Unverifiable 比例显著上升。论文参考数字是 A：79.25/80.68；B：25.25/25.00，但用自己的模型时不要期待数值相同。

**判定标准**：只要看到 B 大量 collapse 到 Unverifiable 或随机模式，而 A 能稳定给出与人工一致的归因，就验证了 g_t 是评价良定性的关键变量。

### 如果还想做图像融合版最小实验

**目标**：验证"融合步骤的局部意图"是否能减少评价歧义。

**步骤**：
1. 选 50 组图像融合样例，包含红外/可见、多曝光或模糊/清晰组合。
2. 预先定义三类融合动作：detail-transfer、contrast-preserve、artifact-suppress。
3. 每个动作让一个 agent 写 local intent，例如"把红外目标边界转移到可见图，同时保持背景纹理"。
4. 请人类标注者只看最终图和局部意图，判断该局部目标是否达成。
5. 对比两种评价输入：只看全局目标"得到高质量融合图"；看全局目标 + 局部意图。
6. 测标注一致率（Cohen's κ）和 Unverifiable 比例。

**预期**（合理推断）：加局部意图后标注一致性会上升。但这只是对论文机制的迁移验证，不是证明 Agent 提高了融合质量。

## 11. 如果我反对它，我会怎么设计反例？

我会从三个方向打：评价契约的可靠性、统计归因的有效性、成本/能力的外部有效性。

### 反例一：策略可以写"投机局部意图"

构造一个 policy π_bad，它在动作后 According to 结果写 g_t，也就是把 intent 当事后解释使用。论文协议要求 g_t 和 a_t 同一次 tool call 生成，但没有机制阻止模型在学习/提示层面形成一种自我服务式叙述。π_bad 每次都写非常低门槛的意图，例如"稍微移动夹爪以收集观察"，于是大量实际失败动作会被重写成 Achieved。

如果 critic 对这些 g_t 给出高 Achieved 率，就说明框架的标签依赖 policy 的诚实性，而不是客观物理契约。严格说，论文评测的是"动作是否满足给定意图"，不是"意图本身是否合理"。一个动作可以满足一个坏意图。

### 反例二：同一个动作、同一个意图，但证据窗口不同导致标签翻转

找 50 个夹爪闭合动作，分别只用 O_pre/O_post 和评价加 O_aux lift check。预测只用边界帧时 critic 会过多标 Achieved，因为闭合瞬间看似接触成功；加 lift check 后才暴露物体没被保持。

这个反例不一定推翻论文，反而支持它的 contact-aware windows 原则。但它能削弱"局部意图本身足够"的说法：真正关键的可能不是 g_t，而是长一点的物理证据窗口。论文 Table 1 的消融只去掉 g_t，没有单独消融 O_aux。一个更干净的 2×2 设计应该是：有/无 g_t × 有/无 O_aux。

### 反例三：CHOICE 低不等于语义 grounding 强

CHOICE 的定义是执行与 g_t 中声明的物体、顺序或类别相反。如果 policy 很少生成需要复杂选择的 g_t，CHOICE 自然低。比如在任务里它只写"approach the red block"，而场景里只有一个红 block，那么这个动作几乎不可能 CHOICE。

要反驳"可靠语义 grounding"这个 claim，可以设计一个挑战集：局部意图里指定一个属性组合，场景中存在多个同类物体、视觉干扰、镜像视角和顺序约束；同时统计 g_t 的语义难度。如果 CHOICE 随干扰强度显著上升，就说明原结论的 0.2% 只是 benchmark 分布结果，不是稳健能力。

### 反例四：恢复率相关来自任务难度混杂

r = 0.81 的横截面相关不能证明恢复导致成功。可以设计分层分析：在 task family 内按初始状态难度配对，比较高恢复和低恢复 agent 的成功率；或者直接做干预实验，强制禁止 recovery 动作，看成功率掉多少。如果控制任务难度后相关消失，原文"failure recovery is closely associated with task success"的行动含义会变弱。

### 反例五：图像融合迁移中会退化为语言审美评价

如果把 critic 直接搬到图像融合，要求它判断"是否保留细节""是否抑制伪影"，不同人类专家可能没有一致答案。此时 critic 的高"准确率"可能只是和某个 VLM 的审美偏好一致，而不是和质量指标一致。反例设计：让同一个局部意图在多个融合算法输出上判断，看 critic 排名是否和 no-reference IQA/人类偏好一致。若不一致，说明迁移需要重新定义可验证证据，不能照搬机器人物理契约。

## 12. 调用搜索工具调研后续研究：扩展、反驳与新认知

我调用了 arXiv、项目页、Bing 和 Semantic Scholar API 做检索。结果如下。

**原文与项目页**：论文于 2026-11-19 提交，28 页，项目页提供代码、数据集和 critic 模型。项目页比正文多了若干细节：决策延迟表、恢复判定计数、self-preference bias 表、训练超参数、action unit 定义、失败模式/GRASP 子类完整表。

**后续引用检索**：Semantic Scholar 的该论文 citations 查询返回空数组 `data: []`。Bing 对 `"AgentRoboCritic" follow-up citation` 的检索没有找到可信后续论文，返回的是无关中文百科/游戏结果。因此，**当前可核验范围内没有发现后续扩展或反驳**。这可能是因为论文非常新，也可能因为检索索引滞后。这个结论要谨慎表述，不能说"领域没有后续"。

**相关前置工作网络**：Semantic Scholar references 显示它站在 2025-2026 一批 frontier robot policy 评测工作上，例如 "Frontier LLMs Enter the World of Robotics: A Cross-Model Evaluation on RoboColiseum"、"Large Multimodal Models for Direct Robot Control: GPT-6 as a Beginning"、"GPT-6 Astra Is a Native Visuo-Tactile Policy for Contact-Rich Manipulation"、"The Bitter Lesson Comes to Robotics"，以及 RoboDojo、RoboMME、LIBERO-MAX、World Action Models are Zero-shot Policies 等。失败分析相关前置包括 REFLECT、AHA、RoboFAC、FailBench。

**新认知一：这篇论文更像"评价基础设施论文"，不是"控制方法论文"。** 它没有提出新的 policy，也没有训练新的 controller。创新在于把 local intent 变成评价锚点，并把 critic 标注产品化。这个定位解释了为什么 release 数据集和 critic 是主要贡献。

**新认知二：作者自己提供了几条"反例证据"。** 项目页的 decision latency 表明 frontier agent 的 zero-shot 成功伴随两个数量级以上的延迟代价；vision-only visuo-tactile 设置下 ALIGNMENT 占比 75%/86% 表明缺失触觉会改变失败结构；self-preference bias 表表明 GPT-6 Astra 作为主 critic 存在潜在利益冲突，虽然实测它最严格。

**新认知三：Agent + 图像融合方向检索结果稀薄。** 对 `Agent in image fusion survey agentic image fusion` 和 `agentic workflow image fusion degradation-aware routing tool selection` 的搜索没有返回可核验的专门论文，结果多为泛泛的 Agent/Agentic AI 介绍。**不确定猜测**：agentic image fusion 可能还没形成稳定术语，相关论述散落在多模态工具调用、图像编辑 agent、自动化视觉管线和低层视觉 Controlled Generation 里。不能据此断定没有工作，只能说本次检索没有找到强证据。

## 13. Follow-up idea：从方法缺陷和需求出发的新方向

### 名字：FusionCritic with Counterfactual Local Contracts

这不是把 AgentRoboCritic 换个数据集做增量，而是把它的核心假设改掉。AgentRoboCritic 假设"policy 自述的局部意图是可信契约"。图像融合里这个假设更脆弱，因为"保留细节""突出目标""抑制伪影"常常没有唯一真值。我的 follow-up 核心是：**不要只让 agent 写一句局部意图，要让系统生成可反事实检验的局部契约。**

### 要解决的问题

在图像融合 Agent 中，一个决策可能是"用红外细节替换可见光阴影区的纹理"。事后看融合图，很难判断这一步是否正确。问题有三个：
1. 局部意图含糊，critic 可以任意解释。
2. 没有反事实对照，不知道这个算子是否比其他算子更好。
3. 多个区域目标相互冲突，一个区域增强可能带来另一个区域伪影。

### 方法草案

**1. Counterfactual Action Unit（反事实动作单元）**
每一步融合动作不只输出 (a_t, g_t)，还输出一组候选动作 A_t = {a_t^1, ..., a_t^k} 和对应预测后果。例如对某阴影区域，候选是：
- a^1：用红外高频细节增强可见光纹理；
- a^2：保持可见光亮度，只注入红外目标掩膜；
- a^3：做多尺度加权平均并抑制显著边缘差异。

**2. Evidence Contract（证据契约）**
g_t 改写成可证伪的条件：
- 目标区域 R_t；
- 要保留/增强的属性 p_t，例如小目标对比度、边缘连续性、纹理方差；
- 禁止出现的副作用 q_t，例如伪影边缘、热目标扩散、色彩漂移；
- 测量证据 e_t，例如局部梯度分布、显著目标 SNR、无参考质量图、人类偏好。

输出不是自由文本，而是结构化契约：$g_t = (R_t, p_t, q_t, e_t, threshold_t)$。

**3. Multi-Branch Replay Critic**
critic 不只看执行后的图，而是同时看候选动作在小范围试执行后的结果。它回答三个问题：
- 选中的动作是否满足自己的契约？
- 是否有候选动作以更少副作用满足同一契约？
- 是否出现了契约外副作用，即 q_t 被破坏？

这把 AgentRoboCritic 的二元局部判定变成带反事实的 regret 判定：不是"这步成没成"，而是"这步是不是在当时信息下最优或近似最优"。

**4. Region-to-Global Credit Assignment**
把每个局部契约的结果聚合到最终融合质量。训练一个 credit model，估计局部动作对最终指标的贡献。这样能回答"最终 PSNR 高，是因为算子选得好，还是因为区域重要性估计错但恰好抵消"。

### 为什么 novel

- AgentRoboCritic 的 local intent 是单条、自述、事后判定；这里是结构化、可证伪、带候选反事实的契约。
- 普通 image fusion agent 若只做动态算子选择，仍然没有可验证的局部评价；这里把 critic 放进选择回路，直接输出 regret 而不是绝对质量。
- 现有质量评价多为全图分数；这里用区域级契约和反事实对照做 credit assignment。

### 可验证实验

- 数据集：红外/可见、多曝光、多焦点、医学多模态融合；每个样本预定义区域属性标注。
- 指标：除了 SSIM/PSNR/FSIM/VIF，增加契约满足率、反事实 regret、副作用发生率、人类偏好一致率。
- 消融：无 g_t；有自由文本 g_t；有结构化契约；结构化契约 + 反事实候选；再加闭环重规划。
- 核心假设：结构化契约 + 反事实 critic 会比自由文本 local intent 更稳定地提升区域质量，并减少局部增强引起的全局伪影。

### 风险

最大风险是反事实执行成本高。可以先用轻量算子代理和区域裁剪降低计算，再逐步扩展到全图融合。另一个风险是契约属性本身难定义，尤其是感知质量类属性；因此需要人类标注校准，不能只靠 VLM 自评。

---

<!-- PAPERFLOW_METRICS_JSON
{
  "task": "action-level analysis and failure attribution of frontier multimodal agents under direct robot control; no image-fusion task in the paper",
  "backbone": {
    "policy_agent": "GPT-6 Astra (frontier multimodal language agent)",
    "primary_critic": "GPT-6 Astra",
    "baseline_critics": [
      "GPT-6.1 Sol",
      "GPT-6.1 Terra",
      "Claude Fable 5.2",
      "Claude Opus 5.5",
      "Claude Sonnet 5.5",
      "Kimi K3.1 Pro",
      "DeepSeek-V4.1-Flash-1017",
      "GLM-5.3-Flash",
      "Muse-Glimmer-30B zero-shot"
    ],
    "open_source_critic": "Muse-Glimmer-30B fine-tuned with LoRA rank 32",
    "vla_wam_baselines": ["pi0.5", "InternW0-Delta"]
  },
  "datasets": {
    "benchmark_count": 12,
    "benchmarks": [
      "RoboDojo",
      "StationeryBench",
      "Astranomy",
      "UniVTAC",
      "OpenViTac",
      "ContactBench 1.0",
      "LIBERO-MAX",
      "Meta-World+",
      "DexJoCo",
      "RoboWits",
      "RoboTwin 2.0",
      "YAMLab"
    ],
    "annotated_actions_released": 12844,
    "human_annotated_actions": 400,
    "human_test_failed_actions": 264,
    "failed_actions_analyzed_for_recovery": 12163,
    "main_dataset_annotated_actions_total_from_project_page": 12844,
    "critic_train_split_actions": 12844,
    "critic_validation_split_actions": 1548,
    "critic_test_split_actions": 1936
  },
  "sota_summary": {
    "gpt6_astra_zero_shot_success": {
      "RoboTwin 2.0": 91,
      "YAMLab": 90
    },
    "baseline_zero_shot_success": {
      "pi0.5": {"RoboTwin 2.0": 6, "YAMLab": 0},
      "InternW0-Delta": {"RoboTwin 2.0": 0, "YAMLab": 0}
    },
    "critic_human_benchmark": {
      "GPT-6 Astra": {"outcome_acc": 79.25, "failure_mode_acc": 80.68, "overall_acc": 71.25, "cost_usd": 26.06},
      "GPT-6 Astra w/o local intent": {"outcome_acc": 25.25, "failure_mode_acc": 25.00, "overall_acc": 24.50, "cost_usd": 25.18},
      "Claude Fable 5.2": {"outcome_acc": 78.25, "failure_mode_acc": 72.73, "overall_acc": 71.00, "cost_usd": 26.52},
      "Muse-Glimmer-30B zero-shot": {"outcome_acc": 52.50, "failure_mode_acc": 32.58, "overall_acc": 34.75, "cost_usd": 1.34},
      "Muse-Glimmer-30B fine-tuned": {"outcome_acc": 76.25, "failure_mode_acc": 74.24, "overall_acc": 67.75, "cost_usd": 0.79}
    },
    "recovery": {
      "successful_episodes_with_at_least_one_failure_pct": 49.8,
      "recovered_within_10_actions_pct": 38.9,
      "recovered_by_episode_end_pct": 57.7,
      "recovery_success_pearson_r": 0.81,
      "recovery_success_spearman_rho": 0.86
    },
    "failure_mode_share_among_failed_actions": {
      "GRASP": 54.4,
      "INTERFERENCE": 21.9,
      "ALIGNMENT": 15.4,
      "INCOMPLETE_MOTION": 5.7,
      "EFFECT": 2.4,
      "CHOICE": 0.2
    }
  },
  "innovation_tags": [
    "intent-grounded-action-level-critique",
    "local-intent-as-verifiable-contract",
    "contact-aware-observation-window",
    "seven-failure-mode-taxonomy",
    "closed-loop-recovery-analysis",
    "action-level-dataset-and-open-critic",
    "frontier-model-to-open-source-critic-distillation",
    "agentic-image-fusion-analogy-not-paper-claim"
  ]
}
-->

---

<!-- AI-GENERATED-NOTICE -->
!!! note "内容由 AI 生成，请审慎甄别"
    本站的论文解读、摘要速览与网站点评均由人工智能自动整理生成，仅用于学习与快速检索。
    AI 输出可能存在事实偏差、理解误差或信息滞后，涉及关键结论、数据与观点时，
    请以论文原文及官方来源为准，并自行判断其准确性。
