---
paper_uid: arxiv_2611.26435
title: "Aggron: Aggressive Compression of Agentic KV Caches during Head-of-Line Stalls in the Request Queue"
venue: "arXiv 2026"
year: 2026
tier: "arXiv preprint (cs.DC/cs.AR)"
tldr: "Aggron 把 Agent 的历史压缩从请求关键路径移到服务器的排队等待里：只总结最新非结构化证据之后的 prose 尾段，用队列深度决定压缩阈值，用独立摘要队列和三个 gate 保证摘要能在请求出队前落地。在高负载下相对 Slipstream/APEC 降低 P99 27%/31%，吞吐提升 1.34×/1.40×，准确率保持在运行间噪声内。"
tags: [agentic-serving, kv-cache, context-compression, head-of-line-blocking, vllm, queue-aware-scheduling, multimodal-agent-fusion, tool-chain, closed-loop-feedback]
code_url: "N/A"
paper_url: "https://arxiv.org/abs/2611.26435"
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


## 1. 论文提出并解决的研究问题是什么，为什么重要

**论文明确声称**：本文处理的是在线多租户服务场景下的 Agentic LLM KV  cache 膨胀问题。Agent 一次任务包含几十到几百次模型调用，每次工具输出都追加进上下文。生产 trace 中 90 分位 session 发起超过 100 次模型调用，Codex 达到 241 次，上下文峰值 186K token，Codex 为 235K token。即使使用混合线性注意力或 latent attention，一个 128K token 的 GLM-4.5 请求也占约 40 GB HBM，两个就填满 H100 的 80 GB。

问题的重要性集中在三个数字上：

- **KV 容量先于算力饱和**。论文回放生产 trace 和 benchmark trace，在 TP=8 下，单轮请求的 batch 能到 1024 上限，Agentic 请求的 batch 中位数停在 37。GPU 算力空着，后续请求排队。
- **延迟主要来自 admission wait**。高负载下 60% 到 79% 的端到端时间花在等 KV block；队列头的请求有 75% 到 89% 的运行时间无法被 admit。
- **压缩本身也有代价**。同步压缩把 summary 放在关键路径；异步压缩让 summary 和 Agent 请求抢同一块 KV 与 batch slot。论文指出，既有异步方案多在独占服务器上评估，这和共享服务的拥塞结构不同。

论文要回答的核心问题是：**能否在共享、高负载的 serving 系统里，既缩小每个 Agent 请求的 KV footprint，又不牺牲任务准确率，也不把 summary 的 prefill/decode 成本转嫁到关键路径？**

**价值**分两层。系统层面，论文报告在高负载下相对 Slipstream 和 APEC，P99 latency 降低 27% 和 31%，mean latency 降低 11% 和 15%，throughput 提升到 1.34× 和 1.40×；在四个 frontier 模型上，配合尾部 KV 复用时吞吐提升 5% 到 17%。方法层面，它把压缩决策从固定的上下文长度阈值改成由**队列状态**驱动，给出一种把系统空闲资源用于语义压缩的具体机制。

**迁移说明**：用户给的专属侧重提到 Agent 在图像融合中的决策角色。本文本身是文本 Agent 的 KV serving 系统，没有图像融合实验，也没有多模态工具链。后文会把 Aggron 的决策结构映射到图像融合 Agent，这一部分标为**合理推断或研究建议**，不写成论文结论。

## 2. 之前是否被解决过，已有方案哪里不足

**相关文献已有结论**，已有路线分成四类。

**同步摘要**。Agent harness 在上下文接近窗口上限时暂停，运行一次 summarization，再从 summary 继续。缺点是 summary 直接躺在关键路径上，提高 mean 和 P99 latency。论文指出，在小 prose cap 下 summary 本身只占排队时间的一小部分，所以完全同步仍能拿到接近异步的吞吐，但它的压缩时机仍然由请求自己的长度决定，服务器无法利用排队窗口。

**异步摘要**。APEC 在上下文越过软阈值后对快照做后台摘要，下一次请求时安装；Slipstream 在 Agent 旁边运行 compactor 并用 judge 验证摘要。论文明确声称，这类工作在独占服务器上有效，但在多租户共享服务中，summary 会和普通 Agent 请求争 KV 与 batch slot。Figure 6c 显示使用异步摘要后第 k+2 次 Agent 执行因 contention 变慢。

**整段上下文压缩的阈值策略**。Belcak 等人在 16K 预算下压缩完整历史并重启，报告准确率损失很小。论文的 Table 1 显示，整段摘要在 DeepResearch Bench 上较稳定，但在 SWE-bench 上准确率最多下降 6 个百分点，因为代码、变量名、assertion 这类结构化内容被摘要后语义丢失。论文由此把数据分成 prose 和 non-prose。

**KV eviction、pruning 和量化**。H2O、Scissorhands、StreamingLLM、SnapKV、PyramidInfer 根据注意力分数丢 token 或 KV。论文的 Figure 5 显示 SWE-bench 轨迹里，早期 6K 到 8K 位置的 key 在多数后续 query 中几乎不被注意，但两个后续迭代会重新访问它们。按注意力排名筛选会先丢掉这些 token。CPU offload 可以保留可达性，但 CPU-GPU 互连带宽比 HBM 低 10 到 50 倍。TriAxialKV、NVFP4-MLA 等量化和 latent storage 方法降低每 token 成本，却不改变“上下文增长导致 KV 增长”这一事实。

