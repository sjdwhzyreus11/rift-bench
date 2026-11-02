"""证据收集编排（qa/evidence.py）。

为一问题收集四类"依据"，供 LLM 裁判层组织回答：
  - cards:   卡牌匹配（多卡+部分名+模糊）→ 原文
  - effects: 卡牌效果结构解释（执行顺序）
  - flow:    引擎流程权威步骤（结算链/战斗/回合/打出）
  - rules:   规则依据链（锚点+父链+兄弟+章节）
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from riftbench.qa.card_match import CardMatcher
from riftbench.qa.corpus import Corpus
from riftbench.qa.effect_explain import EffectExplainer
from riftbench.qa.flow_explain import FlowExplainer
from riftbench.qa.retriever import Retriever
from riftbench.qa.rule_chain import RuleChainBuilder


class EvidenceCollector:
    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self.matcher = CardMatcher(corpus)
        self.retriever = Retriever(corpus)
        self.chain = RuleChainBuilder(corpus)
        self.flow = FlowExplainer()
        self.effects = EffectExplainer()

    def collect(self, question: str, k: int = 4) -> dict:
        """收集四类证据。"""
        # 卡牌（多卡）
        cards = self.matcher.match_all(question)
        # 效果结构
        effects = [self.effects.explain(c["name"], c["text"]) for c in cards]
        # 引擎流程
        flow = self.flow.detect(question)
        # 规则依据链
        rule_docs = self.retriever.retrieve_rules(question, k=k)
        anchors = [d.meta.get("rule_id") for d in rule_docs if d.meta.get("rule_id")]
        # 流程涉及时，把流程规则编号也纳入锚点
        if flow:
            anchors = [s["rule"] for s in flow["steps"]] + anchors
        # 多类型卡（如既是单位又是装备）→ 附带多类型规则（178.3: 可被任一类型的效应影响）
        if any(len(c.get("types", [])) > 1 for c in cards):
            anchors = ["178.3", "178", "177"] + anchors
        chains = self.chain.build_multi(list(dict.fromkeys(anchors))[:6])
        # 额外：卡牌相关规则（若有卡名，检索该卡效果相关规则）
        return {
            "cards": cards,
            "effects": effects,
            "flow": flow,
            "rules": chains,
            "rule_docs": [{"rule": d.meta.get("rule_id"), "text": d.text} for d in rule_docs],
        }

    def to_facts(self, question: str, evidence: dict) -> str:
        """把证据渲染为 LLM 可读的"事实块"（防幻觉：只给材料）。"""
        lines = [f"# 问题\n{question}\n", "# 参考材料（仅依据以下材料作答）\n"]

        if evidence.get("cards"):
            lines.append("## 卡牌")
            for c in evidence["cards"]:
                types = "/".join(c.get("types", [])) or "?"
                lines.append(f"- {c['name']}（匹配方式：{c['match_type']}；类型：{types}）")
                lines.append(f"  原文：{c['text']}")
        if evidence.get("effects"):
            lines.append("\n## 卡牌效果结构（引擎解析）")
            for e in evidence["effects"]:
                lines.append(f"- {e['name']}：")
                for s in e["structure"]:
                    lines.append(f"    {s}")
                if e.get("note"):
                    lines.append(f"    注：{e['note']}")
        if evidence.get("flow"):
            f = evidence["flow"]
            lines.append(f"\n## 引擎流程：{f['name']}（权威实现：{f['engine']}）")
            for i, s in enumerate(f["steps"], 1):
                lines.append(f"  {i}. {s['desc']}  [规则 {s['rule']}]")
        if evidence.get("rules"):
            lines.append("\n## 规则依据链")
            for ch in evidence["rules"]:
                lines.append(f"- 锚点 [规则 {ch['anchor_rule']}]（章节：{ch['chapter']}）")
                for p in ch["chain"]:
                    lines.append(f"    父规则 [{p['rule']}]: {p['text'][:200]}")
                for s in ch["siblings"][:5]:
                    lines.append(f"    兄弟 [{s['rule']}]: {s['text'][:160]}")
        return "\n".join(lines)
