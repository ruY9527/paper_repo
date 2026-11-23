---
paper_uid: arxiv_2611.26480
title: "Held While Waiting: What LLM Agent Sessions Reserve on Serverless and Agent Runtimes"
venue: "arXiv (cs.PF / cs.DC / cs.SE)"
year: 2026
tier: "arXiv preprint v1；artifact README 标注投稿 ICPE 2027 Industry Track"
tldr: "LLM agent 每步等模型约 2.6–2.7 秒、算 5–40 毫秒；AgentCore 免收等待期 CPU，却给每个会话独占一个 microVM，按整段会话计费内存并占用会话配额。作者用 socket 级 mock 测出框架 CPU 随请求体线性增长，用 Little 定律加 50–400 并发直测得到每核 68–610 个环境；模拟显示 64 会话共享一个环境少占 59 倍环境、p99 只多 40 毫秒，客户端主动关闭会话少占 28 倍。开放问题是既隔离会话，又不让环境在等待期空占。"
tags: ["LLM agent", "serverless", "agent runtime", "capacity measurement", "Little's law", "isolation vs multiplexing", "performance", "measurement methodology", "image-fusion agent (reader lens, not paper content)"]
code_url: "https://github.com/MEKHALA/agent-runtime-capacity"
paper_url: "https://arxiv.org/abs/2611.26480"
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


## 0. 阅读约定：证据分级与一个必须先说清的错配

本文严格区分四类信息，正文用短标记标注：**【原文】**论文明确声称，**【文献】**论文引用或公开文档已有的结论，**【推断】**基于论文证据的合理推断，**【猜想】**尚未验证的设想。

还有一个必须先说清的错配。任务说明要求重点覆盖 Agent 在图像融合中的决策角色、多模态工具链、闭环反馈和融合质量消融。这篇论文里**没有**图像融合算法、没有算子调度器、没有退化感知路由、没有自适应提示生成、没有 PSNR/SSIM 实验，也没有任何视觉数据集。它是一篇系统性能测量论文，研究对象是 agent 会话在 serverless 与 agent runtime 上占用多少环境。把图像融合视角套上来，属于读者带来的应用透镜，不是论文内容。第 5、7 节会在完成论文本身的方法与实验拆解后，给出一段明确标注为【推断】的迁移设计，说明这些融合 agent 组件如果放进这套测量框架会怎样被约束，并指出论文对它们零证据。

---

## 1. 研究问题：agent 的稀缺资源到底是什么

### 1.1 问题从哪来

【原文】Serverless 的函数即服务模型假设请求短、CPU 密集、跨租户复用。三个设计决定随之而来：一个请求占一个执行环境，按环境存活的毫秒计费，用并发环境数限制容量。这些决定对原 workload 是合理的，但 LLM agent 的每一步恰好相反：它大部分时间阻塞在远程模型上。论文在 Amazon Bedrock AgentCore 上观察到的部署数据里，一步等模型的中位数是 2.74 秒（LangGraph）和 2.59 秒（Strands），而框架计算只有几毫秒到几十毫秒。90% 的步等待落在 1.7 到 6.5 秒之间。

【原文】AgentCore 在 2026 年做了一件看起来很对症的事：I/O 等待期间 CPU 计费归零，公开表述是 CPU scales to zero during I/O wait。但计费变化与环境占用是两件事。每个会话仍拿到专属 microVM，跨步保留；内存按整段会话计费，从 microVM ready、初始化、活跃处理、空闲期一直到会话结束；每个会话无论忙闲都占一个配额槽，默认 5,000 个活跃会话，多数区域 2,500 个。

### 1.2 论文问的四个问题

1. 【原文】一步里等待 w 和计算 c 各是多少，且怎么测准？两个量差两三个数量级，混在一起测，毫秒会被秒的抖动吞掉。
2. 【原文】一个为每个会话独占环境的平台，每完成一核实际工作要占着多少环境？
3. 【原文】有哪些修复手段，分别由谁执行？客户端关闭会话是一类，平台共享环境是另一类。
4. 【原文】是否存在既保持会话隔离、又不在等待期预留环境的方案？论文把这条留给平台建设者，作为开放问题。

### 1.3 为什么重要，价值在哪

【原文】容量先于 CPU 耗尽。1,000 个并发会话只让 1.6 到 15 个核忙，却占着 1,000 个环境和 1,000 个配额槽。看 CPU 利用率的容量规划会显示大量余量，而会话配额已经打满。定价视角也不成立：按公开价格算，hosting 的计算账单只有模型 token 账单的几个百分点；免收等待期 CPU 让这笔更小的账单再降一点，环境占用一点没少。

【原文】论文的贡献是一套可复现的测量仪器、一个用 Little 定律表达的容量比、一个客户端就能拿到的 28 倍修复、一个需要平台改动的 59 倍修复，以及对九个平台文档的系统整理。对图像融合读者来说，价值是间接的：如果你的融合 agent 每一步也要调多模态模型并等待，这套仪器告诉你等待会怎样变成环境占用，但论文不告诉你融合质量怎么提升。

---

## 2. 之前解决过吗，不足在哪

【文献】serverless 为 I/O 阻塞函数预留容量，早有结论。论文引用 MXFaaS 指出函数执行大部分时间阻塞在同步等待上，并引用 concurrency-informed orchestration 讨论并发请求如何共享容器。Hellerstein 等人与 Berkeley view 早就 catalogued 了 serverless 在哪些数据密集场景下适配差。这些是论文当作前提接受的工作。

【文献】平台侧也有现成机制。Cloud Run 和 Cloudflare Workers 多年默认共享环境；Lambda 在 2025 和 2026 年通过 Managed Instances 与 web functions 加入共享；Lambda MicroVM 可以挂起；durable functions 能在等待时释放并发槽；AgentCore 能让 CPU 在 I/O wait 归零。

