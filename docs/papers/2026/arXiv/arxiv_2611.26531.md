---
paper_uid: arxiv_2611.26531
title: "Cost-Aware Agentic Feature Optimization System for Fleet-Scale Ranking Models"
venue: "arXiv 2026"
year: 2026
tier: "arXiv preprint (cs.IR / cs.AI / cs.LG；论文未标注会议或期刊接收)"
tldr: "Meta 的生产广告排序系统把特征选择重写成有预算的黑箱优化：LLM 提假设，确定性工具算账、跑实验、验证结果；用一个跨模型持续微调的检索 LLM 造交叉特征，用 Pareto 混合做多任务筛选，用 LLM Researcher 在 10–25 次异步试验里再平衡各类特征数量，用 trimming 守住共享 pipeline 预算。生产模型 NE 平均降 0.31%，pipeline cost 降 2.3%，线上主指标 +0.20%。"
tags:
  - feature-selection
  - llm-agent
  - llm-as-optimizer
  - cost-aware-optimization
  - ads-ranking
  - pareto-optimality
  - pipeline-cost
  - feature-engineering
  - experiment-automation
  - multimodal-fusion-transfer
code_url: null
paper_url: "https://arxiv.org/abs/2611.26531"
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


## 1. 论文提出并解决的研究问题是什么？为什么重要？带来哪些价值？

先讲清楚场景。一个大型 Web 平台不会只跑一个排序模型，而是跑一支模型舰队：不同 surface、不同意图、不同任务各有一个模型。它们共享一个上万级别的特征池。每个特征在不同模型里的表现不一样，而且每个特征都要付费。付费分两笔，论文分得很清楚（【论文明确声称】）：

- **per-model serving cost**：QPS、延迟、内存。QPS 用每样本推理 FLOPs 做代理；延迟包括特征拉取和抽取，在某些 serving 阶段占 CPU 大头；内存主要由 sparse 特征的 embedding table 决定。
- **shared feature pipeline cost**：上游为生成、存储、记录一个特征付出的 processing、data、logging 成本。这笔钱由同一预算下的多个模型共同承担，一个特征只要被同预算下的另一个模型用过，它的边际 pipeline cost 就是零（论文的 attribution 规则）。

要解决的问题可以写成一句话：在每个模型有各自 serving 上限、整个舰队有共享 pipeline 预算的条件下，自动为每个模型挑出一组特征，使归一化熵（NE，越低越好）最小，同时不靠人工逐个模型调参。

为什么以前这是个难题？因为特征价值是集合依赖的，成本也是集合依赖的。论文明确说这些成本是 multi-dimensional、type-dependent、set-dependent rather than additive，所以按重要性分数取 top-N 到某个数量上限的做法在这些约束下是次优的（【论文明确声称】）。再加一层现实约束：一次训练评估要几小时到几天，一个 session 只跑得起 K≈10–25 次试验，最多 W≈4–8 个并发（【论文明确声称】）。这把问题从“跑个大搜索”变成“小样本、有预算的黑箱优化”。

价值有三层。工程上，系统每次模型 refresh 都重新选特征，不再继承 incumbent 的特征再手工增删（Section 5 的贡献 3）。研究上，它把 LLM agent 从“单模型 feature engineering”推到“舰队级、跨模型共享经验”的设置：一个检索 LLM 用多个模型的 FI 结果持续微调，优化的模型越多，特征生成越好（Section 2 的贡献 1）。业务上，论文报告了可落地的数字：七个高影响模型在各自预算内 NE 平均降 0.31%；六个模型上 trimming 把 attributed pipeline cost 平均降 2.3%（最多 6.3%）；线上 A/B 主指标 +0.20%（【论文明确声称】）。

信息标注约定：下文用【论文明确声称】表示原文直接给出的说法或数字；【文献已有结论】表示论文引用的已有工作或常识性背景；【基于证据的推断】表示我从论文证据出发做的合理外推；【猜测】表示没有证据支持的猜想。

## 2. 这个问题之前被解决了吗？之前的研究为什么存在不足？

相关工作按论文引用分成四条线，每条都解决了一部分，都卡在同一个地方：单模型。

**特征选择本身。** permutation importance、Shapley sampling、Kernel SHAP 这类重要性估计器是成熟工具（【文献已有结论】，论文引用 [1][7][8]）。它们能告诉你“打乱这个特征损失涨多少”“这个特征在随机 coalition 里的平均边际贡献是多少”。它们的问题是只给单特征的分数，不给“在 QPS  cap 下该拿多少 dense、多少 sparse、多少 embedding”这种组合决策。论文还点出 permutation importance 会低估相关特征（【论文明确声称】），这 motivating 了 Shapley 系估计器。

**自动交叉特征。** 交叉特征（user_country × ad_category 这类 n-gram）常被手工构造，穷举搜索对特征池是平方级；已有的 automated crossing 方法靠反复训练评估候选，无法扩展到生产规模（【论文明确声称】，引用 [9]）。候选数在 bigram 情形下是 |T| = O(|O||F|²)，能到几千万，确定性 FI 阶段在远小于这个数量时就 OOM（【论文明确声称】）。

**LLM 做特征选择与特征工程。** 论文引用 [5][6][14]，LLM 已被用来选特征、造特征。不足是它们把单个模型当作孤立对象，没有舰队视角，也没有建模跨模型共享的 pipeline 预算（【论文明确声称】）。

**LLM agent 跑 ML 实验。** 论文引用 [2][11]，LLM agent 已经能端到端跑机器学习实验。不足同样是 per-model isolation，而且常见做法是让 agent 自由改代码或改超参，缺少硬约束下的验证闭环（【基于证据的推断】：论文没有逐字这样评价 [2][11]，但它的系统设计明确把“agent 提假设 / 工具执行验证 / winner 规则不可被 LLM 覆盖”作为对立面）。