**Agent 记忆与调度**。ACON、ReSum、MEM1、AgentFold、CompactionRL、SelfCompact、MemGPT 主要从模型训练、提示策略或固定阈值入手。Autellix、Pythia、ThunderAgent 做 program-level 调度，Continuum、MORI、InferCept 做 KV 保留、迁移或 offload。论文明确声称，这些系统没有从队列状态决定“何时压缩、压缩哪一段、压缩请求放哪个队列”。

不足可以概括成一句：**已有方法要么优化模型侧摘要质量，要么优化 GPU 上的 KV 占用，要么优化请求顺序；Aggron 优化的是拥塞服务系统里“压缩这件事发生在哪里、什么时候发生、由谁承担成本”。**

## 3. 作者可能的思考路径

以下是**基于论文背景和观察的合理重建**，不使用论文贡献作为前提。

第一步，先看资源曲线。Figure 1 说明上下文长度和 KV 占用近似线性增长，128K 的 GLM-4.5 请求占 40 GB。Figure 4 说明 Agentic 请求先填满 HBM，batch 停在 37 左右，后续请求排队。到这里，优化目标自然从“decode 更快”转向“每个请求占更少 KV block”。

第二步，分解延迟。Figure 6c 显示高负载下请求超过 60% 的时间在排队。Table 3 进一步显示队列头经常卡住，约 5% 的阻塞时间中，如果队头稍微小一点就能被 admit；如果把所有等待请求的 tail 压掉，约 46% 的阻塞时间可以多 admit 至少一个请求。这里的直觉是：**压缩的目标不是缩短一次模型调用，而是让请求尽快通过 admission check。**

第三步，判断什么能压。pruning 看起来便宜，因为不需要 LLM 调用，但 Figure 5 的历史重访模式说明 Agent 会再次 attention 到早年被判为“不重要”的 token。于是方向转向 summarization，即由模型根据语义决定保留什么。Table 1 又暴露出整段摘要在代码任务上的语义损失，所以不能一律压缩，需要按工具输出类型分区。

第四步，处理摘要本身的信息损失。传统方案每次摘要都把已有 summary 再摘要一次，信息被反复蒸馏。一个自然的修正做法是：summary 一旦生成就冻结，后续只追加，不重写。这样每个 token 只经过一次压缩，同时 KV prefix 在整段 episode 中保持有效，避免完整 re-prefill。

第五步，利用等待时间。请求从 tool call 返回后并不立即运行，而是重新进入队列等待 admit。这段时间本来就会支付。如果在这段时间里生成 summary，而且 summary 在请求成为队头前完成，summary 的 prefill/decode 成本就被排队延迟吸收。

第六步，服务器比 Agent harness 更有信息。harness 只知道自己的上下文长度；服务器知道队列位置、admission rate、空闲 KV block、summary 队列积压。压缩决策放在服务器端更合理。

第七步，防止聪明反被聪明误。摘要太小会被队头等住；摘要太大抢 batch slot。三个 gate 因此出现：预测能藏住才发，压缩收益足够大才发，至少释放一个 KV block 才发。

## 4. 方法的 Intuition

**一句话核心**：把上下文压缩从 Agent 的执行路径挪到服务器的排队空档里，只压缩那些语义上可安全压缩的 prose 尾段，并用队列深度决定压缩强度。

这里有三个关键动作：

1. **选对压缩对象**。文件系统读取、SQL 结果、测试日志这些输出保留原文；模型推理、工具调用本身、网页检索文本这些 prose 可以摘要。
2. **选对压缩时机**。请求越靠队列后面，等待时间越长，压缩阈值越低；越靠队头，越不打扰它。
3. **选对执行队列**。summary 请求放到独立队列，只有主队列队头因为 KV 不足无法 admit 时，才把 summary 填进闲置的 KV 和 batch slot。

最终效果是：每次 summary 都很小，论文报告约 300 到 500 token，足够藏进 admission wait；Agent 看到的上下文更短，每个 turn 的 prefill 和 decode 更便宜；更多请求能同时进 batch，队列排空更快。

## 5. 具体方法是什么：输入、处理、输出完整 pipeline

抽取内容没有给出架构图原图，下面按 Figure 7 的文字描述重建。

### 5.1 状态和输入

请求进入 Session Registry。Registry 为每个 session 保存三部分：

- **H**：frozen summaries，已经生成且不再重写的摘要段。
- **P**：protected region，从 transcript 开头到最近一次 non-prose observation 的连续前缀。
- **K**：compressible accumulation，最近一次 non-prose observation 之后、尚未压缩的 prose token 数。

请求从工具返回时重新进入同一个入口。Context Classifier 按 observation 粒度分类。它用 `tool_call_id` 找回产生该 observation 的 tool call，检查工具名和参数。论文把三类工具输出判为 non-prose：

- 文件系统和 shell inspection：`cat`、`grep`、`read_file` 等。
- 数据库访问：`execute_sql`、schema listing、query plan。
- 程序和测试执行：`pytest`、`python`、测试日志。

模型推理、工具调用本身、web search/fetch 结果为 prose。若 Agent 再次读取同一资源，新 observation 替换旧 observation，避免重复副本。

### 5.2 分区规则

non-prose observation 到达后，protected region 向前推进，覆盖它以及它之前所有尚未压缩的内容。好处是不会把 tool call 和解释它的 result 拆开；代价是这次文件读取之前的 prose 不再被压缩。可压缩 prose 正好是最近一次 non-prose observation 之后的尾段。

### 5.3 压缩计数器

论文公式为：

\[
$$
K = \sum_{m \in M} t(m) - \sum_{m \in H \cup F \cup P} t(m)
$$
\]