【原文】缺口在三个地方。第一，没有人在这批专门为 agent 建的平台上去测 agent case：一步里到底多少是等待、每会话运行时在等待期占着什么、客户能做什么。第二，这些机制各自解决的是成本或启动时间，不是预留本身。挂起的 MicroVM 只付快照存储，但仍占内存配额，而且挂起只发生在无流量的配置间隔，不会在一次请求中间的模型等待时发生；durable functions 释放的是 timer 和 callback 的等待，按论文对文档的阅读，step 内部的模型调用仍然占槽。第三，agent runtime 与通用 runtime 形成清晰分野：AWS 和 Microsoft 的 agent runtime 一会话一环境，Google 的 Vertex AI Agent Engine 只在 agent 代码是异步时才允许一个实例接多个并发请求，而默认共享环境的 runtime 全是通用用途。 surveyed nine platforms 里没有一个同时提供按会话隔离和按环境共享。

【推断】之前工作不足的共同原因是抽象层级：它们把一次 invocation 当作工作单元，而 agent 的 invocation 主要是等待单元。把单元从 request 换成 session，计费和容量的语义就跟着变了，这恰好是 2026 年这批 agent runtime 刚做出来的变化，测量自然滞后。

---

## 3. 作者可能的思考路径：只用论文之前的材料重建

这一段是【推断】，论文没有自述思考过程。我只用论文之前就成立的事实和失败模式来推演。

**第一步，从一个公开声明的不协调开始。** AgentCore 宣布 I/O wait 时 CPU 归零。任何有运维直觉的人第一反应是等待成本解决了。但如果你读过 session id 的语义，就知道会话被 pin 到同一个环境直到 close、idle timeout 或 max lifetime。计费归零是账本变化，环境 pinning 是资源变化。两者正交。这个不协调足以支撑整篇论文的问题：多花的钱少了，但占着的东西没少。

**第二步，从 serverless 第一性原理推容量。** 如果每个环境在任意时刻只有一个会话，而会话 99% 时间在等网络，那么 N 个环境里同一时刻在跑 CPU 的只有 N × c/(w+c)。只要 w 是秒、c 是毫秒，这个比例就极小。不需要新算法，Little 定律直接给出结论。这个结论在看到 w 和 c 的具体数字之前就已经能想到，数字只决定倍数是 70 还是 600。

**第三步，三个测不准的失败模式都是可以预先推理出来的。** 想测框架每步 CPU，最省事的办法是把模型对象换成 stub。但 agent 每步把整个增长中的对话转成 provider wire format、序列化、签名、解析回复，这些正是随对话增长的工作；stub 恰好把这部分跳掉，于是 CPU 看起来是平的。第二种办法是在部署的 agent 里给“模型调用”计时，但计时窗口里包含客户端自己的序列化与解析，等于把框架 CPU 记成模型时间。第三种是把 step 背靠背连跑，省掉网络等待，可一次等了几秒之后，处理器的时钟可能降了、缓存冷了，同一个 step 会贵 1.9 到 4.7 倍。三个错误都有一个共同特征：结果看起来合理，数字偏低。

**第四步，从失败模式反推正确仪器。** 保留真正的模型客户端，只伪造它下面的网络层。AWS SDK 的 before-send 事件在请求完全序列化、签名、准备上线时触发；handler 直接返回 Bedrock wire format 的脚本化回复，于是请求构建、签名、解析全部执行并被计入，只有 socket 缺席。每次 sweep 前检查序列化请求体确实随对话增长，否则中止。这是整套方法的核心直觉。

**第五步，从平台语义找两把扳手。** 客户端可以在对话结束时显式 close session，把环境持有时间从 933 秒压回 33 秒。平台可以让一个环境服务多个并发会话，而这类 workload 超过 98% 时间在等待，CPU 争用很小。两把扳手一个只需客户端，一个需要平台。剩下的问题是为什么不能两者兼得：agent 执行模型选择的工具和代码，按会话隔离有真实价值。论文没有把这个价值当成错误，而是给它定价，这个姿态决定了论文的定位是测量研究，不是优化论文。

---

## 4. Intuition：占着车位，不发动引擎

把会话想成一辆占着车位的车。引擎绝大多数时间不转：一步里计算只有 5 到 40 毫秒，等待是 2.6 到 2.7 秒。对话结束后，如果司机不显式开走，车位还要再占 15 分钟。收不收油钱（CPU 计费）和车位是不是被占（环境配额与内存计费）是两套账。平台的容量表按车位数算，agent 的实际需求按引擎转动时间算，两者差两三个数量级。

论文的整个方法就是把这两本账分别测出来，再算它们的比：等待 w 用真实调用校准，计算 c 用 socket mock 隔离，比值 (w+c)/c 就是每核工作要占的环境数。修复也顺着这个模型分成两半：让车更快离开车位，或者让多辆车共用一个车位。前者客户端就能做，后者要平台改规则，而平台不愿意改的理由是车厢里装着模型选出来的工具和代码，隔离有安全意义。

---

## 5. 具体方法：仪器、一个真实 step 的 pipeline、以及图像融合的诚实映射

### 5.1 五件仪器

【原文】表 1 列出五件仪器，前四件各隔离一个量，第五件在部署里观察两者但不干净。

1. **Transport mock / LangGraph**：socket 伪造，测 c，Apple M5 与 Intel x86 各 4,800 步。
2. **Transport mock / Strands**：socket 伪造，测 c，Intel x86，4,800 步。
3. **Transport mock on platform**：两个框架分别放进 AgentCore 与 Lambda，4,800 步每配置。
4. **Calibrated latency**：真实调用，测 w，50 次模型调用加 30 次工具调用。
5. **Deployed agents**：真实部署，观察 w 和部分 c，3,549 个 warm step、384 个会话。

