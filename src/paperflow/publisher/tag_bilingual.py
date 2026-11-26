"""论文标签的中英双语展示。

tag 来源：精读 Markdown frontmatter 的 tags（AI 生成，多为英文 slug）。
本站面向中文读者，渲染时把常见英文 tag 补上中文释义，形如
`agentic-robot-control（智能体机器人控制）`；无释义时原样显示英文 slug。
"""

from __future__ import annotations

# 常见 tag / 概念的英文 → 中文释义（key 统一小写、去连字符比较）
_BILINGUAL: dict[str, str] = {
    "agent": "智能体",
    "aiagent": "AI 智能体",
    "agentic": "智能体化",
    "multiagent": "多智能体",
    "agenticrobotcontrol": "智能体机器人控制",
    "actionlevelcritique": "动作级评判",
    "intentgroundedevaluation": "意图驱动的评估",
    "failureattribution": "失败归因",
    "visionlanguageaction": "视觉-语言-动作",
    "multimodalagent": "多模态智能体",
    "closedlooprecovery": "闭环恢复",
    "zeroshotmanipulation": "零样本操作",
    "imagefusionanalogy": "图像融合类比迁移",
    "imagefusion": "图像融合",
    "hsimsi": "高光谱-多光谱融合",
    "remotesensing": "遥感",
    "superrresolution": "超分辨率",
    "superresolution": "超分辨率",
    "diffusion": "扩散模型",
    "transformer": "Transformer 架构",
    "llm": "大语言模型",
    "largelanguagemodel": "大语言模型",
    "reinforcementlearning": "强化学习",
    "continuallearning": "持续学习",
    "benchmark": "基准评测",
    "dataset": "数据集",
    "evaluation": "评估方法",
    "efficiency": "效率优化",
    "rag": "检索增强生成",
    "tooluse": "工具调用",
    "planning": "任务规划",
    "reasoning": "推理",
    "memory": "记忆机制",
    "codegeneration": "代码生成",
    "security": "安全",
    "privacy": "隐私",
    "robotics": "机器人",
    "autonomousdriving": "自动驾驶",
    "federatedlearning": "联邦学习",
    "interpretability": "可解释性",
    # 强化学习 / 表征
    "continualrl": "持续强化学习",
    "successorrepresentation": "后继表征",
    "successorfeatures": "后继特征",
    "gridcells": "网格细胞",
    "laplacianeigenfunctions": "拉普拉斯特征函数",
    "spectralmethods": "谱方法",
    "generativemodel": "生成模型",
    "foundationmodel": "基础模型",
    "representationlearning": "表征学习",
    "selfsupervised": "自监督学习",
    "transferlearning": "迁移学习",
    "metalearning": "元学习",
    "policygradient": "策略梯度",
    "offlinerl": "离线强化学习",
    "rewarddesign": "奖励设计",
    # 工程 / 系统
    "serving": "模型服务",
    "latency": "延迟优化",
    "kv-cache": "KV 缓存",
    "kvcache": "KV 缓存",
    "throughput": "吞吐优化",
    "costoptimization": "成本优化",
    "multitenant": "多租户",
    "scheduling": "调度",
    "memorymanagement": "内存管理",
}


def _norm(tag: str) -> str:
    return "".join(ch for ch in str(tag).lower() if ch.isalnum())


# 词根级中文提示（用于组合型 slug 的兜底推断，宁可给类目也不留纯英文）
_ROOTS: list[tuple[str, str]] = [
    ("agent", "智能体"), ("reinforcement", "强化学习"), ("rl", "强化学习"),
    ("fusion", "融合"), ("spectral", "谱方法"), ("representation", "表征"),
    ("vision", "视觉"), ("image", "图像"), ("video", "视频"),
    ("language", "语言"), ("multimodal", "多模态"), ("diffusion", "扩散"),
    ("transformer", "Transformer"), ("memory", "记忆"), ("reasoning", "推理"),
    ("planning", "规划"), ("learning", "学习"), ("evaluation", "评估"),
    ("benchmark", "基准"), ("dataset", "数据集"), ("security", "安全"),
    ("serving", "服务"), ("compression", "压缩"), ("retrieval", "检索"),
    ("robot", "机器人"), ("control", "控制"), ("recurrent", "循环"),
    ("graph", "图"), ("neural", "神经"), ("adaptive", "自适应"),
]


def _infer_zh(tag: str) -> str:
    """从英文 slug 的词根推断中文类目提示（保守：命中>=2个词根才给）。"""
    norm = _norm(tag)
    hits = [zh for root, zh in _ROOTS if root in norm]
    uniq = list(dict.fromkeys(hits))
    return " / ".join(uniq[:2]) if uniq else ""


def tag_bilingual(tag: str) -> str:
    """返回单个 tag 的展示文本：中英拆开、各自可复制。

    英文 slug 用行内代码包裹（`` `tag` ``，便于选中复制），中文释义单独
    放在分隔符之后（`` `agent` · 智能体 ``）；无释义时只返回行内代码。
    """
    tag = (tag or "").strip()
    if not tag:
        return ""
    safe_tag = tag.replace("|", "\\|")  # 防破坏 Markdown 表格
    en = f"`{safe_tag}`"
    zh = _BILINGUAL.get(_norm(tag)) or _infer_zh(tag)
    return f"{en} · {zh}" if zh and zh.lower() not in tag.lower() else en


def tags_bilingual(tags) -> str:
    """把 tag 列表渲染成 ` ｜ ` 分隔的双语标签串，每项内部为 `英文 · 中文`。"""
    if not tags:
        return ""
    if isinstance(tags, str):
        tags = [tags]
    seen, out = set(), []
    for t in tags:
        text = tag_bilingual(str(t))
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return " ｜ ".join(out)
