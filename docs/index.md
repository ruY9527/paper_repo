# PaperFlow 2026 — 顶会顶刊论文精读库

!!! info "年度总览"
    - 已收录论文：**20** 篇
    - S 级精读：**13** 篇
    - A 级速览：**7** 篇
    - 带开源代码：**5** 篇
    - 收录网站：**0** 个 → [网站导航](sites/index.md)
    - 最近更新：2026-11-22

## 各顶会/顶刊收录数量

按发表年份分列统计；数字可点击跳转到对应 Venue 年度总表。当前优先年份 **2026**。

| Venue | 今年 2026 | 去年 2025 | 往期 | 合计 |
| :--- | ---: | ---: | ---: | ---: |
| TPAMI | 0 | 0 | 0 | 0 |
| TIP | 0 | 0 | 0 | 0 |
| IJCV | 0 | 0 | 0 | 0 |
| CVPR | 0 | 0 | 0 | 0 |
| ECCV | 0 | 0 | 0 | 0 |
| ICCV | 0 | 0 | 0 | 0 |
| NeurIPS | [1](venues/NeurIPS-2026.md) | 0 | 0 | [1](venues/NeurIPS-2026.md) |
| ICLR | 0 | 0 | 0 | 0 |
| AAAI | 0 | 0 | 0 | 0 |
| ARXIV（其它来源） | [18](venues/ARXIV-2026.md) | 0 | 0 | [18](venues/ARXIV-2026.md) |
| OPENALEX（其它来源） | [1](venues/OPENALEX-2026.md) | 0 | 0 | [1](venues/OPENALEX-2026.md) |

## 最近发布的高价值论文