【原文】时钟的选择跟着框架走。LangGraph 的模型路径在调用线程上，工具通过 worker 线程池调度，所以读 `time.thread_time` 并显式加上 worker 的 CPU。Strands 把 SDK 调用交给 worker 线程、把回复事件投回 event loop，一次模型调用跨两个线程，per-thread 会漏，所以在 Strands 自己的 before/after-model-call 钩子里读 `time.process_time`；它的 loop 严格顺序执行，窗口里没有别的任务。所有 run 都同步执行，因为 asyncio 里 coroutine 挂起会把线程让出去，per-thread 归属失去意义。

### 5.2 一个真实的 step 走一遍

【原文】以 LangGraph 在 AgentCore Graviton3 上、40 步循环中的第 20 步为例。输入是一段已经增长到约 10 KB 的对话历史。框架把历史转成 Bedrock 消息格式，序列化、签名，AWS SDK 触发 before-send handler。handler 不把字节写到 socket，而是返回一个脚本化的 tool call 回复，格式是 Bedrock 自己的 wire format。框架解析回复、更新自己的 state，然后进入工具节点：用 Pydantic 校验模型给出的参数，在线程池里跑这个工具，把结果追加回历史。整段路径上没有一次真实网络往返，但除 socket 外的每个字节操作都发生了。

harness 在每轮 sweep 前检查请求体确实从第一步的 1.1 KB 增长到第四十步的 19.6 KB（LangGraph 19,617 字节，Strands 19,627 字节），否则中止。一次 sweep 是 120 run × 40 步 = 4,800 步。LangGraph 的 120 run 分成三组 checkpointer 配置：none、in-memory、SQLite；Strands 没有对应组件，只测默认不持久化的一组。

【原文】模型路径的 CPU 用 `cpu = c_fixed + c_KB × KB` 拟合。AgentCore G3 上 LangGraph 的拟合是 1.35 ms + 0.220 ms/KB，R² = 0.96；把 10 KB 代进去，这一步模型路径约 3.55 ms，再加工具 dispatch 的 0.73 ms。到 19.6 KB 时约 5.66 ms。Strands 在同一处理器上是 1.41 + 0.324 ms/KB，工具 0.30 ms。形式迁移，常数不迁移：同一份 LangGraph 代码在 x86 桌面每 KB 成本是 M5 的两倍多，在 AgentCore 接近三倍；AgentCore 自己还把 Strands 会话放到了两代 Graviton 上，老一代每 KB 贵 1.4 倍。

【原文】部署端用另一条路径交叉验证。τ²-bench retail 上的 384 个会话、3,549 个 warm step，每个 step 记录 server time、model time 和差值。model time 是围着 `litellm.completion` 或 Strands 的模型钩子量的，包含客户端自己的序列化。所以差值（论文称为 overhead）只覆盖模型客户端之外的框架与 server 工作，4.48 ms（LangGraph on AgentCore）和 4.49 ms（Strands）。把这当作下界，再把同一框架、同一平台的 CPU 拟合外推到部署请求大小（中位数 6.9k 输入 token，按 3 到 5 字节每 token 算 20 到 34 KB），得到上界 13.2 ms 和 20.3 ms。再乘上等待后 CPU 的 2.2 倍因子，得到容量计算用的 23.4 ms 和 38.9 ms。

### 5.3 从毫秒到环境数

【原文】一步的墙钟时间是 w + c，单个独占环境在 CPU 上的时间占比是 c/(w+c)。N 个环境平均让 N·c/(w+c) 个核忙，等价于每核工作占用 (w+c)/c 个环境。把 LangGraph 的中位等待 2,740 ms 和下界 4.5 ms 代进去：2,740/4.5 ≈ 610 个环境每核；1,000 个会话让 1,000 × 4.5/2,744.5 ≈ 1.6 个核忙。

### 5.4  remedy 的模拟设置

【原文】离散事件模拟回放部署会话：每个模拟会话从 384 个真实会话里抽步数（中位 9，范围 7 到 19），每步等待从 1,094 次 LangGraph 部署模型调用里抽（中位 2.74 秒），每步 CPU 在一次 run 内固定为 4.5、11.7、20.3 或 38.9 ms 之一。新会话按泊松过程到达，约每秒 30 个，会话平均 33 秒，于是任意时刻约 1,000 个在进行中。每次 run 40 分钟，丢掉前 20 分钟，让 15 分钟 idle timeout 的效果先积累起来。环境计数与 Little 定律的预测相差在 1% 以内。

隔离策略两种：客户端在对话结束时 close，或者放着不管让平台在 15 分钟 idle timeout 后回收。共享策略是一个 2 vCPU 的环境容纳最多 k 个会话，新会话进第一个有空位的环境，没有空位才开新环境；当同时需要 CPU 的步数超过 vCPU 数，按到达顺序排队，共享的代价表现为 step 的额外延迟。

### 5.5 映射到图像融合 agent：一段明确标注的推断

【推断，论文零证据】下面这段不是论文内容。它说明如果把一个图像融合 agent 放进上述仪器，论文测过的量会怎样约束它的工程决策。

先看决策角色。动态算子调度和退化感知路由，在这套模型里都表现为一次或多次模型调用加上工具调用：agent 拿到退化的多模态输入，调用模型判断退化类型（雾、弱光、运动模糊），模型返回要执行的算子链，agent 逐步执行。自适应提示生成则是把上一轮的质量评估结果写回对话，让下一轮提示包含更具体的约束。这三类决策共享同一个物理事实：每次决策都触发一次 w ≈ 2.7 秒的等待，并让会话的环境在整个等待期保持独占。一个做 8 步决策-执行循环的融合 agent，光等待就有 20 秒量级，而它真正花在本地算子调度、参数校验、结果拼接上的 CPU 是几十毫秒量级。