这里的 \(M\) 是 context 中的 messages，\(t(\cdot)\) 是 token 计数，\(H\) 是 head，\(F\) 是 frozen summaries，\(P\) 是 protected region。 intuition 很简单：**K 不是上下文总长度，而是“摘要真的能压掉的那部分 token 数”。** non-prose observation 到达会把之前内容推入 P，所以 K 归零；摘要触发后 K 也归零。

### 5.4 队列深度相关阈值

Aggron 有两个阈值层级：

- 硬上限 \(T_{def}\)，默认 4096 token。K 超过它就同步压缩，保证 prose tail 有界。
- 等待期阈值 \(\theta\)，默认在 \(T_{min}=1024\) 到 \(T_{hi}=T_{def}-\epsilon\) 之间，\(\epsilon=64\)。

论文公式为：

\[
$$
g = \frac{a f (1-w+ws)}{1+n}
$$
\]

\[
$$
\theta = T_{hi} - g (T_{hi}-T_{min})
$$
\]

其中 \(f\) 是请求在队列中的深度，队尾为 1；\(s\) 是上下文大小排名，最大为 1；\(a\) 是 live program 中的年龄排名；\(n\) 是上次 4K-cap compaction 之后该 program 在排队期生成的 summary 次数；\(w=0.5\)。公式的读法是：\(g\) 越大，\(\theta\) 越低，压缩越激进；排队越久、上下文越大，压缩越值得；多次排队压缩后，\(n\) 会把 \(\theta\) 拉回较保守区域。

论文文本只给出了这些排名的定义和归一化说明，没有展开每个排名的具体标准化实现；复现时需要以 controller 代码为准。

### 5.5 三个 gate

越过 \(\theta\) 只是候选，还要过三关。

**Gate 1：summary 能否藏住。** Aggron 用最近 50 次 issue-to-landing 时间，按每 summary token 的 90 分位数估计 latency，再乘以本次 summary cap \(S_{max}\)。冷启动时使用模型：

\[
$$
t_{sum} = a_{prefill}K + S_{max} t_{step}
$$
\]

再叠加 summary 队列 backlog。请求自己的等待估计为队列位置除以近期 admission rate。只有等待覆盖预测 summary 时间才发出。

**Gate 2：压缩是否值得。** 要求：

\[
K \ge \alpha S_{max}
\]

论文设 \(\alpha=2.5\)。summary 会永久追加进 prompt，如果 tail 只比 summary 略大，压缩收益很小。

**Gate 3：是否释放 KV block。** 要求：

\[
\left\lceil \frac{C}{b} \right\rceil -
$$
\left\lceil \frac{C-K+S_{max}}{b} \right\rceil \ge 1
$$
\]

其中 \(C\) 是当前 context，\(b\) 是 block size。只释放 token 但不释放 block，对 admission 没帮助。首次调用没有 prose tail，不参与；summary 正在飞行的请求跳过；每次 queue visit 最多决策一次。

### 5.6 双队列和服务流程

Aggron 保留主 Agent queue 的 FCFS 顺序。summary 请求进入独立 Compression Queue。每个 batch 调度时：

1. 默认检查主队列队头能否放进空闲 KV。
2. 如果放得下，admit 该 Agent 请求。
3. 如果队头放不下，主队列暂停 admit，从 summary queue 抽取一个 summary 请求填入空闲 KV 和 batch slot。
4. summary 完成后，Registry 在原位置替换压缩区域；Agent 请求没有离开队列，也没有丢掉位置。
5. 如果 summary 在请求成为队头时还没落地，请求占住队头等待，后面的请求继续做自己的 summary。

系统还有一个 reset ceiling \(R\)。当 assembled context 超过 \(R\) 时，Aggron 把所有内容，包括 frozen summaries，压成一个新段并重启。这一步很少发生，是防止线性增长撞上模型窗口的兜底。

### 5.7 一个具体例子

以 SWE-bench 的仓库修 bug 任务为例：

1. Agent 读文件，得到一段源码。Context Classifier 判为 non-prose，这段源码进入 protected region，K 归零。
2. Agent 写了几轮自然语言推理和两次 web search，这些是 prose，K 累加到 1800。
3. Agent 运行 `pytest`，得到失败日志。日志是 non-prose，protected region 推进到日志之后，K 再次归零。日志之前的自然语言推理不再压缩。
4. Agent 又产生 2500 token 的 prose tail。请求 tool 返回后重新排队，队列深度较深，\(\theta\) 被压到 1300 左右，K 超过阈值。
5. Controller 检查 gate 1：按最近 summary latency 估计 9 秒能完成，请求预计 25 秒后才轮到队头，通过。
6. Gate 2：\(2500 \ge 2.5 \times 400\)，通过。Gate 3：压缩后至少释放一个 1056-token block，通过。
7. summary 请求进入独立队列。主队列队头此时 KV 不够，scheduler 把 summary 填入 batch。
8. 400 token 的 summary 落地，作为 frozen segment 追加。K 归零，请求位置不变。
9. 请求成为队头时上下文已经变短，被 admit；prefill 和后续 decode 都更便宜，释放出的 block 让下一个请求也能进来。

输出是三件事：更短的 session context、保持不变的 protected tool outputs、更高的 KV block 周转率。

### 5.8 迁移到 Agent 图像融合：Agent 的决策角色如何落地

这一小节是**基于证据的合理推断，不是本文实验结论**。Aggron 里真正做压缩决策的不是 Agent harness，而是服务器端 Controller。这个角色拆分对图像融合 Agent 很关键：Agent 负责提出动作，Controller 负责根据系统状态和证据类型决定是否执行、何时执行、走哪个队列。