所以缺口很具体：缺一个把特征生成、重要性排序、多任务混合、有约束搜索、共享预算裁剪串成一条流水线，并且同时服务于整个模型舰队的系统。这个缺口就是本文的位置。

## 3. 在正式讲方法前，先重建作者可能的思考路径

下面只用论文之前的背景、失败模式和经验观察来推演，不拿论文自己的贡献当前提。

想象你是广告排序平台的工程师。你手上有一个上线模型，特征表是从上一版继承下来的。产品经理要你提指标。你打开特征池，看到几万个候选。第一反应大概是“加特征”。于是你加了 50 个 sparse 特征，训练一版，NE 没动，QPS 掉了，内存涨了。为什么？论文给出的经验解释是：不同特征类别有不同成本，也有不同边际收益曲线，提升模型通常意味着在类别之间重新分配 volume，而不是所有类别一起加（【论文明确声称】）。这就是第一个失败模式：**按数量堆叠，方向错了**。

第二个失败模式来自钱。你加到模型里的一个特征，上游要生成它、存源数据、记录训练值。这一笔不记在你这一个模型的账上，记在预算账上。如果同预算下另一个模型已经用了这个特征，你的加入不增加 attributed cost。反过来，你是第一个用的，你就把整个预算顶上去。人工做这个判断极其烦，因为成本是 table lookup、类型相关、集合相关的（【论文明确声称】）。这是第二个失败模式：**按重要性排序取 top-N，账算错了**。

第三个失败模式来自多任务。模型同时预测 click 和 conversion，两个 head 的 loss 量纲都不一样，一个是分类一个是回归。按任务权重加权求和挑特征，权重是手调的，主观，而且每次 refresh 都要重调（【论文明确声称】）。这是第三个失败模式：**跨任务分数不可直接相加**。

第四个失败模式来自实验预算。一次 trial 几小时到几天，你只跑得起 10–25 次。人肉盯 25 次试验，每次记一堆 NE、FLOPs、QPS 数字，再决定下一把怎么调，很容易前几把就收敛到一个局部想法上，后面十几把全浪费（【基于证据的推断】：论文 Fig. 2b 显示 new best 出现在 budget 后段，来自 exploration 和 evolutionary 家族，这支持“早期收敛会浪费预算”的判断）。这是第四个失败模式：**trial 太少，搜索策略必须省着用**。

现在把已有工具摆到桌上。LLM 能读文本信号并打分，能写假设，能保持一个长 session 的历史作为记忆。确定性工具能算 FI、能查成本表、能训练、能量 NE 和资源。有人已经证明 LLM agent 能跑端到端 ML 实验。你会怎么连？一个自然的做法是把 LLM 放在“提假设”的位置，把确定性工具放在“算账和验证”的位置，然后用一条硬规则选 winner。这样 LLM 的贡献被限制在搜索策略上，它犯的错会被 validator、cap、trimming 和固定 winner 规则挡住。这就是这条思路的 intuition 起点。

再往前一步：既然舰队里几十个模型都要做同一套动作，为什么每个模型单独配一个生成器？把跨模型的 FI 分数当成监督信号，训一个共享的检索 LLM，它的特征生成能力会随着优化的模型变多而变好。这一步从“单模型自动化”跳到“舰队级基础设施”（【基于证据的推断】：论文把它列为两个 fleet-level mechanisms 之一，但没有给出消融实验证明微调的贡献）。

## 4. 方法的 Intuition 是什么？

核心 idea 一句话：**把“给一个排序模型选特征”当成一个带硬预算的黑箱优化问题，让 LLM 只负责提出下一步试什么，让工具负责把这次尝试变成一组真实特征、算出代价、跑训练、验证约束，最后用一个 LLM 不能改写的规则宣布赢家。**

展开成三个直觉。

第一，搜索空间要小到 agent 能理解、大到能出惊喜。直接搜索“哪些特征进模型”是组合爆炸，agent 看不懂几万个 ID。论文把决策变量压成两个东西：每个特征类别取多少个（volume vector n），以及从 M 个排序来源里各取多少比例（mixture π）。特征本身由 blending 规则确定性生成。这样 LLM 每次只需要提出一个很紧凑的假设，比如“dense 从 1200 加到 1500，embedding 从 47 加到 90，sparse 减 14%”（【论文明确声称】）。

第二，质量信号和成本信号要分开处理。质量信号用多种 FI 估计器和 Pareto front 融合，不同任务不强行加总；成本信号用资源 cap 和 trimming 在训练前处理。两条线在 winner 规则处汇合：先筛掉违反资源 cap 的 trial，再在剩下的里面取 NE 最低者（【论文明确声称】）。

第三，跨模型共享要落在具体机制上，不落在口号上。两个机制：一个共享检索 LLM，用其他模型的 FI 分数做标签持续微调；一个 pipeline-cost attribution，判断某个特征在当前预算下是否已被别的模型用过，从而决定要不要 trim（【论文明确声称】）。

换到图像融合的语言：这套思路把“选哪些特征”换成“在哪个退化条件下调度哪个融合算子、用哪段提示词”，把 QPS cap 换成 FLOPs/延迟预算，把 pipeline cost 换成跨任务共享的预处理与检索成本。Agent 仍然是假设提出者，确定性工具仍然是退化估计、算子执行、质量度量和预算检查。

## 5. 具体方法是什么？结合一个真实例子讲解完整 pipeline