再看多模态工具链。论文测的请求体只到 19.6 KB，对应 5k 到 10k 纯文本 token。图像输入会把请求体推到远超这个范围，可能是数百 KB 到数 MB。论文的拟合形式是线性的，常数跨硬件差五倍以上；把它外推到多模态 payload 属于【猜想】。合理的做法是照论文的方法重做一次 sweep：保留真实的多模态模型客户端，只 mock socket，让脚本化回复携带与真实融合 agent 相同大小的工具输出，重新拟合 c(KB)。如果 base64 编码、图像预处理或分块逻辑引入超线性项，论文关于“上下文越长每核环境数越少”的方向性结论仍然成立，但斜率不再适用。

闭环反馈机制的代价可以直接算。每一轮质量评估如果调用一次模型，就多一次 w；如果评估工具是本地指标计算，就多一次工具 dispatch（论文里 LangGraph 在 AgentCore G3 上是 0.73 ms）。闭环轮数乘以 w，几乎线性地增加会话持有时间。论文的客户端修复在这里变成：融合任务一旦给出最终图像，立刻 close session，否则 15 分钟 idle timeout 会把 33 秒的会话拉成 933 秒。

融合质量提升来源在这篇论文里没有对应物。PSNR、SSIM、LPIPS、边缘保持度、消融实验，论文一个都没有。它的“消融”是系统层面的：stub model 对 transport mock、背靠背对带真实等待、隔离对共享、close 对 timeout。把这些当成融合质量消融的替代品是错误类比。一个诚实的融合迁移实验必须同时报两组数：质量指标证明算子决策有效，环境数和 p99 延迟证明这套 agent 在平台上跑得动。论文只提供第二组数的测量方法。

---

## 6. 核心数学推导：从零开始，不需要统计背景

### 6.1 一步的时间模型

【原文 + 推导】一步分两段：阻塞等待 w，本地计算 c。总时间 T = w + c。部署数据里 w 的中位数是 2.59 到 2.74 秒，c 的估计区间是 4.5 到 38.9 毫秒。先统一单位：w = 2,740 ms，c = 4.5 ms 时，T = 2,744.5 ms。计算占比 c/T = 4.5/2,744.5 = 0.00164，即 0.16%。高估计 c = 38.9 ms、w = 2,590 ms 时，占比 38.9/2,590 = 1.5%。论文结论里写的 0.2% 到 1.5% 就是这个区间。

### 6.2 CPU 拟合并不是玄学

【原文 + 推导】框架每步重复做两件事。一件是模型路径：把整个消息历史转成 provider 格式、序列化、签名、解析回复、更新 state。历史每步追加消息，所以这件事的成本随请求体大小 KB 增长。另一件是工具 dispatch：校验参数、跑工具、追加结果，每步处理一个调用，与历史长度无关。于是模型路径写成：

$$
`c_model(KB) = c_fixed + c_KB × KB`
$$

这就是一条直线。c_fixed 是每步固定开销（构建消息对象、进入调用路径），c_KB 是每 KB 的序列化与解析成本。R² 在 0.96 到 0.98 之间，说明直线解释了几乎全部变化。代入 AgentCore G3 的 LangGraph 拟合：c_fixed = 1.35 ms，c_KB = 0.220 ms/KB，请求 19.6 KB 时 c_model = 1.35 + 0.220 × 19.6 = 5.662 ms。工具 dispatch 再加 0.73 ms，单步模型路径加工具约 6.4 ms，对比 w = 2,740 ms。

【原文】部署请求的 bracket 是同一条直线的应用。20 到 34 KB 代入 LangGraph AgentCore 拟合：1.35 + 0.220 × 34 = 8.83 ms；加上下界 4.5 ms 得 13.33 ms，论文报告 13.2 ms。Strands 把两代处理器合起来拟合为 1.73 + 0.41 ms/KB；34 KB 时 15.67 ms，加 4.5 得 20.17 ms，论文报告 20.3 ms。

【原文】等待后 CPU 更高的因子来自直接测量：一个 LangGraph 会话单独在进程里、带部署等待时，每步 14.8 ms；同样 agent 背靠背跑是 6.8 ms；14.8/6.8 = 2.18，论文取 2.2。于是高估计写成 `4.5 + 2.2 × (13.2 − 4.5) = 23.64 ms`（论文表 4 写 23.4），Strands 是 `4.5 + 2.2 × (20.3 − 4.5) = 39.26 ms`（论文写 38.9）。论文没有把 Strands 自己的更大因子 27/6.4 ≈ 4.2 用进去，因为直接测量的 Strands 每步最多 31 ms，已经低于 38.9 ms 的高估计。

### 6.3 Little 定律，一句话版本

Little 定律在排队论里的说法是：系统里的平均数量 = 到达率 × 平均停留时间。这里不需要到达率。换一个等价说法：如果你有 N 个环境，每个环境在任意随机时刻有 p 的概率正在用 CPU，那么平均忙核数就是 N × p。p 等于一个环境在一步里花在 CPU 上的时间比例，也就是 c/(w+c)。于是：

$$
`busy_cores = N × c / (w + c)`
$$

$$
`environments_per_busy_core = (w + c) / c ≈ w / c`（当 c 远小于 w）
$$

代入四个案例（w 用部署中位等待，c 用表 4 的估计）：

- LangGraph 低估计：c = 4.5 ms，2,740/4.5 = 609 ≈ 610；1,000 个会话忙 1,000 × 4.5/2,744.5 = 1.64 核。
- LangGraph 高估计：c = 23.4 ms，2,740/23.4 = 117 ≈ 120；1,000 × 23.4/2,763.4 = 8.47 核。
- Strands 低估计：2,590/4.5 = 576 ≈ 580；1.7 核。
- Strands 高估计：2,590/38.9 = 66.6 ≈ 68；15 核。

