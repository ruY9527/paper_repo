"""Phase 10：研究方向查询解析、同义词扩展与相关性打分（07 文档第 3.1 节）。

把用户自然输入（中文 / 英文 / 缩写 / `+` 组合）转成 arXiv / OpenAlex 可用的
检索式，并提供本地二次相关性校验。纯函数模块，无网络与数据库副作用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import AppConfig

# 组合分隔符（仅显式符号；中文连接词交给「词典最长匹配扫描」处理）
_SPLIT_RE = re.compile(r"\s*(?:\+|＆|&|\bAND\b)\s*", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 非概念 token（连接词/助词/标点）——按「最长优先」逐字符跳过，
# 避免「以及」只跳过「以」而把「及」误当概念、或「or图像」把 or 粘进中文。
_STOPWORDS = sorted([
    "以及", "并且", "或者", "关于", "进行", "相关", "方向",
    "与", "和", "及", "或", "的", "了", "在", "是", "对", "中", "下", "上",
    "and", "or", "of", "for", "with", "the", "a", "an",
    "，", "。", "、", "；", "：", "！", "？", ",", ".", ";", ":", "!", "?",
    "(", ")", "[", "]", "{", "}", "'", "《", "》", " ",
], key=len, reverse=True)


def _skip_stopword(seg: str, i: int) -> int:
    """若 seg[i:] 以某个停用词开头，返回跳过的长度；否则 0。最长优先。"""
    for sw in _STOPWORDS:
        if seg[i:i + len(sw)].lower() == sw.lower():
            return len(sw)
    return 0


@dataclass
class ConceptGroup:
    """一个必选概念组（AND group），含原始词与扩展同义词（OR）。"""

    raw: str
    terms: list[str] = field(default_factory=list)


@dataclass
class ParsedTopicQuery:
    raw_query: str
    groups: list[ConceptGroup]
    relaxed: bool = False  # 是否启用了放宽匹配

    def expanded_text(self) -> str:
        """人类可读的扩展结果，如 'agent → agent / LLM agent ...'。"""
        parts: list[str] = []
        for g in self.groups:
            parts.append(f"{g.raw} → {' / '.join(g.terms)}")
        return " ; ".join(parts)

    def arxiv_query(self) -> str:
        """arXiv 语法：(ti:"t" OR abs:"t") AND (...)。"""
        group_strings: list[str] = []
        for g in self.groups:
            ors = []
            for term in g.terms:
                q = f'"{term}"' if " " in term else term
                ors.append(f'ti:{q}')
                ors.append(f'abs:{q}')
            group_strings.append("(" + " OR ".join(ors) + ")")
        return " AND ".join(group_strings)

    def openalex_query(self) -> str:
        """OpenAlex title_and_abstract.search 布尔串：(t1 OR t2) AND (...)。"""
        group_strings: list[str] = []
        for g in self.groups:
            ors = [f'"{t}"' if " " in t else t for t in g.terms]
            group_strings.append("(" + " OR ".join(ors) + ")")
        return " AND ".join(group_strings)


def _lookup_synonyms(concept: str, synonym_dict: dict[str, list[str]]) -> list[str] | None:
    """忽略大小写查同义词词典；命中返回扩展列表，否则 None。"""
    lower = concept.strip().lower()
    for key, values in synonym_dict.items():
        if key.lower() == lower:
            return list(values)
    return None


def parse_topic_query(raw_query: str, config: AppConfig,
                      translate_fn=None) -> ParsedTopicQuery:
    """解析用户输入为概念组并扩展同义词。

    规则（词典最长匹配扫描，不依赖枚举连接词）：
    - 整体先查词典（忽略大小写），命中则作为单组。
    - 否则按 `+ / ＆ / & / AND` 拆段；每段用词典 key 从左到右最长匹配切概念。
    - 残留连接词/助词（与、和、的、的…及标点）自动丢弃，绝不送翻译 API。
    - 切不出词典 key 的中文片段才整段翻译（此时无连接词污染）；英文短语原样保留。
    - 这样任意新词/新连接词都不会因「整词误译」而零命中。
    """
    raw = (raw_query or "").strip()
    synonym_dict = config.topic_search.synonym_dict

    # 1) 整体查词典（完全命中直接用，最快路径）
    whole = _lookup_synonyms(raw, synonym_dict)
    if whole:
        return ParsedTopicQuery(raw_query=raw, groups=[ConceptGroup(raw=raw, terms=whole)])

    # 2) 先按显式符号拆；每段再做「词典最长匹配扫描」
    segments = [p.strip() for p in _SPLIT_RE.split(raw) if p.strip()] or [raw]

    def _scan_segment(seg: str) -> list[tuple[str, list[str]]]:
        """在一个片段里从左到右扫描，词典 key 最长匹配优先切出概念。

        例：'agent与图像融合' → [('agent',[...]), ('图像融合',[...])]
        'HSI-MSI图像融合' → [('hsi-msi图像融合',[...])]（最长 key 优先）
        残留的连接词/助词由 _STOPWORDS_RE 丢弃；切不出词典 key 的纯中文
        整段才交给翻译 API（此时不含任何连接词污染）。
        """
        found: list[tuple[str, list[str]]] = []
        keys = sorted(synonym_dict.keys(), key=len, reverse=True)
        i, n = 0, len(seg)
        while i < n:
            match = None
            for k in keys:
                if k and seg[i:i + len(k)].lower() == k.lower():
                    match = k
                    break
            if match:
                found.append((match, list(synonym_dict[match])))
                i += len(match)
                continue
            # 未命中词典：最长优先跳过停用词
            sw = _skip_stopword(seg, i)
            if sw:
                i += sw
                continue
            # 找到一段「非词典、非停用」的连续文本，作为潜在概念
            j = i + 1
            while j < n:
                if _skip_stopword(seg, j):
                    break
                hit = any(seg[j:j + len(k)].lower() == k.lower() for k in keys if k)
                if hit:
                    break
                j += 1
            chunk = seg[i:j].strip()
            if chunk:
                found.append((chunk, []))  # 空 terms 表示待翻译
            i = j
        return found

    groups: list[ConceptGroup] = []
    for seg in segments:
        scanned = _scan_segment(seg)
        for raw_term, terms in scanned:
            if terms:
                groups.append(ConceptGroup(raw=raw_term, terms=terms))
                continue
            # 待翻译：中文才翻译；翻译失败（仍中文）则丢弃，不用中文污染英文检索式
            term = raw_term
            if _CJK_RE.search(raw_term):
                en = translate_fn(raw_term) if translate_fn else None
                if en and en.lower() != raw_term.lower() and not _CJK_RE.search(en):
                    term = en
                else:
                    continue  # 翻译不可用：跳过该片段，避免中文零命中
            terms = _lookup_synonyms(term, synonym_dict) or [term]
            groups.append(ConceptGroup(raw=raw_term, terms=terms))

    # 兜底：扫描没有任何结果（全是未知字符）时保留原文，绝不返回空 groups
    if not groups:
        groups = [ConceptGroup(raw=raw, terms=[raw])]
    return ParsedTopicQuery(raw_query=raw, groups=groups)


def compute_topic_relevance(paper, parsed: ParsedTopicQuery) -> float:
    """本地二次相关性打分。

    - 标题命中某概念组任一同义词：+25/组
    - 摘要命中：+12/组
    - 组合方向（>=2 组）全部组在标题或摘要命中：完全匹配 +30
    - 未完全匹配时返回已得分（调度器可据此判断 relaxed_match）
    """
    title = (getattr(paper, "title", "") or "").lower()
    abstract = (getattr(paper, "abstract", "") or "").lower()
    text = f"{title} {abstract}"
    score = 0.0
    all_hit = True

    for group in parsed.groups:
        terms = [t.lower() for t in group.terms if t]
        in_title = any(t in title for t in terms)
        in_abstract = any(t in abstract for t in terms)
        if in_title:
            score += 25.0
        elif in_abstract:
            score += 12.0
        else:
            all_hit = False

    if len(parsed.groups) >= 2 and all_hit:
        score += 30.0  # 交叉方向完全匹配加分
    return score


def is_fully_matched(paper, parsed: ParsedTopicQuery) -> bool:
    """组合方向是否所有概念组都命中（用于 relaxed_match 标记）。"""
    text = f"{(getattr(paper, 'title', '') or '')} {(getattr(paper, 'abstract', '') or '')}".lower()
    for group in parsed.groups:
        if not any(t.lower() in text for t in group.terms if t):
            return False
    return True