用一个论文里的真实配置走一遍：生产 per-event conversion 模型，基线 volume 是 1200/789/50/47（dense/sparse/transform/embedding），FLOPs cap 是 1.2×（【论文明确声称】）。

**步骤 1：建立候选池和信号库。** 模型输入分四类：dense（实数标量，进 MLP，每槽最便宜）、sparse（ID 列表，进 embedding table，主导内存）、embedding（上游产出的定长向量，无 table，但 logging/storage 贵）、transform（模型内从已有特征派生，例如 cross）。每个特征在 fleet-wide Signal database 里存静态信号：名字、lineage、聚合窗口、coverage、LLM 写的语义描述；也存模型相关信号：importance、interaction score（【论文明确声称】）。

**步骤 2：LLM 检索做召回。** 候选 transform 写成 t = (o, U)，o 来自算子集合 O（n-gram、ID matching、bucketization 等），U 是特征子集。LLM 单次 forward 给每个候选打分，保留 top N_r ≪ |T|。这是 recall 阶段，目的是把几千万候选压到 FI 阶段跑得动的规模（【论文明确声称】）。

**步骤 3：FI 排序做精排。** 在 shortlist 上训练一次包含全部候选的模型，然后用 permutation、Shapley value sampling、Kernel SHAP 打分，分数按任务归一化到和为 1。还有一个 segment-aware 变体：只在小但高价值的流量切片（例如高收入桶用户）上训练和打分，把全局重要性会埋掉的特征挖出来（【论文明确声称】）。

**步骤 4：多任务 Pareto 混合。** 每个特征 i 有重要度向量 $f_i = (f_i1, …, f_iJ)$。若对所有任务 j 有 f_ij ≥ f_i'j 且至少一个严格大于，就称 i 支配 i'。第一层无人支配的特征构成 P1，移走后重复得到 P2…PL，取到累计数量刚好超过 N 为止。这样做不需要任务权重，也保留“只在单一任务上强”的特征（【论文明确声称】）。接着把 M 个排序来源（incumbent 排名、各 FI 估计器全局或 segment 版本、按 PO 得到的多任务排名）按 mixture π 分摊 N 个名额，按固定顺序各取自己最高的、尚未被选的特征，直到贡献 round(π_m N) 个（【论文明确声称】）。

**步骤 5：形成配置 θ = (n, π)。** 特征集合 S(θ) = ⋃_{c∈C} Blend_{n_c}(F_c \ B; π)，B 是被禁用的特征（隐私、合规、覆盖率）。n 和 π 都从上一版模型初始化，然后当作超参数搜索（【论文明确声称】）。

**步骤 6：Researcher 提出假设。** Researcher 在 observe–reason–act 循环里运行（【论文明确声称】，引用 [13]）。它观察 trial history H、tuning guide G（每个类别的经验区间、优先级、每单位预期 ΔNE 和 FLOPs）、从 FI 排名算出的 facts、以及操作员的自由文本 steering。它产出一个假设：改 volume、改 π、或两者都改，附书面理由和一个行为家族标签，四选一：greedy、exploration、evolutionary（组合或变异先前 arm）、recipe（预定义结构化动作，例如“sparse 约 10× embedding 时，砍低排名 sparse，补高排名未用 embedding”）。上面那个真实案例里，赢的就是一个 recipe trial：embedding 翻倍，sparse 砍 14%，NE 相对基线降 0.17%；而所有只加 dense、sparse 或 transform 的初始 trial 都持平或更差（【论文明确声称】）。

**步骤 7：验证与裁剪。** validator 先拒绝重复、越界、参数范围外的提案，避免浪费预算。通过验证后，Trimming 在训练前执行：查成本表，找出破坏预算的新增特征，按最贵优先移除，再用同类里排名最高的“已经在用”的特征回填空位。这样每类特征数量不变，配置不变，FLOPs 基本不变（【论文明确声称】）。

**步骤 8：训练、测量、写入历史。** 每次 trial 用和 baseline/control 相同的数据窗口训练。慢循环每 δ_slow 量一次运行中 trial 的 NE 和资源，超过 cap 的早停，并更新 NE–resource Pareto frontier；快循环每 δ_fast 在有空位时立刻补一个新 trial。结果（NE、资源、假设、理由、家族）全部写回 H（【论文明确声称】）。

**步骤 9：选赢家。** 规则事先固定，LLM 不能覆盖：h★ = 满足全部 R_k(θ_h) ≤ ρ_k R_k(θ_0) 且 NE_h < NE(θ_0) 的 trial 中 NE 最低者；若不存在则返回 incumbent 配置（【论文明确声称】，Algorithm 1 lines 14–15）。

### 5.6 映射到 Agent + 图像融合：决策角色与工具链

论文本身是 tabular ranking，不含图像。下面是基于其机制的迁移设计，属于【基于证据的推断】，原文没有声称做过图像融合。

**动态算子调度。** 把 transform t = (o, U) 直接类比为融合算子：o 可以是多尺度注意力、cross-modal transformer、小波融合、diffusion prior 引导、分割掩膜引导融合；U 是要参与融合的模态或特征层。Agent 的决策变量从“每类取几个特征”变成“在给定退化条件下，调度哪些算子、作用在哪几个模态/层、以什么顺序”。这比固定 fusion network 更接近真实部署：不同输入需要的融合深度不同。

**退化感知路由。** 论文里有两个可以直接搬的结构。一个是 Signal database：除了特征名和语义描述，再存退化统计量，噪声方差、运动模糊核、遮挡比例、光照极端度、模态缺失标记、几何错位估计。另一个是 segment-aware FI：论文只在“高价值用户”切片上打分；图像融合里可以把“高价值切片”换成“严重退化切片”或“下游任务最脆弱的切片”。Agent 读这些信号，决定路由到轻量算子还是重型算子，并给出理由。这是退化感知路由的核心：**让路由依据来自可测量的退化统计，而不是来自模型对整幅图的平均表现**。