【原文】直接测量用来校验公式。在 x86 桌面上同时跑 50、100、200、400 个会话，分散在五个进程，每个 transport-mock agent 的模型调用阻塞一个从部署调用里抽出的等待。五分钟窗口内 scaled to 1,000 sessions：LangGraph 忙 3.8 到 5.0 核，Strands 忙 4.8 到 9.3 核，对应 200 到 260 和 110 到 210 个环境每核，都落在计算区间内。

### 6.4 两个修复的算术

【原文】客户端 close：会话持有时间从 33 秒变成 33 秒；不 close 则变成 33 + 900 = 933 秒（15 分钟 idle timeout）。933/33 ≈ 28.3。模拟里对应的环境数是 1,008 对 28,432，比值 28.2。换算成配额吞吐：5,000 槽 ÷ 33 秒 ≈ 每秒 151 个新对话；5,000 ÷ 933 秒 ≈ 每秒 5.4 个。

【原文】平台共享：k = 64 时，1,008/64 ≈ 15.75，模拟得到 17 个环境，减少 59 倍。p99 额外延迟最多 40 ms，而中位模型等待是 2,741 ms，40/2,741 = 1.46%，与论文说的至多 1.5% 一致。k = 256 时环境降到 5 个，20.3 ms CPU 下 vCPU 已 63% 忙、p99 多 79 ms；38.9 ms CPU 下请求超过两个 vCPU 的供给，step 排队数秒，需要第六个环境。

【原文】内存那组数也纯算术。假设每环境 0.5 GB、每会话 10 MB：隔离且 close 时 1,008 × 0.5 + 1,000 × 0.01 = 504 + 10 = 514 GB；k = 64 时 17 × 0.5 + 10 = 18.5 GB。论文明确说 0.5 GB 是假设，环境计数不依赖这个假设。

### 6.5 为什么上下文变长，比值反而变小

【原文】等待随输出长度走，不随输入长度走。回归里每个输出 token 加 19.3 到 19.5 ms，每千输入 token 的系数是 −15 到 −51 ms（无显著正向贡献）。原因是模型先把整个输入并行读一遍（prefill），再逐 token 写答案（decode），慢的是 decode。框架 CPU 则随请求线性增长。于是 w 近似不变、c 上升，(w+c)/c 下降。论文外推：50k token 上下文约 26 到 47 个环境每核，250k token 约 6 到 11。这是远超观测范围（5k 到 10k token）的外推，而且把等待固定在短上下文中位，真实 250k prefill 会拉长等待，所以方向可信、具体数字不可信。

---

## 7. 实验验证：问题 → 实验 → 答案

### 7.1 问题一：框架每步 CPU 到底多少，怎么测才不偏低

【原文】设计：五件仪器交叉；socket mock 保留模型客户端，只伪造网络；对照三种错误做法（replace model with stub、围着模型调用计时、背靠背连跑）；每种配置 4,800 步，跨五种机器/平台环境。

答案：正确仪器下模型路径 CPU 对请求体线性，六个配置 R² 0.96 到 0.98，但常数跨硬件差五倍以上。stub 让 CPU 看起来平坦，因为它跳过了随对话增长的那部分工作。围着模型调用计时把客户端序列化记成模型时间，论文估计这藏掉了部署数据里大部分框架 CPU。带真实等待的 step 比背靠背贵 1.9 到 4.7 倍；关掉 GC 后 LangGraph 仍 16.5 ms，说明主因不是垃圾回收，论文推测是降频和冷缓存，未分离验证。

### 7.2 问题二：等待由什么决定

【原文】设计：对 3,549 个部署 step 的等待时间同时回归输入和输出 token 数，分三种部署配置；另做 50 次真实 Bedrock 调用作校准，`max_tokens` 在 48 到 1,536 之间对数均匀抽样。

答案：输出 token 每增加一个是 19.3 到 19.5 ms，输入 token 无显著贡献。部署中位等待 2.74 s（LangGraph）和 2.59 s（Strands）；校准调用中位 4.23 s，工具调用 0.97 s。校准与部署的差距主要是每调用固定延迟 3.5 s 对 0.9 到 1.2 s，论文说 50 次调用无法区分模型、客户端位置、日期三个原因。

### 7.3 问题三：每核工作要占多少环境

【原文】设计：Little 定律计算四种 c 估计；再用 50 到 400 并发会话在同一台机器上直测忙核数，等待从部署调用抽样。

答案：计算区间 68 到 610 个环境每核；直测 110 到 260，落在区间内。少数几个细节值得记住：单个 LangGraph 会话在带等待时每步 14.8 ms 而背靠背 6.8 ms；Strands 单会话 27 ms，随并发增加下降到 16 到 31 ms；这些额外 CPU 不是并发造成的。

### 7.4 问题四：平台在等待期到底计费和占用什么

【原文】设计：2026 年 10 月 27 日整理九个平台的公开文档，分计费、持有、默认限制、每环境并发数四栏。

答案：agent runtime 按会话独占环境（AgentCore 专属 microVM、Foundry 专属 sandbox 到 15 分钟 idle timeout）；共享环境的是通用 runtime（Lambda web functions、Managed Instances、Cloud Run、Cloudflare Workers）；Vertex AI Agent Engine 是部分例外，默认 9 并发但要求异步代码。AgentCore 的内存按整段会话计费，10 分钟会话的官方价格例子是 60 秒 CPU 加 600 秒内存。挂起只省成本，不释放配额槽。

### 7.5 问题五：两个修复各值多少

【原文】设计：离散事件模拟回放部署工作负载，对比隔离+close、隔离+timeout、共享 k ∈ {16, 64, 256}，四个 CPU 水平；Little 定律校验在 1% 内。

答案：隔离+close 1,008 个环境；隔离+timeout 28,432 个（28 倍）；共享 k=16 是 65 个（+8 ms p99），k=64 是 17 个（59 倍，+40 ms p99），k=256 是 5 个（+3 到 79 ms，38.9 ms CPU 时过载）。论文明确说模拟给隔离的待遇是慷慨的：隔离会话独占整个 vCPU，而且没有 step 间思考时间；有人类暂停时会话更长，idle timeout 的倍数会更小。

