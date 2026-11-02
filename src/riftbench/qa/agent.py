"""规则问答智能体主入口（qa/agent.py）— P5.1 裁判增强版。

RiftboundQA.answer(question) 流程:
  1. 引擎核验路由（可计算问题: 构筑/卡牌/禁卡）→ 权威判定
  2. 证据收集（四类）: 卡牌匹配 / 效果结构 / 引擎流程 / 规则依据链
  3. LLM 裁判层（配置 ANTHROPIC_API_KEY）→ 中文裁判回答（引用规则编号+卡牌原文）
     未配置 → 结构化模板回答（依据分块展示）

返回: {answer, citations, cards, evidence, source}
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from riftbench.qa.corpus import Corpus
from riftbench.qa.card_match import CardMatcher
from riftbench.qa.effect_explain import EffectExplainer
from riftbench.qa.engine_check import EngineCheck
from riftbench.qa.evidence import EvidenceCollector
from riftbench.qa.flow_explain import FlowExplainer
from riftbench.qa.llm import JudgeLLM
from riftbench.qa.retriever import Retriever
from riftbench.qa.rule_chain import RuleChainBuilder


class RiftboundQA:
    def __init__(self, root: Optional[Path] = None,
                 llm: Optional[JudgeLLM] = None) -> None:
        self.root = root or Path(__file__).resolve().parents[3]
        self.corpus = Corpus(self.root).load()
        self.retriever = Retriever(self.corpus)
        self.engine = EngineCheck(self.root)
        self.matcher = CardMatcher(self.corpus)
        self.evidence = EvidenceCollector(self.corpus)
        self.llm = llm if llm is not None else JudgeLLM()

    def answer(self, question: str,
               decklist: Optional[list[tuple[str, int]]] = None) -> dict:
        """回答一个问题。"""
        # ① 引擎核验路由（构筑/禁卡/简单卡牌详情）
        engine_result = self.engine.route(question, decklist)
        if engine_result and engine_result.get("kind") == "deck":
            return self._engine_answer(question, engine_result)
        if engine_result and engine_result.get("kind") == "banlist":
            return self._engine_answer(question, engine_result)
        # 卡牌详情：仅在"单纯问卡牌"时直接走引擎（复杂判例走证据+裁判）
        if engine_result and engine_result.get("kind") == "card" and self._is_simple_card_q(question):
            return self._engine_answer(question, engine_result)

        # ② 证据收集
        ev = self.evidence.collect(question)

        # ③ LLM 裁判层
        citations = self._citations(ev)
        card_names = [c["name"] for c in ev["cards"]]
        if self.llm.is_configured:
            facts = self.evidence.to_facts(question, ev)
            try:
                nl = self.llm.judge(question, facts)
            except Exception as e:
                nl = None
                ev["llm_error"] = str(e)
            if nl:
                return {"answer": nl, "citations": citations, "cards": card_names,
                        "evidence": ev, "source": "judge"}

        # ④ 结构化回退（无 key / LLM 失败）
        return self._structured_answer(question, ev, citations, card_names)

    # ---------- 回答构建 ----------

    def _structured_answer(self, question, ev, citations, card_names) -> dict:
        """结构化裁判式回退：依据分块展示（卡牌/效果结构/流程/规则依据）。"""
        lines = [f"问：{question}", ""]
        # 卡牌
        if ev.get("cards"):
            lines.append("【相关卡牌】")
            for c in ev["cards"]:
                types = "/".join(c.get("types", []))
                lines.append(f"  · {c['name']}（类型：{types}）: {c['text'][:200]}")
        # 效果结构
        if ev.get("effects"):
            lines.append("\n【效果执行结构】")
            for e in ev["effects"]:
                for s in e["structure"]:
                    lines.append(f"  · {s}")
        # 引擎流程
        if ev.get("flow"):
            f = ev["flow"]
            lines.append(f"\n【{f['name']}】（引擎权威实现）")
            for i, s in enumerate(f["steps"], 1):
                lines.append(f"  {i}. {s['desc']}  [规则 {s['rule']}]")
        # 规则依据链
        if ev.get("rules"):
            lines.append("\n【规则依据】")
            for ch in ev["rules"][:3]:
                for p in ch["chain"][:2]:
                    lines.append(f"  [规则 {p['rule']}] {p['text'][:200]}")
        if not any([ev.get("cards"), ev.get("flow"), ev.get("rules")]):
            lines.append("  未找到直接命中的规则/卡牌。可尝试英文卡名或更具体的规则术语。")
        return {"answer": "\n".join(lines), "citations": citations,
                "cards": card_names, "evidence": ev, "source": "structured"}

    def _engine_answer(self, question: str, engine_result: dict) -> dict:
        kind = engine_result.get("kind")
        lines = [f"问：{question}", f"答（引擎核验·{kind}）："]
        if kind == "card":
            lines.append(f"  {engine_result['name']} [{engine_result['public_code']}]")
            lines.append(f"  类型={'/'.join(engine_result['types'])} "
                         f"费用={engine_result['energy']} 战力={engine_result['might']}")
            if engine_result["text"]:
                lines.append(f"  效果: {engine_result['text']}")
        elif kind == "banlist":
            lines.append(f"  {'禁用' if engine_result['banned'] else '未禁用'}"
                         f"（{'/'.join(engine_result.get('formats', []))}）")
        elif kind == "deck":
            lines.append(f"  合法: {'是' if engine_result['valid'] else '否'}")
            for issue in engine_result.get("issues", []):
                lines.append(f"    ✗ {issue}")
            lines.append(f"  主牌堆 {engine_result['main_size']} 张，符文 {engine_result['rune_count']} 张")
        return {"answer": "\n".join(lines), "citations": [],
                "cards": [], "evidence": None, "source": "engine"}

    # ---------- 辅助 ----------

    def _is_simple_card_q(self, question: str) -> bool:
        """单纯问卡牌（无场景/顺序/交互词）→ 直接走引擎卡牌详情。"""
        complex_keys = ["顺序", "结算", "响应", "如果", "当", "链", "触发", "互动", "先", "再", "同时"]
        return not any(k in question for k in complex_keys)

    def _citations(self, ev: dict) -> list[str]:
        cits = []
        for ch in ev.get("rules", []):
            if ch.get("anchor_rule"):
                cits.append(ch["anchor_rule"])
        if ev.get("flow"):
            cits.extend(s["rule"] for s in ev["flow"]["steps"])
        return list(dict.fromkeys(cits))