**自适应提示生成。** 论文的 LLM 为每个特征写 semantic description，并用跨模型 FI 分数持续微调检索 LLM。迁移到图像融合时，Agent 为每次融合生成条件提示词：描述当前退化组合、期望保留的结构、要抑制的伪影、下游任务偏好。这些提示既是算子的输入，也可以被写回信号库。持续微调的监督信号换成“该提示在下游任务上的质量增益”，形成跨任务共享的提示经验。

**多模态工具链设计。** 按论文的 agent/tool 二分法切：LLM 侧负责假设生成、历史推理、operator steering 的解释；工具侧包含五个确定性模块，分别是退化估计器、算子候选检索器、质量度量器（保真度、自然度、结构一致性、下游 mAP/PSNR/SSIM 等）、资源计数器（FLOPs、延迟、显存、logging 量）、共享预算 ledger（记录某个预处理结果或中间模态是否已被同预算下其他任务使用）。Agent 不能自己宣布成功，winner 由固定规则给出。

**端到端闭环反馈。** 闭环是 H → Researcher → hypothesis → Validate/Trim → Train/Measure → H。图像融合版本里，Measure 要同时产出图像级质量分和下游任务奖励，并把两者都写进 H；慢循环早停掉超过延迟或显存 cap 的算子组合；快循环在有 GPU 空位时补跑新组合。长期记忆就是同一个 session 的完整试验历史。

## 6. 核心数学推导过程

这一节从最基础的概念推到论文的两个优化式。数学基础差的读者可以先看直觉，再对符号。

**背景 1：重要性分数为什么能当特征价值。** 给定一个已训练模型和一个验证 batch，permutation importance 的做法是：把特征 i 的值打乱，看 loss 涨多少。涨得多说明模型依赖它。Shapley 值来自博弈论：一个特征的价值等于它在所有可能的特征加入顺序中带来的平均边际损失下降。Kernel SHAP 用加权线性回归在一组采样 coalition 上估计这个Shapley 值。把这些分数归一化到和为 1，就得到每个特征在当前模型里的相对重要度 f_ij（【论文明确声称】，【文献已有结论】关于 Shapley 定义）。

**背景 2：Pareto 支配。** 设模型有 J 个任务，特征 i 的重要度是向量 $f_i = (f_i1, …, f_iJ)$。说 i 支配 i'，记作 i ≻ i'，当且仅当：对每个任务 j，f_ij ≥ f_i'j；并且至少存在一个任务 j 使 f_ij > f_i'j。所有没有被任何其他特征支配的特征构成第一前沿 P1。把 P1 拿掉，在剩下的特征里重复，得到 P2，依此类推。选特征时按 P1、P2、… 的顺序整层整层地拿，直到累计数量达到 N。这个操作的好处是：click 上排第一、conversion 上排末尾的特征不会被“平均掉”，因为它没有被任何特征支配（【论文明确声称】）。

**背景 3：mixture 如何生成特征集。** 有 M 个排序来源，π = (π_1, …, π_M)，Σ_m π_m = 1。来源 m 按自己的排名依次添加尚未被选中的特征，直到贡献了 round(π_m N) 个。对类别 c 取 n_c 个，四类并起来就是：

S(θ) = ⋃_{c∈C} Blend_{n_c}(F_c \ B; π)，θ = (n, π)。

这里 π 和 n 完全决定特征集，因此搜索空间被压缩成这两个变量（【论文明确声称】，Eq. 1）。

**背景 4：主优化问题。** 记 θ_0 = (n_0, π_0) 为 incumbent 配置，NE(θ) 是归一化熵（越低越好），R 是资源指标集合，R_k(θ) 是第 k 个指标的值，ρ_k 是相对 incumbent 的上限。要解：

θ★ = arg min_θ NE(θ)，满足 R_k(θ) ≤ ρ_k · R_k(θ_0)，对所有 k ∈ R。

几个细节值得停下来讲。QPS 作为 cap 时，论文把它写成 1/QPS，这样“吞吐至少是多少”就变成“某个量不超过上限”的统一形式。FLOPs 是 QPS 的代理，例如 ρ_k = 1.2 表示 FLOPs 最多涨 20%。pipeline cost 不放进这组约束，单独用 trimming 处理（【论文明确声称】，Eq. 2）。

**背景 5：为什么按重要性取 top-N 会错。** 假设 cost 是可加的、每特征一个标量，那么“按 value/cost 排序取到预算用完”是最优的。论文的论点是生产成本是多维、类型相关、集合相关的：变长 sparse 特征可能远比 dense 标量贵；一个特征的成本是否被计入取决于同预算下有没有别的模型用它。所以这个贪心解的假设不成立（【论文明确声称】）。

**背景 6：pipeline-cost trimming 的约束式。** 记 I 为 incumbent 特征集，Δ_b(S) 是用 S 替换 I 后预算 b 的 attributed pipeline cost 变化，C_b(I) 是 incumbent 在预算 b 上的 attributed cost。每个 trial 必须满足：

Δ_b(S) ≤ τ · C_b(I)，对模型被记账的每个预算 b。

τ = 0 表示把每个预算锁在 incumbent 成本；τ > 0 允许有界增长；τ < 0 要求节省。因为成本是查表可得，这个约束在训练之前就能检查，不需要等训练完（【论文明确声称】）。Trimming 的做法是：保留 Blend 选出的集合，只修破坏预算的部分，最贵的新增先删，再用同类里排名最高的“已经在用”的特征回填。于是每类数量不变 → θ 不变 → FLOPs 基本不变，只有 pipeline cost 降下来了（【论文明确声称】）。