### 7.6 关于图像融合的实验：论文里没有，以下是迁移设计【推断】

论文没有质量指标，没有视觉数据集，没有算子消融。如果要把这套方法用在图像融合 agent 上，一个诚实的设计至少要做两层实验，而且两层都不能互相替代。

第一层复刻论文的系统问题：把融合 agent 的每步请求体、等待、工具调用记录进同一套 tracer，重做 transport-mock sweep，报出 c_fixed 与 c_KB；用真实多模态调用校准 w；按 (w+c)/c 算环境每核；回放真实流量比较 close、timeout、共享 k 三策略。这里的指标是环境数、忙核数、p99 额外延迟、配额吞吐。

第二层才是融合本身：输入多退化图像（例如雾加弱光），对比固定算子链、退化感知路由、路由加质量反馈闭环三种策略，报 PSNR、SSIM、LPIPS 和人工评分；消融分别去掉路由、去掉反馈、换掉提示生成模块。关键是要把第一层的系统数与第二层的质量数并列报告。一个质量更高但需要 24 步闭环的 agent，可能把环境占用推高到不可接受的程度，这恰好是论文方法能揭示、而融合论文通常不报的维度。

【推断】这里最容易被做错的仍然是测量：如果用 stub 替换多模态模型，图像 token 的序列化成本会被跳掉，融合 agent 的 c 会被严重低估；如果只在部署里围着模型调用计时，客户端的图像编码会被记成模型等待，w 和 c 同时错。论文的三个陷阱在视觉场景下更严重，因为 payload 更大。

---

## 8. Take aways

1. 【原文】agent 的瓶颈是环境数，不是 CPU。1,000 个会话只让 1.6 到 15 核忙，却占 1,000 个环境和配额槽。
2. 【原文】免收等待期 CPU 只改账单，不改占用。AgentCore 仍按整段会话计内存，仍每会话占一个配额槽。
3. 【原文】最便宜的修复在客户端：对话结束就 close session，33 秒对 933 秒，28 倍环境数。
4. 【原文】第二个修复在平台：64 会话共享一个 2 vCPU 环境，环境少 59 倍，p99 每步只多 40 ms，相对 2.7 s 的模型等待是 1.5%。
5. 【原文】测框架 CPU 要伪造网络，不要伪造模型；stub 会跳掉随对话增长的那部分工作。
6. 【原文】带真实等待的 step 比背靠背贵 1.9 到 4.7 倍，所以背靠背 benchmark 系统性偏低。
7. 【原文】等待由输出长度决定，输入长度几乎不影响；框架 CPU 则由整个对话长度决定。这个反向关系是容量比随上下文增长而收窄的原因。
8. 【原文】按会话隔离有真实理由：agent 执行模型选出的工具和代码。论文给它定价，不主张取消它。九个平台里没有一个是既隔离会话又共享环境的。

---

## 9. 最脆弱的假设

【原文】最脆弱的一处是部署 CPU 不是测出来的，是 bracket 出来的。上界可能把两件仪器都覆盖的工作重复计算；表 4 的整个比值按 w/c 缩放，c 错两倍，610 就变成 300 或 1,200。论文自己也把 construct validity 列在第一位。

紧随其后的是等待后 CPU 因子。1.9 到 4.7 倍只在一台 x86 桌面上测过，没有分离降频和冷缓存的原因，也没有在云平台上测；把 2.2 这个 LangGraph 因子同时套到 Strands（它自己的因子约 4.2）是一处明确的近似，论文用直接测量的 31 ms 上界为它兜底。

第三是外部有效性。只有一个 workload（τ²-bench retail），而且工具由 benchmark 执行，部署 step 里没有工具等待；一个自己跑工具的 agent 只会更阻塞。一个模型家族、两个框架、上下文只到 10k token，脚本化回复只有短答案，所以解析成本只代表短回复。CPU 常数跨六种处理器差五倍以上，只有线性形式被声称可迁移。

第四是模拟假设。2 vCPU 共享环境、泊松到达、无 step 间思考时间、隔离会话独占整颗 vCPU、0.5 GB 每环境的内存足迹。这些假设逐个放松，28 倍和 59 倍都会变。特别是有人类暂停时，持有时间变长，idle timeout 的倍数从 28 缩到接近 1。

第五是视角限制。所有倍数计的是客户持有的环境、配额和计费内存，不是 provider 的物理成本；provider 可以超卖空闲 microVM，论文从外部看不到。作者受雇于 AWS，平台事实全部来自 2026 年 10 月 27 日的公开文档，会随时间变化。

【推断】对图像融合读者还要加一条：论文对多模态 payload、GPU 工具、图像预处理流水线完全没有证据。把它的线性拟合外推到 MB 级请求，或者把 40 ms 的 p99 延迟预算当成融合 agent 的通用预算，都超出了论文能支撑的范围。

---

## 10. 一周最小复现