**动态算子调度**。在图像融合任务里，可调度对象从“summary 请求”扩展成一组工具算子：去噪、配准、曝光对齐、区域修复、跨模态融合、质量验证、重新采集。Controller 可以参考 Aggron 的三层状态：哪些证据必须原样保留，哪些语义描述可以压缩，哪些算子可以延迟到等待窗口执行。调度依据包括队列深度、GPU 空档、退化程度、下游任务置信度。

**退化感知路由**。Aggron 的 prose/non-prose 分类在图像融合中可迁移成“可摘要语义/不可变证据”分类。原始图像块、校准矩阵、配准参数、退化图、分割 mask、失败 patch、传感器读数应当作为不可变证据保留；自然语言解释、检索文本、历史摘要、失败复盘可以压缩。进一步可以构造退化向量 \(d=(\sigma_{noise}, B_{blur}, \delta_{align}, l_{lowlight}, a_{artifact})\)，用轻量感知工具估计，再路由到对应算子。CRT-HMAR 的工作提供了相关证据：它用 causal requirement tracing 把任务语义偏好映射到图像级需求图，再由多个 agent 分层调节开放任务下的红外-可见光融合，说明“需求解释-任务平衡-冲突缓解”的 agent 链条在融合任务中可行。

**自适应提示生成**。Aggron 冻结 summary，避免反复摘要造成信息蒸馏。图像融合 Agent 可以把每一轮的工具发现写成 frozen evidence card，包含证据指针、退化标签、采用的算子和置信度。下一轮 prompt 由当前观测、frozen cards 和 protected evidence 组成，而不是重写整段历史。这样既控制 prompt 长度，也保留图像证据的可追溯性。

**多模态工具链设计**。一个可落地的链条包括：感知工具输出质量分数和退化图；证据注册表保存原始图像、patch 指针和文本摘要；算子库执行配准、融合、修复；验证工具用下游任务模型或 MLLM judge 判断融合结果；Controller 决定算子进入主队列还是空闲队列；日 Roland 保存工具调用、质量变化和摘要来源。H2MAF 的相关实验表明，MLLM arbitration 在 CNN 冲突样本上收益最大，但收益依赖模型校准，Qwen 在特定风险指标上出现明显 overflag。这个结论支持在融合 Agent 中加入 verifier 校准，而不是无条件信任语言模型的判断。

**端到端闭环反馈**。Aggron 的反馈来自队列 latency、summary 落地时间和 KV block 释放。图像融合还需要质量反馈：融合指标变化、下游任务精度、工具间冲突、Agent 轨迹偏移、重新采集代价。这些信号应回写到 Controller，用于调整退化路由阈值、summary cap、verifier 触发频率和算子预算。

## 6. 核心数学推导过程

先从 KV cache 的基础账本讲起。Transformer 在每个 token、每层 attention 中保存 key 和 value 向量。忽略 GQA 共享细节时，单 token KV 字节数近似为：

\[
\text{bytes/token} \approx L \times 2 \times d_{head} \times n_{heads} \times \text{bytes}
\]

其中 \(L\) 是层数，\(d_{head}\) 是 head 维度，\(n_{heads}\) 是 head 数，bf16 取 2 byte。上下文长度 \(C\) 增长时，KV 占用近似线性增长。论文 Figure 1 给出 1M token 下不同模型的占用：GLM-4.5 为 368 GiB，Llama-3-70B 为 320 GiB，gpt-oss-120B 为 80 GiB。H100 只有 80 GB HBM，其中 92% 分给 KV pool 时也只有约 2.49M token 容量。

decode 每一步都要从 HBM 读取整段 KV，所以缩短 \(C\) 同时减少两件事：新请求需要的 admission KV block 数，以及每个 decode step 的 HBM 流量。prefill 也要处理整个 prompt，因此小上下文降低每一步推理成本。

**K 的推导**。Aggron 不拿 \(C\) 当压缩触发信号。它只关心摘要能真正减少多少 token。把 context 中所有 message 的 token 数求和，再减去 head、frozen summaries 和 protected region 的 token 数，得到：

\[
$$
K = \sum_{m \in M} t(m) - \sum_{m \in H \cup F \cup P} t(m)
$$
\]

这一步的含义是：non-prose 和 frozen summary 对 summarization 不可动，不能计入收益。non-prose 到来时 P 扩张，所以 K 归零；摘要触发后 prose tail 变成 frozen summary，所以 K 也归零。

**阈值的推导**。目标是让队列后面的请求更早压缩，队头请求尽量不被打扰。论文把三个排名做成一个综合 aggressiveness score \(g\)。若 \(g\) 增大，\(\theta\) 按：

\[
$$
\theta = T_{hi} - g (T_{hi}-T_{min})
$$
\]

下降。于是队尾请求在很小的 K 上就会触发，队头请求接近 \(T_{def}\) 才触发。\(n\) 在分母里衰减重复排队压缩，防止一个长期等待的请求被反复过度摘要。

**可隐藏性的推导**。请求从 tool 返回后预计等待时间：

\[
$$
wait_{est} \approx \frac{\text{queue position}}{\text{recent admission rate}}
$$
\]

summary 预测时间用最近样本的 p90 per-token 值乘以本次 summary cap：

\[
$$
lat_{pred} \approx p90\left(\frac{issue\!-\!to\!-\!land}{summary\ tokens}\right) \times S_{max}
$$
\]

当 \(wait_{est} \ge lat_{pred}\) 时，summary 有较高概率在请求 admit 前落地。否则 summary 会成为队头阻塞源。论文 ablation 说明这个 gate 很重要，因为把无法隐藏的 summary 放进独立队列会让 P99 最差增加 47%。

