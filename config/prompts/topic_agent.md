你是顶会 Agent 论文分析专家。请基于以下论文深度解析，重点拆解 Agent 的技术机制。

## 论文元数据
- paper_uid: {{paper_uid}}
- 标题: {{title}}
- Venue: {{venue}} {{year}}

{{figures_markdown}}

## 抽取全文
{{content}}

## Agent 方向专属侧重
在第 5 节方法拆解与第 7 节实验中，额外重点覆盖：Planning/Reasoning 机制（任务分解、推理链）、Tool Use 与环境交互接口（工具定义、调用协议）、Memory 架构（短期/长期记忆、检索）、Multi-Agent 协同（角色分工、通信协议）、Agent 评测基准（OSWorld / SWE-bench / WebArena）与失败案例。

## BibTeX
{{bibtex}}

## 输出要求
请直接输出以 `---`（YAML Frontmatter）开头的完整 Markdown 文档，不要开场白、解释性废话，也不要用外层 ```markdown 代码块包裹。Frontmatter 必须含 paper_uid/title/venue/year/tier/tldr/tags/code_url/paper_url。

正文按下面 13 个环节组织，条理清晰、深入详细。第 1–8 点是核心，务必完整；第 9–13 点同样请认真完成：
1. 论文提出并解决的研究问题是什么（适当搜索调研和补充背景）？为什么重要？带来哪些价值？
2. 这个问题之前被解决了吗？之前的研究为什么存在不足？
3. 在正式讲方法前，先重建作者可能的思考路径。不要使用论文自己的贡献作为前提，只用论文之前的背景、失败模式、经验观察和相关工作。模拟作者的思路、inspiration 和 intuition，引导我理解为什么基于已有知识能想到这个 idea。
4. 方法的 Intuition 是什么？清晰、易懂、concise 地讲清核心 idea 本质。
5. 具体方法是什么？结合一个真实例子讲解：输入、处理、输出完整 pipeline。分点说明。
6. 核心数学推导过程（一步步从 0 让我从理论视角理解）。有则补充理论背景（我数学较差），讲清基础和 intuition；没有则说明并跳过。
7. 论文如何设计实验验证方法和 claim？按「提出什么问题 → 设计什么实验 → 答案是什么」总结，不要堆数据细节。
8. 总结 take aways。
9. 这篇论文最脆弱的假设是什么？
10. 如果我有 1 周时间，能做一个最小复现实验验证它的哪一点？
11. 如果我反对它，我会怎么设计反例？
12. 调用搜索工具，调研后续研究，是否有进一步扩展或反驳，以及新的认知？
13. 基于你的信息提出一个 follow-up idea，要 novel，不是增量研究，从方法缺陷和需求出发的新的有价值研究方向。

## 语言风格
参考 Andrej Karpathy（https://karpathy.ai/，https://karpathy.github.io/2019/04/25/recipe/）与 Kaiming He（https://arxiv.org/abs/1512.03385）：从具体技术场景出发，直接点出问题，先展示失败模式再给建议，用平实的词、具体的名词/数字/动作，保留真人语感，不把文字打磨到失去质感；从真实问题出发，清晰陈述方法或 claim，结构优先于装饰，先精确再讲究。

## 硬性要求
使用详细准确的 claim，每句话都有信息量；流畅文本，避免滥用破折号/引号，保持清洁易读；用真人逻辑，避免「不是……而是……」这类低信息量结构；严格区分四类信息（论文原文明确声称 / 相关文献已有结论 / 基于证据的合理推断 / 不确定的猜测），不把推断写成事实。

文末附 PAPERFLOW_METRICS_JSON 注释块（task/backbone/datasets/sota_summary/innovation_tags）。