**背景 7：异步搜索为什么需要两个循环。** 一次评估几小时到几天，K≈10–25，W≈4–8。快循环 δ_fast 负责在有空位时立刻补 trial，避免 GPU 空转；慢循环 δ_slow 负责测量、早停超 cap 的 trial、更新 Pareto frontier。早停的作用是让违反约束的 arm 不继续消耗剩余时间（【论文明确声称】）。

**最后的 winner 规则。** 在所有终态 trial 里，先过滤掉任何 R_k 超 cap 的，再过滤掉 NE 不优于 incumbent 的，取 NE 最低者。若集合为空，返回 incumbent。这条规则写在 Algorithm 1 的 14–15 行，LLM 无权改写（【论文明确声称】）。从优化角度看，这一步把“LLM 的搜索提议”和“可行性/最优性判定”彻底解耦，是整套设计能上生产的关键。

## 7. 论文如何设计实验验证方法和 claim？

按“提出什么问题 → 设计什么实验 → 答案是什么”来读，论文其实在回答四个问题。

**问题 A：在固定 serving 预算下，跨类别再平衡能不能提升 NE，还是只能靠整体加特征？**
实验：在一个基线为 300/100/30/30 的模型上跑 25 次 trial，只调 volume n，固定 π。记录 NE、FLOPs、QPS，画出 NE–QPS Pareto frontier 和按提交顺序的搜索进度图。答案：前沿从最快 trial（+1.47% NE，1.10× QPS）延伸到最准 trial（−1.08% NE，0.77× QPS）；Fig. 2b 显示 new best 在预算后段仍不断出现，来自 greedy、exploration、evolutionary 三个家族（【论文明确声称】）。这说明搜索没有早期枯竭，非贪心家族确实贡献了后期收益。

**问题 B：在真实生产 cap 下，recipe 式的再平衡是否优于单类别扩张？**
实验：一个 per-event conversion 生产模型，基线 1200/789/50/47，cap 为 1.2× FLOPs。把初始 trial 分成“只加 dense”“只加 sparse”“只加 transform”和“recipe：embedding 翻倍 + sparse 砍 14%”。答案：前三类全部持平或更差，recipe 让 NE 相对基线降 0.17%（【论文明确声称】）。这是论文对“rebalancing across categories”最直接的证据。

**问题 C：fleet-aware trimming 能不能在不动模型配置的前提下守住共享预算？**
实验：六个生产模型，和“untrimmed, importance-only control”对比，τ = 0。答案：六个模型全部进入预算，attributed pipeline cost 平均降 2.3%，最多降 6.3%；每类特征数量完全一致，FLOPs 变化在 0.3% 以内，主任务 loss 最差 +0.03%，落在 run-to-run noise 内（【论文明确声称】）。

**问题 D：这套系统对线上指标有没有用？**
实验：系统运行六个月以上，多次上线，做线上 A/B。答案：主在线指标提升 0.20%（【论文明确声称】）。

**跨模型的整体效果。** 七个高影响模型，在各自预算内 NE 平均降 0.31%；论文声明 ΔNE 超过 0.03% 才算显著（【论文明确声称】）。

### 7.5 融合质量提升的来源与消融：从论文证据到图像融合实验设计

论文对“提升来自哪里”给出的因果解释是明确的：来自跨类别再平衡，因为继承的 per-category counts 做不到这一点（【论文明确声称】）。它对另一些组件的贡献没有做消融，这些属于缺口：

- 检索 LLM 的跨模型持续微调：没有消融，无法量化它单独贡献多少 recall 质量（【基于证据的推断】：论文把它列为贡献点并给了机制，但 Results 段没有对应对照）。
- mixture π 的调节：实现了但未评估，所有实验固定 π（【论文明确声称】）。
- 各个 FI 估计器、segment-aware 变体、Pareto 混合：没有拆分消融（【基于证据的推断】：Results 只报告整体系统效果）。
- Researcher 的四种行为家族：Fig. 2b 标了家族，但没有给出“去掉 exploration/evolutionary 会怎样”的对照。
- 与随机搜索、贝叶斯优化等标准 black-box baseline 的对比：论文没有给出（【基于证据的推断】：从抽取全文看没有此类表格）。

如果要把这套思路搬到图像融合并做扎实的消融，我建议这样设计（【基于证据的推断】）：固定下游任务和算力预算，做五组对照，分别是固定最强单一融合算子、随机算子调度、退化感知但无 agent 记忆、agent 有记忆但无共享预算 trimming、完整系统。度量同时报四类：保真度（PSNR/SSIM）、感知质量（LPIPS 或人类偏好）、下游任务（mAP/分割 IoU）、资源（延迟、FLOPs、显存、共享预处理次数）。这样能区分“质量提升来自算子本身”“来自按退化路由”“来自跨试验记忆”“来自预算复用”。论文的 NE–QPS 前沿对应到这里就是“质量–资源前沿”，论文的 run-to-run noise 概念对应到这里就是多次随机种子的方差。

## 8. 总结 take aways