**压缩收益的推导**。summary 输出长度未知，论文用 cap \(S_{max}\) 上界估计。要求 \(K \ge \alpha S_{max}\)，等价于保证 summary 最多占被替换 tail 的 \(1/\alpha\)。设 \(\alpha=2.5\)，新段最多是旧 tail 的 40%。论文实验里 summary 通常约为 tail 的 10%，因此默认值比较保守。

**KV block 收益的推导**。paged KV 按 block 分配，压缩必须跨过 block 边界才有 admission 价值。原 context 占用 \(\lceil C/b\rceil\) 个 block，压缩后占用 \(\lceil (C-K+S_{max})/b\rceil\) 个 block。两者差至少为 1 才发 summary。这解释了一个看似奇怪的现象：token 数减少不一定马上帮助 admit，只有释放整块 KV 才有系统收益。

## 7. 论文如何设计实验验证 claim

这里按“提出什么问题 → 设计什么实验 → 答案是什么”总结，不堆表格细节。

### 7.1 选择性摘要会不会伤害准确率和轨迹

**问题**：只压 prose、保留 tool outputs、冻结 summary 后，任务成功率和 Agent 行为轨迹是否变化。

**实验**：三个模型 Qwen3.6-35B-A3B、GLM-4.7-Flash、Gemma-4-26B-A4B；四个 benchmark：SWE-bench Verified、Terminal-Bench、DeepResearch Bench、MCPMark；比较 grow-1k、grow-4k 和 vanilla。运行两次 vanilla 估计噪声带。轨迹差异用归一化 Levenshtein distance 和 Jaccard overlap，报告相对两次 vanilla 的额外偏移 \(\Delta d\)。

**答案**：论文明确声称所有准确率差异都落在运行间噪声内；摘要后 prose 上限 4K 时最多损失 2.7 个百分点。24 个 arm-benchmark 对中，22 个轨迹偏移不显著；两个例外是 Qwen 和 GLM 的 SWE grow-1k，Agent 因摘要后重新检查状态而多调用 1.3 到 1.7 倍工具，工具顺序未变。

### 7.2 是否能提升高负载 serving 性能

**问题**：队列驱动的压缩是否比 SOTA 异步摘要更能降低尾延迟、提高吞吐。

**实验**：用校准过的 trace-driven simulator，Poisson 到达率 \(\lambda\)，每个 arm 回放同一批 1000 个 program；比较 vanilla vLLM、APEC、Slipstream、Aggron；指标为 P99 latency、throughput、batch occupancy、context 分布。

**答案**：高负载 \(\lambda=1\) 时，Aggron 吞吐为 vanilla 的 1.44×、APEC 的 1.40×、Slipstream 的 1.34×；P99 相对三者降低 33%、31%、27%。batch occupancy 从 26% 提到 39%，说明收益来自更小的 per-request KV footprint。

### 7.3 延迟收益到底来自哪里

**问题**：summary 运行时间小，为什么对端到端延迟影响这么大。

**实验**：Figure 6c 和 Figure 8d 分解 latency，看 GPU 时间和 admission wait 的比例；Table 3 统计队头阻塞时间和“稍微变小即可 admit”的比例。

**答案**：论文明确声称高负载下多数时间花在排队，队头有 75% 到 89% 的运行时间阻塞；约 5% 的阻塞时间中，压缩 prose tail 释放约 2.4K token 就能 admit 队头；如果所有等待请求都压 tail，约 46% 的阻塞时间可以多 admit 至少一个请求。

### 7.4 独立 summary 队列是否必要

**问题**：summary 放在主队列里会不会抢 Agent 的 KV 和 batch slot。

**实验**：Figure 9a 比较独立队列和共享队列；Figure 9b 测 summary 的 P50 latency 与排队占比。

**答案**：在 Qwen 上，独立队列带来 1.9% 到 8.0% 吞吐提升和 3.8% 到 8.1% P99 降低。共享队列里 summary 的 82% 到 98% 时间花在排队，没有一个 summary 能在对应 Agent 请求到达队头前落地；独立队列里 summary 7 到 33 秒落地，93% 到 100% 按时完成。

### 7.5 隐藏性 gate 是否必要

**问题**：如果 summary 本来无法隐藏，强行放到独立队列是否会伤害性能。

**实验**：Figure 9c 去掉 controller，把 4K cap 自身的 summary 从主队列移到独立队列。

**答案**：这种设置会让吞吐下降 0.2% 到 3.8%，P99 增加 1.3% 到 47%。轻负载 \(\lambda=0.05\) 最差，因为队列太短，没有时间藏 summary。这个结果直接支持 Gate 1。

### 7.6 Gate 2、Gate 3 是否真正改变决策

**问题**：收益 gate 和 block gate 在默认设置下是否过滤掉大量有效 summary。

**实验**：Figure 9d 扫描 \(\alpha\) 和 KV block size。

**答案**：默认下 summary 通常比 tail 小约 10 倍，所以两个 gate 很少改变决策。把 \(\alpha\) 放宽到 0 几乎无变化；收紧到 10 会砍掉 63% 到 66% 的 summary，但性能和 P99 变化仍低于 0.4%。block size 从 16 到 4096 token 变化时，吞吐变化最多 0.65%，P99 最多 2.6%。

### 7.7 方法的通用性和边界

**问题**：在 frontier 模型、不同 KV 成本和不同 context cap 下是否仍有效。