| 日期 | Venue | 标题 | Tier | 标签 | TL;DR |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-11-19 | NeurIPS | [Grid Cells as Spectral Successor Features: A Reusable Basis for Continual Reinforcement Learning](papers/2026/NEURIPS/arxiv_2611.26504.md) | S | `continual-RL` · 持续强化学习 ｜ `successor-representation` · 后继表征 ｜ `successor-features` · 后继特征 ｜ `grid-cells` · 网格细胞 ｜ `laplacian-eigenfunctions` · 拉普拉斯特征函数 ｜ `spectral-methods` · 谱方法 | Continual reinforcement learning requires agents to adapt when the task changes while reusing what t… |
| 2026-11-19 | arXiv | [Seer: Guiding Small Deep-Research Agents with Shared Decision Models](papers/2026/arXiv/arxiv_2611.26423.md) | S | `deep-research-agent` · 智能体 ｜ `inference-time-guidance` ｜ `model-based-lookahead` ｜ `world-model` · 强化学习 ｜ `value-estimator` ｜ `puct` | Deep-research agents repeatedly decide what to search, read, and verify, often using large cloud-hos… |
| 2026-11-19 | arXiv | [MemFolder: Structure-Guided Memory Folding for Efficient Agent Memory Management](papers/2026/arXiv/arxiv_2611.26427.md) [💻](https://github.com/xuyang-liu16/MemFolder) | S | `agent-memory` · 智能体 / 记忆 ｜ `memory-compression` · 记忆 / 压缩 ｜ `retrieval-augmented-generation` · 检索 ｜ `long-term-agents` · 智能体 ｜ `DPC-clustering` ｜ `temporal-chaining` | Long-term agents accumulate large external memory stores as interactions unfold, increasing the cost… |
| 2026-11-19 | arXiv | [Aggron: Aggressive Compression of Agentic KV Caches during Head-of-Line Stalls in the Request Queue](papers/2026/arXiv/arxiv_2611.26435.md) | S | `agentic-serving` · 智能体 / 服务 ｜ `kv-cache` · KV 缓存 ｜ `context-compression` · 压缩 ｜ `head-of-line-blocking` ｜ `vllm` ｜ `queue-aware-scheduling` | LLM agents run long, multi-turn programs whose contexts grow at every step, and serving them is limi… |
| 2026-11-19 | arXiv | [Held While Waiting: What LLM Agent Sessions Reserve on Serverless and Agent Runtimes](papers/2026/arXiv/arxiv_2611.26480.md) [💻](https://github.com/MEKHALA/agent-runtime-capacity) | S | `LLM agent` · 智能体 ｜ `serverless` · 强化学习 ｜ `agent runtime` · 智能体 ｜ `capacity measurement` ｜ `Little's law` ｜ `isolation vs multiplexing` | LLM agents spend nearly all their time waiting for the model |
| 2026-11-19 | arXiv | [JARVIS: An Agent That Designs, Builds, and Tests Circuit Boards on Its Own](papers/2026/arXiv/arxiv_2611.26503.md) | S | `embodied-agent` · 智能体 ｜ `self-driving-lab` ｜ `digital-twin` ｜ `power-electronics` ｜ `hardware-in-the-loop` ｜ `PCB` | Power electronics is central to the energy transition, but developing new hardware still relies on h… |
| 2026-11-19 | arXiv | [ACE-Brain-0.7: Learning Execution-Grounded Reasoning for Embodied Agents](papers/2026/arXiv/arxiv_2611.26519.md) | S | `embodied-reasoning` · 推理 ｜ `execution-grounding` ｜ `vision-language-model` · 视觉 / 语言 ｜ `task-planning` · 规划 ｜ `progress-estimation` ｜ `spatial-grounding` | Reliable reasoning for long-horizon embodied tasks requires predictions grounded in the observed exe… |
| 2026-11-19 | arXiv | [Backtracking Agent Applications Security Incidents](papers/2026/arXiv/arxiv_2611.26525.md) | S | `agent security` · 智能体 / 安全 ｜ `backtracking` ｜ `taint analysis` ｜ `CEP` ｜ `CLDG` ｜ `indirect prompt injection` | Agent applications are increasingly deployed, yet agent-specific attacks pose real threats to them |
| 2026-11-19 | arXiv | [Cost-Aware Agentic Feature Optimization System for Fleet-Scale Ranking Models](papers/2026/arXiv/arxiv_2611.26531.md) | S | `feature-selection` ｜ `llm-agent` · 智能体 ｜ `llm-as-optimizer` ｜ `cost-aware-optimization` ｜ `ads-ranking` ｜ `pareto-optimality` | Large Web platforms operate large fleets of ranking models, each selecting features from a shared po… |
| 2026-11-19 | arXiv | [Replication of Agentic Security Events: Audit and Investigation (ROGUE-AI)](papers/2026/arXiv/arxiv_2611.26553.md) [💻](https://rogue-ai.surge.sh) | S | `LLM agents` · 智能体 ｜ `agent security` · 智能体 / 安全 ｜ `incident replication` ｜ `causal inference` ｜ `matched control` · 控制 ｜ `multi-agent pipeline` · 智能体 | Agents based on large language models (LLMs) can now delete files and send payments on behalf of the… |
| 2026-11-19 | arXiv | [AgentRoboCritic: Understanding the Capability of Frontier Agents on Direct Robot Control](papers/2026/arXiv/arxiv_2611.26613.md) [💻](https://github.com/cxcscmu/AgentRoboCritic) | S | `agentic-robot-control` · 智能体机器人控制 ｜ `action-level-critique` · 动作级评判 ｜ `intent-grounded-evaluation` · 意图驱动的评估 ｜ `failure-attribution` · 失败归因 ｜ `vision-language-action` · 视觉-语言-动作 ｜ `multimodal-agent` · 多模态智能体 | Frontier multimodal language agents such as GPT-6 Astra have demonstrated strong capabilities in con… |
| 2026-11-19 | arXiv | [PlayCraft: Designing Engaging Games from Agent Play Experience](papers/2026/arXiv/arxiv_2611.26624.md) [💻](https://github.com/xt4d/PlayCraft) | S | `game-design` ｜ `foundation-model-agent` · 智能体 ｜ `visual-game-playing` ｜ `mastery` ｜ `playtest-driven-revision` · 视觉 ｜ `agent-memory` · 智能体 / 记忆 | Recent AI agents can generate playable games, but these games are not necessarily engaging |

<div class="hv-pager" id="hv-pager" markdown>

每页 8 篇 · 第 <b id="hv-page">1</b> / 2 页

<button type="button" onclick="hvGo(-1)">← 上一页</button> <button type="button" onclick="hvGo(1)">下一页 →</button>

</div>

<script>
(function(){
  var tables=document.querySelectorAll('table');
  var tbl=null; tables.forEach(function(x){ if(x.querySelector('th') && x.textContent.indexOf('TL;DR')>=0 && x.textContent.indexOf('标签')>=0) tbl=x; });
  if(!tbl) return;
  var rows=Array.prototype.slice.call(tbl.querySelectorAll('tbody tr'));
  var per=8, page=0, total=Math.ceil(rows.length/per);
  window.hvGo=function(d){ page=Math.max(0,Math.min(total-1,page+d));
    rows.forEach(function(r,i){ r.style.display=(i>=page*per&&i<(page+1)*per)?'':'none'; });
    var el=document.getElementById('hv-page'); if(el) el.textContent=page+1;
    window.scrollTo({top:document.getElementById('hv-pager').offsetTop-80,behavior:'smooth'});
  };
  window.hvGo(0);
})();
</script>

## 按研究方向浏览

- [agent](topics/agent.md)（20 篇）

---

<!-- AI-GENERATED-NOTICE -->
!!! note "内容由 AI 生成，请审慎甄别"
    本站的论文解读、摘要速览与网站点评均由人工智能自动整理生成，仅用于学习与快速检索。
    AI 输出可能存在事实偏差、理解误差或信息滞后，涉及关键结论、数据与观点时，
    请以论文原文及官方来源为准，并自行判断其准确性。