1. **把特征选择写成优化问题，而不是启发式流程。** 决策变量只有 n 和 π 两组，特征集由 Blend 确定性生成，这让 LLM 的搜索空间小到可以推理。
2. **LLM 负责提假设，确定性工具负责产生事实。** FI 排序、成本查表、训练测量、validator、winner 规则全在工具侧；LLM 的提议要是越界、重复或超参范围外，会在花预算之前被拒（【论文明确声称】）。
3. **硬约束和软偏好要分开。** serving cap 做成不等式，pipeline cost 做成训练前的 trimming，类别 volume 的经验区间只当搜索启发式，不当 constraint（【论文明确声称】）。
4. **多任务不要用加权和。** Pareto front 不需要任务权重，也能保住单任务强特征。
5. **小预算搜索要留后手。** 25 次 trial 里，后期 new best 来自 exploration 和 evolutionary；如果前几把就把预算耗尽在贪心上，这些收益拿不到。
6. **舰队级的收益来自共享，不是来自单模型更聪明。** 一个跨模型微调的检索 LLM，一个按“同预算下有没有别的模型用过”记账的 trimming，是两个真正的 fleet-level 机制。
7. **生产落地靠的是可验证性。** winner 规则预先固定且 LLM 不能覆盖，这在工程上比“agent 自己判断哪次更好”重要得多。
8. **数字要放在正确的量级上看。** NE −0.31%、pipeline cost −2.3%、线上 +0.20% 都不大，但它们是在已有成熟模型上、守住硬预算后拿到的，且论文声明 ΔNE > 0.03% 才显著（【论文明确声称】）。

## 9. 这篇论文最脆弱的假设是什么？

最脆弱的一条是 pipeline-cost 的 attribution 规则：**“同预算下另一个模型已经用过这个特征，则新增它不增加 pipeline cost”**。论文把它直接写成事实并据此设计 trimming（【论文明确声称】）。它成立需要几个很强的条件：使用是二值的、成本在预算层面可分摊、边际成本在第二个消费者出现时真的归零。现实里 processing 查询量、日志量、存储量往往随消费者数量变化，变长 sparse 特征的日志量尤其敏感。论文自己也承认这些成本是 set-dependent rather than additive，这与“第二个用户免费”的规则之间存在张力（【基于证据的推断】：这是我从论文两处表述的并置中读出的张力，论文没有讨论这个矛盾）。如果这个 attribution 错，trimming 会把本该付费的特征留下，预算表面合规、实际超标。

第二脆弱的是 **FI 排序对新配置的迁移性**。FI 分数来自“一次在完整候选池上训练的模型”，然后用来指导一个新特征子集的构建。当 volume 大幅重排（例如 embedding 翻倍、sparse 砍 14%）时，特征间交互会变，原先的边际重要性未必保留。论文没有报告 FI 分数跨配置的相关性或稳定性（【基于证据的推断】）。

第三是 **NE 作为优化目标与线上主指标的一致性**。论文用 NE 做 winner 规则，最后报线上 +0.20%。它没有给出 NE 增量与线上指标增量之间的相关性分析。0.31% 的 NE 改善对应 0.20% 的线上指标，这个转换关系在不同模型上是否稳定，是未知的（【猜测】：可能相关，也可能只是几个上线模型的巧合；论文没有证据）。

第四是 **trial 预算假设**。K≈10–25、W≈4–8 被当作既定约束。如果某个模型交互极其复杂，25 次可能不够；如果另一个模型很平滑，25 次可能太多。系统没有自适应决定何时停止（【论文明确声称】搜索跑到 K 用完为止）。

第五是 **0.03% 显著性阈值**。论文声明 ΔNE 大于 0.03% 才算显著，但没有给出这个阈值的来源、估计方法和置信度。线上 A/B 的 +0.20% 也没有给置信区间（【基于证据的推断】：从抽取全文看不到统计细节）。

## 10. 如果我有 1 周时间，能做一个最小复现实验验证它的哪一点？

选最容易验证、也最核心的一点：**在固定 FLOPs cap 下，跨类别再平衡优于单类别扩张**。不要试图复现整套系统，也不要碰跨模型微调和线上 A/B。

**数据与代理。** 用一个公开点击日志数据集（Criteo Display Ads 或 Avazu 量级足够）做代理。把特征人工分成四类模拟 dense / sparse / embedding / transform：连续字段当 dense，类别 ID 当 sparse，随机初始化的低维向量当 upstream embedding，dense 分桶交叉当 transform。成本表自己造：dense 每槽 FLOPs 1，sparse 每槽 FLOPs 3 加内存，embedding 每槽 FLOPs 8，transform 每槽 FLOPs 5；pipeline cost 用一张简单的“特征 → 成本”表，并标记哪些特征已被“同预算下的其他模型”使用。

**实现最小版本。** 只实现 Eq. 1、Eq. 2、Pareto blending 和 trimming；Researcher 用随机采样加简单启发式代替 LLM，因为要验证的是搜索空间结构，不是 LLM 的语言能力。跑三组各 25 次 trial：A 组只允许单类别扩张，B 组允许跨类别再平衡，C 组允许再平衡加 trimming。每组用相同数据窗口、相同随机种子。

**度量。** 画 NE（或 logloss）对 FLOPs 的 Pareto 前沿；统计每组超过基线的 trial 数、最佳 trial 出现的位置、预算违反次数；对 C 组额外检查论文的两个不变量：每类特征数量是否和提议配置一致、FLOPs 变化是否在很小范围内。

**预期与判据。** 如果 B 组前沿明显优于 A 组，且最佳 trial 出现在后段，就复现了论文 Table 1 和 Fig. 2b 的定性结论；如果 C 组能把 pipeline cost 压下来同时保持 FLOPs 和数量不变，就复现了 trimming 的核心性质。如果 B 组不优于 A 组，那说明“再平衡收益”依赖于真实广告特征的特殊结构，论文的结论外推性有限。这个实验一周内可做，因为模型小、 trial 是分钟级。

## 11. 如果我反对它，我会怎么设计反例？