【原文 + 推断】artifact 在 [github.com/MEKHALA/agent-runtime-capacity](https://github.com/MEKHALA/agent-runtime-capacity)，Apache 2.0，README 明确说除两个可选云端步骤外全部离线运行，benchmark 不调用模型。

- **第 1 天**：clone 仓库，装 Python 3.12+ 和 `cloud/requirements.txt`，跑 `python3 tests/test_agentprof.py`（19 个测试，约一秒），读懂 `scripts/bedrock_transport_mock.py` 的 before-send handler。重点确认请求体随对话增长这个不变量。
- **第 2 天**：跑 `scripts/sensitivity.py`（秒级）。它读仓库自带数据，直接产出第 4.4 节 bracket、第 5 节容量表、Figure 1 和 scenario 数字。这是验证核心 claim 最快的一条路：68 到 610 个环境每核这组数是否成立。
- **第 3 天**：跑 `scripts/simulate_remedy.py` 再跑 `scripts/fig_remedy_alt.py`（约 8 分钟），复现 Figure 3。检查 1,008、28,432、65、17、5 这五根柱子与 p99 延迟标注。
- **第 4 天**：在自己机器上跑 `scripts/measure_framework_cpu.py --steps 40 --replicates 40 --out ...` 和 `scripts/measure_strands_cpu.py --replicates 120`（约 15 分钟）。预期斜率不同、线性形式相同。若你的硬件给出非线性，那本身就是对论文迁移性的反例。
- **第 5 天**：跑 `scripts/fig_session_timeline_v2.py` 复现 Figure 2，读 `results/PLATFORMS.md` 核对九个平台的计费与持有栏。
- **第 6–7 天（可选）**：有 AWS 账号再跑云端部署（README 说花费低于 2 美元）；`validate_capacity.py` 各框架约 35 分钟、占五个核，用来复现等待后 CPU 因子。

这一周能验证的是：容量比的数量级、两个修复的倍数、以及 socket mock 能否稳定产出线性 CPU 曲线。它不能验证部署 CPU 的 bracket 是否准确，因为那需要重新采集部署数据。如果你带图像融合场景来，合理的加餐是把脚本化回复换成携带图像工具输出的 payload，重新拟合 c(KB)，看线性是否还成立；这一步属于【推断】，不在原 artifact 的验证范围内。

---

## 11. 如果反对它，怎么设计反例

**攻击 CPU bracket。**【推断】部署 CPU 上界可能重复计数，也可能漏掉 SDK before-send 之后的工作（流式解析、重试、异步回调后的处理）。反例实验：在真实 AgentCore 会话里用 perf/eBPF 级计数逐 step 采 CPU 周期，与 4.5–38.9 ms 的 bracket 对比。如果实测 c 系统性高于 38.9 ms，表 4 的 68 个环境每核上界会被推得更低，论文的“tens to hundreds”描述范围要改写。

**攻击等待后因子。**【推断】1.9 到 4.7 倍可能只是这台桌面降频和冷缓存的产物。在云上把 vCPU 钉住、预热缓存后重测，若因子接近 1，高估计塌回 13–20 ms，容量比变成 130 到 600，59 倍与 28 倍的叙事仍成立但数字要全线调整。

**攻击共享的安全性。**【原文 + 推断】论文自己承认共享会话共享内存和失败，模型选出的工具或代码可能需要更强隔离。一篇反论文可以构造真实攻击面：一个会话的工具触发进程崩溃或内存泄露，量化对同环境其他会话的爆炸半径。如果融合 agent 的算子涉及原生库和 GPU 状态，风险更大。这时 40 ms 的 p99 收益在某些合规场景里不足以抵消风险。

**攻击工作负载外推。**【推断】加 60 秒人类思考时间再回放，会话持有时间从 33 秒变成约 90 秒，idle timeout 倍数从 28 掉到约 10；如果是长时间自主运行的 agent（think time 数分钟），倍数接近 1，客户端 close 这个“最大可客户控制因子”就不再大。

**攻击容量前提。**【推断】provider 超卖空闲 microVM，客户侧“环境数”未必等于 provider 侧的真实容量约束；配额是账户级、可提升的。从外部很难证伪，但可以通过大账号实测提升配额后是否真的能持续跑更多并发会话来间接检验。

**攻击多模态外推。**【猜想】图像输入让请求体从 KB 级跳到 MB 级，编码与分块可能引入超线性 CPU，论文的 `c_fixed + c_KB × KB` 形式失效；或者融合 agent 的主要等待从模型转到 GPU 工具，`w` 不再由输出 token 决定。两者中任一成立，图像融合场景下的容量比都要重新推导。

---

## 12. 后续研究调研结果（调用搜索工具所得）

我实际查询了 arXiv、OpenAlex、Semantic Scholar、GitHub raw 和几个通用搜索入口。结果如下，时间点是本次查询：

- [arXiv 摘要页](https://arxiv.org/abs/2611.26480)显示只有 v1，提交于 2026 年 11 月 19 日，12 页、3 图，分类 cs.PF / cs.DC / cs.SE，DOI 10.48550/arXiv.2611.26480。没有后续版本。
- [OpenAlex 工作记录](https://api.openalex.org/works/doi:10.48550/arXiv.2611.26480)给出 created_date 2026-11-21，`cited_by_count` 为 0；[引用查询](https://api.openalex.org/works?filter=cites:W7237063363)返回 count 0。Semantic Scholar API 返回 429 限流；DuckDuckGo 返回人机验证；Google 发生跨Origin跳转，Bing 重定向到 cn.bing.com。因此“零引用”只能说在这些可查来源里未发现，不能说不存在。
- [artifact README](https://raw.githubusercontent.com/MEKHALA/agent-runtime-capacity/main/README.md)透露一条 arXiv 页面没有的信息：该工作标注为投稿 ICPE 2027 Industry Track。README 还列出了完整复现命令，并说明 `CALIBRATION-NOTES.md` 记录了那个给出错误答案的 model-object stub。
- 【文献，来自论文的 related work 与 Table 6，我没有逐篇独立核验】相邻结论包括：MXFaaS 与并发感知编排确立了 I/O 阻塞函数预留容量的结论；snapshot/restore 与轻量隔离主要解决启动成本和密度；stateful serverless（Cloudburst、Boki、Beldi）提供持久状态与 exactly-once 语义，但当前粒度不适合 agent 的 append-only 对话；Unum 等工作把长控制流外置。

**新的认知**：这篇论文的可证伪单元不是某个算法，而是那套 harness 和它产出的几个数字。它刚发布、零引用、带完整 artifact，所以合理的跟进方式不是引用后争论，而是拿它去测新 workload（自主 agent、带工具等待的 agent、多模态与图像融合 agent），看线性形式、等待因子和两个修复倍数是否存活。论文自己列出的开放问题——在不给每个会话预留环境的前提下保持隔离——在本次查到的来源里仍未被解决，九个平台中也没有一个同时提供两种能力。

---

## 13. Follow-up idea：IAFU，用 agent 自己的意图信号驱动会话折叠与展开

【猜想，我的想法，论文与后续文献均未提供】

**起点是两个缺陷的交叉。** 论文证明隔离的代价是 59 倍环境，同时指出没有平台把“正在远程调用上阻塞的 in-flight 会话数”暴露给调度器。Table 6 里 snapshot/restore 只切启动、不切等待；per-instance concurrency 能去掉预留，但 agent runtime 不用它。平台看不到 agent 什么时候安全，agent 却知道自己下一步要做什么。让 agent 把这件事说出来，就能把盲目的共享变成有条件的折叠。

**机制。** 在 step 边界，agent 向 runtime 发两类带类型的意图：

- `quiescent(model_wait, route, confidence, capability_set)`：即将进入远程模型调用，声明本轮路由结果和置信度。
- `execute(tool, sandbox_class, writes_pixels)`：即将执行工具或代码，声明需要的隔离等级。

runtime 只在多个会话的 capability_set 兼容、租户相同、且都处于 quiescent 时，把它们折叠进一个共享快照宿主；收到 `execute` 时把该会话恢复到独占 microVM，执行结束后再决定是否折回。正确性不变量是：任何真正执行工具或代码的时间窗内，一个会话绝不与其他会话共享进程。意图本身不可信（模型可能说谎），所以 runtime 必须用实际的工具派发事件去校验声明，发现偏差就永久退出折叠资格。

**在图像融合 agent 上的具体形态。** 退化感知路由和提示生成是只读决策，天然满足折叠条件：读图像统计、调模型判断退化类型、选择算子链。真正的像素级融合算子执行和质量评估工具（可能加载原生库、占 GPU）属于 `execute`，必须展开。置信度门控有实际意义：路由置信度低意味着可能触发探索性代码，这类会话保持独占；置信度高且连续多轮选同一算子族，才允许折叠。于是密度来自决策等待期，隔离来自算子执行期，两者不再二选一。

**为什么这不是增量。** 它既不是论文里的客户端 close（那是平台无感的），也不是 k=64 的盲目多路复用（那对所有会话一视同仁），也不是 snapshot/restore（那只减启动）。新的是 agent 与 runtime 之间一条语义化控制通道：agent 暴露下一步意图，runtime 据此在共享与独占之间切换，并用可观测的工具派发事件保证隔离不变量。据本次查询，已有平台文档没有暴露这类信号。

**评估。** 主指标：环境每核数、p99 每步额外延迟、折叠/展开自身的开销、隔离违规计数必须为零。质量侧：融合 agent 的 PSNR/SSIM/LPIPS 在 IAFU 下与全隔离部署一致。消融四组：全隔离、盲目 k=64 共享、IAFU、IAFU 去掉置信度门控。预期 IAFU 的环境数接近盲目共享，p99 延迟高于盲目共享但远低于全隔离带来的配额压力；若折叠/展开开销超过论文给出的 40 ms 预算，这个想法就失败。

**风险写明白。** 模型生成的意图可能被提示注入操纵，必须靠 runtime 侧事实校验；融合工具常带 GPU 状态，快照成本可能吞掉收益；折叠窗口内一个会话的远程回复到达时若另一会话正在展开，调度复杂度会上升。这些都是未验证的【猜想】，不是结论。

---

<!--
PAPERFLOW_METRICS_JSON
{
  "task": "LLM agent 运行时容量与资源预留测量（系统性能论文；非图像融合算法论文）",
  "backbone": "LangGraph 0.6.11、Strands 1.55.0；Claude Sonnet 4.5（部署）/ Haiku 4.5（校准）经 Amazon Bedrock；LangChain ChatBedrockConverse、LiteLLM；AWS SDK before-send transport mock",
  "datasets": "τ²-bench retail 3,549 warm steps / 384 sessions；50 次模型 + 30 次工具延迟调用；每机器 4,800 步 transport-mock sweep；50–400 并发直测；9 个平台公开文档（2026-10-27）",
  "sota_summary": "无图像融合 SOTA 或视觉指标。核心量化结论：部署 step 等待中位 2.59–2.74 s、计算 4.5–38.9 ms（占 0.16%–1.5%）；1,000 会话仅忙 1.6–15 核；环境每核 68–610（计算）/110–260（直测）；隔离 1,008 环境，不 close 则 28,432（28×），共享 k=64 降至 17（59×）且 p99 仅 +40 ms；框架 CPU 对请求体线性，R² 0.96–0.98，常数跨硬件差五倍以上",
  "innovation_tags": [
    "socket-level transport mock keeping model client",
    "separate measurement of wait w and framework CPU c",
    "Little's law capacity ratio environments-per-busy-core",
    "wait-after-idle CPU inflation 1.9-4.7x",
    "client-side close vs platform-side multiplexing remedy quantification",
    "nine-platform billing/holding/limit survey",
    "open problem: per-session isolation without per-session reservation",
    "image-fusion mapping explicitly labeled as reader inference, not paper evidence"
  ]
}
-->

---

<!-- AI-GENERATED-NOTICE -->
!!! note "内容由 AI 生成，请审慎甄别"
    本站的论文解读、摘要速览与网站点评均由人工智能自动整理生成，仅用于学习与快速检索。
    AI 输出可能存在事实偏差、理解误差或信息滞后，涉及关键结论、数据与观点时，
    请以论文原文及官方来源为准，并自行判断其准确性。