**实验**：Figure 10 在 T1、DeepSeek-V4-Flash、GLM-5.3、Kimi K3 上回放长轨迹，比较 120K cap 和 24K cap，并测试尾部 KV 复用和 side summarizer。

**答案**：120K cap 下 Aggron 在 T1、K3、GLM-5.3 上吞吐提升 5% 到 14%，P99 降低 7% 到 13%。DSV4 每 token KV 仅 3.4 KiB，未压缩时 HBM 只用到 68%，summary prefill 占 8% GPU 时间，Aggron 反而下降 1.7%。加入尾部 KV 复用后，四个模型都提升 5% 到 16%。side summarizer 多占一张 GPU，在 120K cap 下提升 8% 到 18%，但在 24K cap 的 DSV4 上因为等待自身 summary 而下降 26%。

### 7.8 面向 Agent 图像融合的实验设计建议

这一小节是**研究建议，论文没有做这些实验**。如果要把 Aggron 的决策角色迁移到图像融合，claim 和实验可以这样对应。

**Claim A：退化感知路由能在不损伤正常样本的前提下提升困难样本融合质量。**

设计实验：构造红外-可见光、多曝光、低光照多模态、医学多序列融合任务，人为注入噪声、模糊、错位、低光、压缩伪影。比较固定融合流水线、无退化路由的 Agent、带退化路由的 Agent。指标包括信息熵、互信息、VIF、\(Q_{abf}\)、有 GT 时的 SSIM，以及下游检测 mAP 或分割 IoU。关键观察应放在退化子集和模态冲突子集，而不是只看平均分数。

**Claim B：冻结证据和摘要可以减少融合 Agent 的轨迹漂移。**

设计实验：让 Agent 多次处理同一批图像，比较三种状态管理：完整历史、每轮重写摘要、冻结摘要加不可变证据指针。用工具调用序列的 Levenshtein/Jaccard、错误重采次数、证据引用错误率衡量漂移。论文的文本实验为这个设计提供依据，但图像场景必须额外测视觉证据引用是否丢失。

**Claim C：把融合算子和压缩算子调度到队列空档，可以降低多租户 P99。**

设计实验：用 trace-driven simulator 回放多租户图像融合请求，记录每个算子的 prefill、decode、图像工具执行时间和 GPU 占用；比较主队列、独立算子队列、带隐藏性 gate 的独立队列。指标为 P99 latency、throughput、GPU idle slot 利用率、summary 或 repair 操作的按时落地率。

**必要消融**：去掉退化路由、去掉冻结摘要、去掉 verifier 反馈、把所有算子放回主队列、去掉隐藏性 gate、把不可变证据也纳入压缩。只有这些消融都做了，才能判断收益来自 agent 决策、来自队列调度，还是来自简单的上下文缩短。

## 8. Take aways

- Agentic serving 的瓶颈常常是 KV  admit，而不是 GPU 算力。把延迟分解成 GPU time 和 queue time，是理解本文所有设计的前提。
- 压缩决策的价值不由压缩比单独决定。一个压缩请求释放多少 KV block、能否在队头出队前完成、会不会占用 Agent 的 batch slot，才决定系统收益。
- pruning 和 summarization 在 Agent 上不等价。历史重访使注意力排名不可靠；语义摘要 safer，但必须避开代码、SQL 结果、测试日志等结构化内容。
- summary 反复重写会蒸馏信息，也会破坏 prefix cache。冻结 summary、追加新段，既保信息，也保 KV prefix。
- 队列本身是一个压缩强度控制器。队尾请求可以激进压缩，队头请求应当尽量不打扰。
- 独立 summary queue 只有在 summary 能按时隐藏时才划算。否则它会把后台工作变成队头阻塞。
- 对图像融合 Agent，Aggron 最值得迁移的不是“摘要文本”本身，而是“证据分区 + 队列感知调度 + 可隐藏性 gate + 反馈校准”这套决策骨架。
- 任何压缩系统都要报告两类代价：任务准确率或轨迹变化，以及系统层面的尾延迟和吞吐。只看其中一个会误判。

## 9. 这篇论文最脆弱的假设

**最脆弱的假设是：最近一次 non-prose observation 之后的 prose tail 可以被 300 到 500 token 的摘要安全替代，而且 protected region 已覆盖所有必须逐字保留的信息。**

这个假设依赖工具分类规则。论文把文件系统、数据库、程序和测试输出判为 non-prose，把推理、工具调用、网页检索判为 prose。这个划分在 SWE-bench、Terminal-Bench、DRB、MCPMark 上有效，但边界任务很多。比如网页检索结果可能包含精确报价、版本号、引用 ID；工具调用参数可能包含关键路径；模型推理中可能出现唯一变量名。若这些内容被摘要掉，短 tail 不再安全。

第二个脆弱点是隐藏性预测。它用最近 50 次 summary 的 p90 per-token latency 估计未来。突发负载、summary 队列突然变长、某个模型 prefill 变慢，都会让预测失效。论文自己的 ablation 显示，无法隐藏的 summary 放到独立队列会让 P99 最差增加 47%。

第三个脆弱点是多模态空白。图像 token、特征图、退化图、配准矩阵并不符合 prose/non-prose 二分类。若直接迁移到图像融合，需要重新定义“可压缩语义”和“不可变证据”。

## 10. 如果我有 1 周时间，能做一个最小复现实验验证哪一点

我会优先复现**排队空档能否藏住小 summary**，而不是完整实现 Aggron。

**目标**：验证 Observation 3 和 Gate 1 的核心链条：高负载下延迟主要在排队；小 summary 放进独立队列能更快落地；没有隐藏性 gate 会伤 P99。

