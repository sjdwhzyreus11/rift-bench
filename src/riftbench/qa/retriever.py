"""轻量检索（qa/retriever.py）— 纯 stdlib，零依赖，确定性。

流程:
  1. tokenize_query: 中文问题 → 英文查询词
     - 保留已有英文 token（卡名/英文关键词/数字）
     - 中文片段查术语表 → 英文同义词
  2. 卡牌名精确匹配（用户直接问卡名）
  3. 文档 TF 加权评分 → top-K 命中（带规则编号锚定）
"""
from __future__ import annotations

import re
from typing import Optional

from riftbench.qa.corpus import Corpus, Doc

_ENGLISH_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9'\-]*")
_NUM_TOKEN = re.compile(r"\d+")


def tokenize(text: str) -> list[str]:
    """英文/数字 token 提取（小写）。"""
    toks = _ENGLISH_TOKEN.findall(text) + _NUM_TOKEN.findall(text)
    return [t.lower() for t in toks]


def tokenize_query(query: str, terms: dict[str, str]) -> list[str]:
    """中文问题 → 英文查询词（术语表桥接）。"""
    tokens: list[str] = []
    # ① 英文/数字 token 原样
    tokens.extend(tokenize(query))
    # ② 中文术语查表
    for zh, en in terms.items():
        if zh in query:
            tokens.extend(tokenize(en))
    return tokens


def _tf_score(doc_text: str, query_tokens: list[str], rule_id: str | None = None) -> float:
    """加权评分：查询词覆盖率 + 短定义规则优先 + 顶级编号优先。

    改进：绝对词频偏向长规则（Example 多），覆盖率 + 短文档加权
    让章节定义规则（002/469/328 等）优先命中。
    """
    d_toks = tokenize(doc_text)
    if not d_toks or not query_tokens:
        return 0.0
    hits = set(t for t in query_tokens if t in d_toks)
    # 查询词覆盖率（0-1）
    coverage = len(hits) / len(set(query_tokens))
    # 命中词频加权（小）
    freq = sum(1 for t in d_toks if t in query_tokens)
    score = coverage * 2.0 + 0.1 * freq
    # 定义锚点：极短定义规则（如 806 "Action"）被查询词精确覆盖 → 最高优先
    if len(d_toks) <= 5 and hits and all(t in hits for t in d_toks):
        score += 3.0
    # 短定义规则加权（章节标题/定义句通常短）
    if len(d_toks) <= 40:
        score += 1.0
    # 顶级编号规则加权（无子编号，如 '431' 而非 '431.3.c'）
    if rule_id and "." not in rule_id:
        score += 0.5
    return score


class Retriever:
    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        # 卡名倒排（小写 → 卡数据）
        self._card_by_name: dict[str, list[dict]] = {}
        for c in corpus.cards:
            nm = c.get("static", {}).get("name", "").lower()
            self._card_by_name.setdefault(nm, []).append(c)

    def find_card(self, query: str) -> list[dict]:
        """卡牌名精确匹配（小写）。"""
        q = query.lower().strip()
        hits = self._card_by_name.get(q, [])
        if hits:
            return hits
        # 包含匹配
        return [c for name, cs in self._card_by_name.items() if q in name
                for c in cs][:5]

    def retrieve(self, query: str, k: int = 5, source: Optional[str] = None) -> list[Doc]:
        """检索 top-K 文档（TF 加权）。"""
        q_tokens = tokenize_query(query, self.corpus.terms)
        if not q_tokens:
            return []
        scored: list[tuple[float, Doc]] = []
        for doc in self.corpus.docs:
            if source and doc.source != source:
                continue
            s = _tf_score(doc.text, q_tokens, rule_id=doc.meta.get("rule_id"))
            if s > 0:
                scored.append((s, doc))
        scored.sort(key=lambda x: -x[0])
        return [d for _, d in scored[:k]]

    def retrieve_rules(self, query: str, k: int = 5) -> list[Doc]:
        """只检索规则语料（带规则编号）。"""
        return self.retrieve(query, k=k, source="rules")