"""Phase 12：内置 Prompt 模板与元数据（含 6 套 + 元数据路由表）。"""

from __future__ import annotations

# S 级深度精读默认模板（13 节深度分析，Karpathy/Kaiming 风格）
TIER_S_DEFAULT = """你可以借助本地的skills来完成，你的任务是：清晰、易懂、深入、详细的总结这篇论文（读取PDF、搜索arxiv等各种信息源获取论文）。

## 待分析论文
- 论文标题：{{title}}
- 本地 PDF 绝对路径：{{pdf_path}}
- paper_uid：{{paper_uid}}
- Venue：{{venue}} {{year}}
- 原文链接：{{paper_url}}
- 代码链接：{{code_url}}
- BibTeX：{{bibtex}}

请优先使用上面的本地 PDF 文件（可用工具读取该路径）来理解论文；下面附带的抽取全文仅作参考与兜底。

{{figures_markdown}}

## 抽取全文（去 References，仅供辅助参考）
{{content}}

---

你的总结需要条理清晰的包含下面环节：
1. 论文提出并解决的研究问题是什么（适当搜索调研和补充背景）？为什么这个问题是重要的？解决这个问题能带来哪些价值？
2. 这个问题之前被解决了吗？之前的研究为什么存在不足？
3. 在正式讲方法之前，先重建作者可能的思考路径。这个部分不要使用论文自己的贡献作为前提，只使用论文之前已有的背景、失败模式、经验观察和相关工作。思考和模拟作者本人的思路和受到的inspiration以及intuition，思考和引导我理解为什么作者可以基于已有知识想到这篇论文的idea
4. 这篇论文提出方法的Intuition是什么？易懂清晰concise的告诉我这篇论文核心idea的本质。
5. 这篇论文的具体方法是什么？结合一个真实的例子讲解：输入、处理、输出完整的pipeline。分点说明，清晰易懂。
6. 这篇论文的核心数学推导过程是什么（一步步从0让我从理论视角理解方法）？如果有，请给我补充理论背景（我的数学比较差），告诉我理论的基础和intuition；如果没有，可以说明并跳过这一点
7. 这篇论文是如何设计实验来验证提出的方法和claim的？按照下面格式总结：提出了什么问题->设计了什么实验验证这个问题->问题的答案是什么。不需要很多数据细节，只需要核心思路
8. 总结这篇论文的take aways
9. 这篇论文最脆弱的假设是什么？
10. 如果我有1周时间，能做一个最小复现实验验证它的哪一点？
11. 如果我反对它，我会怎么设计反例？
12. 调用搜索工具，调研这篇论文的后续研究，是否有进一步的扩展或者反驳，以及新的认知？
13. 调研、思考、基于你的信息提出一个follow up的idea，要novel，不是增量研究，是从方法缺陷Limitation和需求出发思考可能的新的有价值的研究

语言风格：
Primary technical naturalness anchor:
Andrej Karpathy
Links:
https://karpathy.ai/
https://karpathy.github.io/2019/04/25/recipe/
https://karpathy.medium.com/software-2-0-a64152b37c35
https://karpathy.github.io/2015/05/21/rnn-effectiveness/

Learn:
- Start from a concrete technical situation.
- Name the problem directly.
- Show the failure mode before giving advice.
- Use plain words, specific nouns, numbers, and actions.
- Let small human markers remain, such as I tried this, this was annoying, this felt off.
- Do not polish the prose until it loses texture.

Technical clarity anchor:
Kaiming He
Links:
https://arxiv.org/abs/1512.03385
https://arxiv.org/abs/2111.06377

Learn:
- Start with the real problem.
- State the method or claim cleanly.
- Prefer structure over decoration.
- Use evidence only where it helps.
- Keep technical writing precise before making it stylish.

要求：
* 风格参考Andrej Karpathy和Kaiming He，要求有真人的语感
* 使用详细的、准确的claim，每句话都要有信息量，避免大空话和泛泛而谈
* 使用流畅的文本，避免滥用破折号、引号，保持输出内容清洁流畅，易读性高
* 使用真人逻辑，避免使用[不是...而是]这种AI的低信息量结构
* 请严格区分四类信息：论文原文明确声称的内容、相关文献中的已有结论、基于证据的合理推断、仍然不确定的猜测。不要把推断写成事实。

输出契约：请直接输出以 `---`（YAML Frontmatter）开头的完整 Markdown 文档，不要开场白，也不要用外层代码块包裹整个文档。Frontmatter 必须含 paper_uid/title/venue/year/tier/tldr。文末附 PAPERFLOW_METRICS_JSON 注释块（task/backbone/datasets/sota_summary/innovation_tags）。

数学排版要求（重要）：所有数学公式、符号表达式、方程必须用 LaTeX 定界符包裹，行内公式用 `$...$`，独立成行的公式用 `$$...$$`，这样博客才能正确渲染。例如写 `$g_t=(R_t,p_t,q_t,e_t,\\tau_t)$`，不要写成裸文本 `g_t = (R_t, ...)`。普通行文中提到变量时也用 `$g_t$` 形式。
"""