**反例 1：强互补性打破再平衡假设。** 构造一个合成任务，sparse 特征和 dense 特征必须有固定比例才能学出交互，单独增减任何一类都掉点。这时论文的 recipe（砍 sparse、补 embedding）会失效。判据：recipe trial 的 NE 不优于基线，且所有FI 排名靠前的特征仍属于被砍的那一类。这个反例直接攻击“提升来自跨类别再平衡”的因果解释。

**反例 2：attribution 规则被钻空子。** 设一个预算下有 20 个模型，全部开始使用同一个极贵的 logging 特征。按论文规则，第二个以后的模型都觉得它“免费”，于是所有模型都保留它。实际logging成本随消费者数线性增长，预算爆掉。判据：attributed cost 显示为 0 增长，实际观测到的存储与 ingestion 成本翻倍。这个反例攻击 trimming 的记成本方式。

**反例 3：segment-aware FI 过拟合高价值切片。** 让高价值流量切片的分布和整体分布差异很大，且切片样本很少。segment-aware 估计器会把只在切片上偶然相关的特征排到前面。判据：这些特征在切片上 FI 高，在留出集和线上 A/B 上无增益甚至负增益。论文没有报告 segment-aware 的泛化检查。

**反例 4：NE 与线上指标脱钩。** 找到一组特征配置，NE 改善 0.1% 但线上点击或转化下降。原因是 NE 衡量的是概率分布校准，线上业务指标可能由排序位次、外部性决定。判据：NE–线上指标的相关系数在多个模型上接近零。论文只报了一个汇总的 +0.20%，无法排除这种脱钩。

**反例 5：LLM 搜索坍缩。** 让 validator 统计数据发现，Researcher 在 25 次 trial 里提交了 20 次近似重复的 recipe，大部分被拒或被 early-stop。有效独立试验数远小于 K。判据：去重后有效 trial 数小于 10，且 new best 全部出现在前 5 次。这攻击“LLM as optimizer 在 10–25 次预算里表现好”的隐含假设。

**反例 6：长 trial 期间分布漂移。** 一次 trial 跑几天，期间流量分布变了。用同一数据窗口的 baseline 比较会失真，winner 规则选出的其实是“赶上了好流量”的配置。判据：同一配置在不同时间窗重跑，NE 波动超过 0.03% 的显著性阈值。论文说每个 trial 用和 baseline 相同的数据窗口，但没有说是否做时间对齐或漂移校正（【基于证据的推断】）。

## 12. 调用搜索工具调研后续研究，是否有进一步扩展或反驳，以及新的认知？

本次检索做了几组查询，结果如下。

在 arXiv 上搜索 `LLM agent feature selection ranking cost-aware`，只返回两篇：本文（arXiv:2611.26531）和一篇 QoS-aware 的 agent skill 服务推荐（arXiv:2607.00011）。后者研究的是给 LLM agent 在预算下挑技能服务，和本文在“预算约束下的 agent 决策”这个抽象层面相似，但对象不同（【基于证据的推断】：从标题和摘要看，未见直接引用或扩展本文）。

Semantic Scholar API 查询本文记录：year 2026，referenceCount 13，citationCount 0（检索时）。这意味着截至本次检查，没有公开引用本文的后续工作，谈不上被扩展或反驳（【基于证据的推断】：引用数为 0 只能说明未见公开引用，不代表没有被工业界内部采用；论文自己说已上线六个月）。

在 arXiv 上搜索 `LLM agent image fusion degradation-aware tool use`，返回零结果；换成 `LLM agent image fusion multimodal fusion decision`，返回四篇相关方向：MM-VeriRec（arXiv:2609.31718，failure-guided fusion for verifiable agentic multimodal recommendation，ACM Multimedia 2026 workshop）、一篇多模态 agentic framework 综述（arXiv:2608.20379，TMLR 接收）、LCMF（arXiv:2509.18576，轻量跨模态 Mambaformer 用于具身机器人 VQA）、以及一篇大视觉语言推理综述（arXiv:2505.04921）。这些工作说明“agentic + 多模态 + 融合”在 2025–2026 是活跃方向，但没有任何一篇把本文的舰队级成本感知特征选择机制搬到图像融合（【基于证据的推断】：基于标题、摘要和检索命中情况）。

另外我核对了几篇基础工作的实际内容，避免张冠李戴：arXiv:2402.03620 是 Self-Discover（LLM 自组推理结构），说明“LLM 自己组合原子模块形成结构”这条线在 2024 年已有；arXiv:2304.02643 是 Segment Anything，提供了可提示的分割工具，这在图像融合里可以作为 Agent 调用的一个确定性工具（【文献已有结论】）。

新认知有两点。第一，本文的引用数为零但已上线六个月，这种“工业系统先落地、学术引用滞后”的模式在 arXiv 预印本里常见；不能把缺少后续论文当成方法无效。第二，图像融合侧的 agentic 工作目前集中在“用 agent 做推荐/推理的可验证性”和“轻量跨模态架构”，缺少一篇把**预算、共享成本、异步试验循环**讲清楚的融合系统论文。这正好是本文机制可以迁移的空位（【基于证据的推断】）。

## 13. 基于你的信息提出一个 follow-up idea

**题目：Degradation-Conditioned Fusion Operator Fleet（DCFOF）——按退化条件调度融合算子的舰队级预算优化系统。**

这个想法从本文的三个缺陷出发：π 的调节实现了但没评估；FI 排序假设跨配置稳定；pipeline cost attribution 在真实共享场景下可能被钻空子。同时对应图像融合的真实需求：同一个下游系统要服务多个视觉任务，退化类型千差万别，重型融合算子不能对所有输入都开。

