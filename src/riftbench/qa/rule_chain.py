"""规则依据链（qa/rule_chain.py）。

解决 P5 短板：只返回零散规则片段，无上下文依据。
  - 层级聚合：命中 465.2.c.5 → 拉父链(465.2.c → 465.2 → 465) + 所属章节
  - 兄弟子规则：锚点规则的直接子规则（补细节）
  - 多话题：一个问题涉多话题 → 分别检索后合并去重

输出: [{anchor_rule, chain, siblings, chapter, texts}]
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from riftbench.qa.corpus import Corpus


def parent_chain(rule_id: str) -> list[str]:
    """返回父规则链（由近到远）: '465.2.c.5' → ['465.2.c','465.2','465']。"""
    parts = rule_id.split(".")
    return [".".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]


class RuleChainBuilder:
    # 相邻编号视为兄弟（474.1 的兄弟是 474.2、474.3；465.2.a 的兄弟是 465.2.b）
    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self.rules = corpus.rules_index
        self.chapters = corpus.chapters

    def build(self, anchor_rule: str) -> dict:
        """为一条锚点规则构建依据链。"""
        chain = []
        # 锚点本身在最前（放最前便于展示"依据"）
        if anchor_rule in self.rules:
            chain.append({"rule": anchor_rule, "text": self.rules[anchor_rule]})
        for pid in parent_chain(anchor_rule):
            if pid in self.rules:
                chain.append({"rule": pid, "text": self.rules[pid]})
        # 章节（顶层编号）
        top = anchor_rule.split(".")[0]
        chapter = self.chapters.get(top, "")
        # 兄弟子规则：同父下的直接子规则
        parent = ".".join(anchor_rule.split(".")[:-1])
        prefix = (parent + ".") if parent else ""
        siblings = []
        for rid in self.rules:
            if rid == anchor_rule:
                continue
            if prefix and rid.startswith(prefix) and "." not in rid[len(prefix):]:
                siblings.append({"rule": rid, "text": self.rules[rid]})
            elif not prefix and rid.startswith(top + ".") and rid.count(".") == 1:
                siblings.append({"rule": rid, "text": self.rules[rid]})
        # 兄弟按编号排序，取邻近若干
        siblings.sort(key=lambda x: x["rule"])
        return {
            "anchor_rule": anchor_rule,
            "chain": chain,
            "siblings": siblings[:8],
            "chapter": chapter,
            "texts": [self.rules.get(anchor_rule, "")],
        }

    def build_multi(self, rule_ids: list[str]) -> list[dict]:
        """多锚点 → 多个依据链（去重锚点）。"""
        seen = set()
        out = []
        for rid in rule_ids:
            if rid in seen or rid not in self.rules:
                continue
            seen.add(rid)
            out.append(self.build(rid))
        return out