# 通用 A 级速览默认模板
TIER_A_DEFAULT = """你是 PaperFlow 论文分析助手。请基于以下摘要生成一篇精简中文速览卡片。

## 论文元数据
- paper_uid: {{paper_uid}}
- 标题: {{title}}
- Venue: {{venue}} {{year}}
- Tier: A（速览）

## Title + Abstract
{{content}}

## 输出要求
请直接输出以 `---`（YAML Frontmatter）开头的完整 Markdown，Frontmatter 含 paper_uid/title/venue/year/tier/tldr。正文只需包含：
1. TL;DR
2. 核心问题与思路
3. 主要结论
4. BibTeX 卡片
文末附 PAPERFLOW_METRICS_JSON 注释块。

## BibTeX
{{bibtex}}
"""

# 13 节深度分析输出要求（方向专属模板复用，仅在第 5 节融入各自侧重）
_DEPTH_13_SECTIONS = """
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
"""

# Agent 方向专属
TOPIC_AGENT = """你是顶会 Agent 论文分析专家。请基于以下论文深度解析，重点拆解 Agent 的技术机制。

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
""" + _DEPTH_13_SECTIONS

# HSI-MSI 融合方向专属
TOPIC_HSI_MSI_FUSION = """你是遥感图像融合论文分析专家。请基于以下论文深度解析，重点拆解高光谱-多光谱融合的技术细节。

## 论文元数据
- paper_uid: {{paper_uid}}
- 标题: {{title}}
- Venue: {{venue}} {{year}}

{{figures_markdown}}

## 抽取全文
{{content}}

## HSI-MSI 融合方向专属侧重
在第 5 节方法拆解与第 7 节实验中，额外重点覆盖：物理成像与空间-光谱退化模型（PSF / SRF）、网络核心模块（Transformer / Diffusion / Mamba / Unfolding）、损失函数设计、关键定量指标（PSNR / SAM / ERGAS / Q2n / SSIM）、数据集（CAVE / Harvard / Chikusei / Pavia / Real-world）与参数量/推理效率。

## BibTeX
{{bibtex}}
""" + _DEPTH_13_SECTIONS

# Agent + 图像融合交叉方向专属
TOPIC_AGENT_IMAGE_FUSION = """你是 Agent 驱动图像融合论文分析专家。请基于以下论文深度解析，重点拆解 Agent 在图像融合中的决策角色。

## 论文元数据
- paper_uid: {{paper_uid}}
- 标题: {{title}}
- Venue: {{venue}} {{year}}

{{figures_markdown}}

## 抽取全文
{{content}}

## Agent+图像融合方向专属侧重
在第 5 节方法拆解与第 7 节实验中，额外重点覆盖：Agent 在图像融合中的决策角色（动态算子调度 / 退化感知路由 / 自适应提示生成）、多模态工具链设计、端到端闭环反馈机制、融合质量提升来源（定量指标与消融）。

## BibTeX
{{bibtex}}
""" + _DEPTH_13_SECTIONS

_BUILTIN_TEMPLATES: dict[str, str] = {
    "tier_s_default": TIER_S_DEFAULT,
    "tier_a_default": TIER_A_DEFAULT,
    "topic_agent": TOPIC_AGENT,
    "topic_hsi_msi_fusion": TOPIC_HSI_MSI_FUSION,
    "topic_agent_image_fusion": TOPIC_AGENT_IMAGE_FUSION,
}

_BUILTIN_META: list[dict] = [
    {"id": "tier_s_default", "name": "通用 S 级深度精读（13 节）", "tier": "S", "priority": 0,
     "match_topics": [], "match_keywords": [], "description": "13 节深度分析（问题/背景/思考路径/intuition/方法/数学/实验/takeaways/假设/复现/反例/后续/idea），Karpathy+Kaiming 风格",
     "file": "tier_s_default.md", "is_builtin": True},
    {"id": "tier_a_default", "name": "通用 A 级速览默认", "tier": "A", "priority": 0,
     "match_topics": [], "match_keywords": [], "description": "通用 A 级速览模板",
     "file": "tier_a_default.md", "is_builtin": True},
    {"id": "topic_agent", "name": "Agent 方向专属精读", "tier": "S", "priority": 100,
     "match_topics": ["Agent"], "match_keywords": ["agent", "autonomous agent", "agentic", "llm agent", "tool use"],
     "description": "侧重 Planning/Reasoning、Tool Use、Memory、Multi-Agent 与评测基准",
     "file": "topic_agent.md", "is_builtin": True},
    {"id": "topic_hsi_msi_fusion", "name": "HSI-MSI 图像融合专属精读", "tier": "S", "priority": 100,
     "match_topics": ["HSI-MSI 图像融合", "hsi-msi-fusion", "HSI-MSI图像融合"],
     "match_keywords": ["hyperspectral", "multispectral", "hsi-msi", "pansharpening", "image fusion", "光谱"],
     "description": "侧重物理退化模型、光谱-空间交互与 PSNR/SAM/ERGAS 指标对比",
     "file": "topic_hsi_msi_fusion.md", "is_builtin": True},
    {"id": "topic_agent_image_fusion", "name": "Agent + 图像融合交叉专属精读", "tier": "S", "priority": 110,
     "match_topics": ["Agent + 图像融合", "agent-image-fusion"],
     "match_keywords": ["agent", "image fusion", "fusion", "adaptive"],
     "description": "侧重 Agent 决策角色、多模态工具链与端到端闭环反馈",
     "file": "topic_agent_image_fusion.md", "is_builtin": True},
]