**环境**：一张 H100 最理想。若没有，用 7B 到 14B 模型加小 KV pool 也能验证调度趋势，但绝对数字不能和论文比较。服务端用 vLLM 0.24，客户端用 100 条 SWE-bench 或 Terminal-Bench 轨迹，固定 seed，按 Poisson 到达率回放。

**步骤**：

1. 记录 vanilla 下 \(\lambda\) 从 0.02 到 0.5 的 queue share、P50、P99、throughput。
2. 加一个最小 Session Registry，只维护 protected/non-prose 边界和 K 计数。先不做复杂工具分类，手工标注工具类型即可。
3. 实现固定 4K prose cap 的同步摘要，作为 baseline。
4. 实现独立 summary queue，但先只加 Gate 1，用最近 20 次 summary 的 p90 per-token latency 做隐藏性预测。
5. 比较四个 arm：vanilla、sync-4k、own-queue-no-gate、own-queue-with-gate。
6. 记录 summary 从 issue 到 landing 的时间、是否早于对应请求到队头、head wait on summary 的比例。

**预期信号**：如果 high-load 下 queue share 超过 60%，own-queue-with-gate 的 summary 多数能在请求到队头前落地，P99 低于 sync-4k，而 own-queue-no-gate 在轻负载时变差，那么论文核心机制成立。若 summary 落地普遍过慢，或者分类后 K 很少超过阈值，首要怀疑点是工具分类和 latency 预测，而不是双队列设计。

## 11. 如果反对它，我会怎么设计反例

**反例 1：历史证据高频回看。** 构造一个 Agent，每隔几轮就回到很久以前的文件读取或测试日志。non-prose observation 会不断扩大 protected region，K 被迫频繁归零，Aggron 退化为 vanilla。与此同时，一个带高质量 judge 的全上下文摘要方案可能仍能压缩这些旧日志。这个反例攻击的是 prose/non-prose 分区。

**反例 2：prose 中藏关键标识符。** 让 prose tail 包含低频但关键的变量名、commit hash、URL 参数或医学剂量。300 到 500 token summary 若丢失这些 token，Agent 在后续轮次失败。论文用统计噪声带判断准确率不变，但单个高风险任务上的灾难性失败可能平均值不明显。

**反例 3：突发流量击穿隐藏性预测。** 先用低负载让 p90 summary latency 变小，然后突然提高 \(\lambda\)。Gate 1 会误判 summary 可隐藏，发出大量 summary，队头被迫等待。论文 ablation 中 no-gate 的 P99 增加 47% 已经提示这个风险。

**反例 4：KV 很便宜但 prefill 很贵。** DSV4 类模型每 token KV 仅 3.4 KiB，未压缩时 HBM 利用率不高，summary prefill 占 8% GPU 时间。压缩释放的 block 价值小于 summary 成本。论文 Figure 10 已经给出这种情形，Aggron 在无尾部复用时下降 1.7%。

**反例 5：多模态证据不可摘要。** 在图像融合中，融合质量依赖精细空间证据。若系统把图像 patch 当 prose 摘要，可能丢失小目标或局部纹理；若全部当 protected，K 几乎不增长，Aggron 的触发机制失效。这说明迁移时需要算子级压缩，而不是文本级摘要。

## 12. 后续研究调研：扩展、反驳与新认知

**相关扩展**：