核心设计如下。

**搜索空间不再是特征数量，而是“退化条件 → 算子组合 + 提示”的路由策略。** 定义退化向量 d（噪声、模糊、遮挡、错位、低照度、模态缺失）。定义融合算子集合 O，包含轻量通路（通道拼接、逐元素加权）、结构通路（多尺度注意力、分割引导）、生成通路（diffusion prior 补全）。Agent 的假设写成 h = (g, o, U, p)：在什么退化门控 g 下，对哪些模态/层 U 调用算子 o，用什么提示 p。这比本文的 (n, π) 更结构化，也更难，因此价值更高。

**双通道质量信号。** 一条是图像级：保真度、感知质量、结构一致性；一条是任务级：下游 mAP、IoU 或跟踪精度。用本文的 Pareto front 方法融合，不对两类分数做加权和，也就不引入手调权重。

**共享预算的 ledger 改成按实际用量记账。** 针对第 11 节反例 2，ledger 不记录“是否被用过”这个二元状态，而记录每个预处理结果或中间模态的消费者数量和实际 resource footprint。trimming 的约束改成 Δ_b(S) ≤ f(consumer_count, footprint)，而不是论文的 τ C_b(I)。这是对新缺陷的直接修补，也是和本文最实质的区别。

**端到端闭环。** 退化估计器产出 d → Agent 读历史 H 和 guide G（每个算子的预期质量增益与 FLOPs/延迟）→ 提假设 → validator 检查门控范围和预算 → 确定性工具执行融合与下游评估 → 慢循环早停超预算 arm、更新质量–资源前沿 → 快循环补空位 → 写回 H。跨任务共享的部分：一个路由器在多个下游任务上微调，监督信号是“该路由在该退化条件下带来的质量增益”，类似本文的跨模型微调检索 LLM。

**可证伪的假设。** 在固定延迟预算下，退化条件化的算子路由在严重退化子集上比单一最强融合算子提升可测量的下游指标，同时在轻度退化子集上不显著增加计算。这个假设可以被直接否定：如果退化估计器不准，或者算子之间没有明显的条件优势，路由就不会赢过固定算子。

**风险。** 退化估计本身会出错，错误门控会放大伪影；图像质量的评价比 NE 噪声大得多，0.03% 级别的差异可能被随机种子淹没；FLOPs 与真实 GPU 延迟的对应关系在访存密集的融合算子里比在 tabular MLP 里弱。这三点必须在系统设计时正面处理，而不是当作细节。

<!-- PAPERFLOW_METRICS_JSON
{
  "task": "舰队级广告排序模型的有成本约束特征选择与生成：在 per-model serving cost cap（QPS/FLOPs/延迟/内存）和跨模型共享 feature pipeline cost 预算下，自动为每个模型生成、排序、混合并挑选特征，最小化归一化熵 NE。",
  "backbone": "LLM 检索生成器（一个跨模型 FI 标签持续微调的共享 LLM，负责 cross feature 召回与语义信号生成） + LLM Researcher agent（observe-reason-act，LLM-as-optimizer，四行为家族 greedy/exploration/evolutionary/recipe） + 确定性工具链（permutation / Shapley sampling / Kernel SHAP / segment-aware FI，Pareto blending，validator，pipeline-cost trimming，异步调度与早停，固定 winner 规则）。底层为生产 ads ranking model，输入含 dense / sparse / transform / embedding 四类特征。",
  "datasets": [
    "Meta 生产广告排序流量（论文未公开数据集名称与规模）",
    "高价值流量切片（top revenue buckets，用于 segment-aware FI）",
    "七个高影响生产排序模型（NE 平均 -0.31%）",
$$
"六个生产模型（pipeline-cost trimming 对照，τ=0）",
$$
    "线上 A/B 测试（六个月以上，多次上线）",
    "公开基线示例：论文 Table 1 的 300/100/30/30 配置与 1200/789/50/47 per-event conversion 配置"
  ],
  "sota_summary": "论文不与公开 benchmark SOTA 对比，报告的是生产系统相对 incumbent 的增益：七个高影响模型在各自预算内 NE 平均 -0.31%（论文声明 |ΔNE|>0.03% 才显著）；六个模型上 attributed pipeline cost 平均 -2.3%、最多 -6.3%，τ=0 时全部进入预算，类别数量不变、FLOPs 变化 ≤0.3%、主任务 loss ≤+0.03%（噪声内）；线上 A/B 主指标 +0.20%。25 次 trial 的 NE–QPS 前沿从 +1.47% NE @ 1.10× QPS 到 -1.08% NE @ 0.77× QPS；recipe trial（embedding 翻倍、sparse -14%）在 1.2× FLOPs cap 下取得 -0.17% NE。mixture π 调节已实现但未评估；检索 LLM 持续微调、各 FI 估计器、四行为家族均未做单独消融。",
  "innovation_tags": [
    "agentic-feature-selection",
    "llm-as-optimizer",
    "fleet-level-continual-fine-tuning",
    "pareto-feature-blending",
    "pipeline-cost-trimming",
    "asynchronous-constrained-search",
    "deterministic-tool-verification",
    "cost-aware-ranking",
    "segment-aware-importance",
    "image-fusion-transfer-potential"
  ]
}
-->

---

<!-- AI-GENERATED-NOTICE -->
!!! note "内容由 AI 生成，请审慎甄别"
    本站的论文解读、摘要速览与网站点评均由人工智能自动整理生成，仅用于学习与快速检索。
    AI 输出可能存在事实偏差、理解误差或信息滞后，涉及关键结论、数据与观点时，
    请以论文原文及官方来源为准，并自行判断其准确性。