- [ActKV: Efficient LLM Agents through Action-Guided KV Cache Management](https://arxiv.org/abs/2609.31395) 用 action contribution 给 KV entry 打分，报告只保留 25.98% 峰值 KV 时维持 98.53% FullKV 准确率，token 和 task throughput 分别到 3.97× 和 3.58×。它说明“按动作重要性做 eviction”在某些 Agent 任务上很强，对 Aggron 的“pruning 不适合 Agent”构成条件性挑战。
- [AgentKV: Phase-Aware KV Eviction for Agentic LLMs](https://arxiv.org/abs/2609.14872) 指出 Agent 的 query 来自 think、act、tool 等不同 phase，这些 phase 占据不同 query 子空间，用最近 token 代表未来 query 会低估某些 key。它的 phase-aware buffer 在六个任务域上相对 R-KV 和 Tri-attention 平均提升 5.5 和 5.3 分，吞吐最高 1.80×。这对 Aggron 的二分法提出更细的粒度要求。
- [ReFold: Training-Free Reversible Inter-Turn Context Folding for Long-Horizon Agents](https://arxiv.org/abs/2610.07863) 强调可逆的跨轮 folding，直接针对摘要不可逆的问题。它和 Aggron 的 frozen summary 思路方向相近，但更强调可恢复性。
- [NVFP4-MLA](https://arxiv.org/abs/2611.18972)、[TriAxialKV](https://arxiv.org/abs/2605.17170) 从 KV 数值精度和存储结构入手。它们降低 KV 成本但通常不产生 summary prefill，和 Aggron 正交，也可能在 KV 便宜模型上更划算。
- [EfficientSkill](https://arxiv.org/abs/2611.19823) 从技能规则的 token 膨胀入手，说明 prompt-level 精简和 KV-level 压缩是不同层次的问题。

**图像融合侧的支撑工作**：

- [CRT-HMAR](https://arxiv.org/abs/2610.09330) 在开放任务红外-可见光融合中使用 causal requirement tracing 和层级多 agent regulation，强调从任务需求到图像级需求图的映射。
- [H2MAF](https://arxiv.org/abs/2608.24934) 在植物病害诊断中融合 CNN 决策级输出和 MLLM 语义仲裁，发现 MLLM 在 CNN 冲突子集上收益最大，但不同模型校准差异很大。
- [Agent-Wise Test-Time Normalization for Camera-Based Cooperative Perception with Corrupted Collaborators](https://arxiv.org/abs/2610.39505) 处理协作感知中损坏 collaborator 的问题，体现退化感知路由在融合系统中的必要性。

**新认知**：这个方向正在从“压缩算法谁更好”转向“压缩作为系统调度”。Aggron 的价值在于把队列状态、证据类型、执行位置和可隐藏性放进同一个决策器。ActKV 和 AgentKV 说明压缩评分可以更贴近动作和阶段；ReFold 说明可逆性可能比不可逆摘要更安全；图像融合工作说明语言模型仲裁必须 calibrated，否则质量判断会带来新错误。

## 13. 一个更 novel 的 follow-up idea

**题目：FUSE-Queue：面向多租户 Agent 图像融合的可逆证据调度器。**

**问题来源**：Aggron 只处理文本 KV，压缩对象是 prose tail；图像融合 Agent 的核心对象是图像证据、退化状态、配准参数和算子结果。图像的“压缩”如果做成不可逆文字摘要，会丢空间细节；如果全部保留，KV 和 prompt 都会爆炸。现有图像融合 agent 多数在单请求内部做决策，没有利用多租户队列的空档，也没有把下游质量反馈接到压缩 gate 里。

**核心想法**：把每次融合过程维护成一个三态证据账本。

1. **Immutable evidence**：原始图像块、退化图、配准矩阵、mask、传感器读数、失败 patch。只存指针和版本，不摘要。
2. **Frozen evidence cards**：每个工具输出对应一张短卡，记录来源、退化标签、采用算子、质量置信度、下游影响。卡片生成后不重写。
3. **Compressible narration**：自然语言推理、检索文本、复盘描述，可以按队列状态压缩。

Controller 同时维护两条队列：融合请求主队列和 operator/compaction 队列。只有当主队列队头因 KV 或显存无法 admit，且某个 repair、compaction 或 precompute 操作预测能在 admit 前完成时，才把操作塞进空档。三个 gate 改成：

- **Hideability gate**：操作完成时间小于请求预计等待时间。
- **Quality-worth gate**：预计质量增益或错误风险下降超过阈值，例如冲突集上的 \(\Delta Q\)、下游任务置信度提升、重采代价下降。
- **Evidence-release gate**：操作至少释放一个 KV block、一个图像 cache slot，或避免一次昂贵重采。

**闭环反馈**：verifier 把下游任务 loss、融合理测冲突、工具间不一致和 Agent 轨迹偏移写回 Controller。若某个 degradation bucket 上摘要后任务置信度下降，系统自动提高该 bucket 的 protected 比例，甚至触发 evidence expansion。这样压缩是可逆的：summary 只是索引，必要时能回到原始证据。

**为什么 novel**：它不是把 Aggron 直接套到图像上，而是重新定义了多模态证据的可压缩性，把退化感知路由、算子调度、可逆摘要和下游质量反馈放进同一个 serving controller。融合质量提升来源也从单一模型能力变成三部分的组合：更好的证据选择、更少的关键细节丢失、更低的拥塞导致的轨迹偏移。

**评估设计**：用红外-可见光、多曝光、低光照多模态和医学多序列融合任务；注入噪声、模糊、错位和缺失模态；比较固定流水线、异步摘要、ActKV 类 eviction、CRT-HMAR 式 agent 和 FUSE-Queue。报告下游 mAP/IoU、融合指标、轨迹偏移、证据扩展率、P99 latency、throughput 和 verifier 校准误差。关键消融是去掉退化路由、去掉可逆证据指针、去掉隐藏性 gate、去掉质量反馈。

<!-- PAPERFLOW_METRICS_JSON
{
  "task": "Online multi-tenant serving of long-horizon LLM agents under KV-cache pressure; migrated analysis to agent-driven multimodal image fusion decision making",
  "backbone": ["Qwen3.6-35B-A3B FP8", "GLM-4.7-Flash", "Gemma-4-26B-A4B", "simulated frontier models: T1", "DeepSeek-V4-Flash", "GLM-5.3", "Kimi K3", "vLLM 0.24 scheduler subclass"],
  "datasets": ["SWE-bench Verified", "Terminal-Bench", "Terminal-Bench 2.1", "Terminal-Bench Science", "DeepResearch Bench", "MCPMark", "production traces from Claude Code and Codex", "TraceLab and Azure conversational traces", "LH-TB"],
  "sota_summary": "Against Slipstream and APEC at high load, Aggron reduces P99 latency by 27% and 31%, mean latency by 11% and 15%, and raises throughput by 1.34x and 1.40x. Accuracy remains within run-to-run noise. On four frontier models, throughput improves up to 14% over 120K/24K caps and 5-17% with tail KV reuse.",
  "innovation_tags": ["queue-depth-dependent threshold", "prose-only summarization", "frozen append-only summaries", "separate summarization queue", "head-of-line stall utilization", "hideability gate", "KV-block release gate", "agentic serving", "degradation-aware fusion routing", "reversible multimodal evidence scheduling"]
}
-->

---

<!-- AI-GENERATED-NOTICE -->
!!! note "内容由 AI 生成，请审慎甄别"
    本站的论文解读、摘要速览与网站点评均由人工智能自动整理生成，仅用于学习与快速检索。
    AI 输出可能存在事实偏差、理解误差或信息滞后，涉及关键结论、数据与观点时，
    请以论文原文及官方来源为准，并自行判断其准确性。
