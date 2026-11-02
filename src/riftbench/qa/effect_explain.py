"""效果结构解释（qa/effect_explain.py）。

解决 P5 短板：不解释"卡牌效果按什么顺序执行"。
复用 P2.1 的 parse_card_effects 把卡牌文本拆成能力结构 → 中文描述。

输出: {name, text, structure: [能力描述], parseable, note}
"""
from __future__ import annotations

from riftbench.engine.effects.parser import parse_card_effects

# 指令 op → 中文动词
_OP_ZH = {
    "play": "打出", "kill": "摧毁", "deal": "造成伤害", "ready": "变为活跃",
    "exhaust": "横置", "move": "移动", "recall": "召回", "score": "得 1 分",
    "gain": "获得资源", "give_might": "给予战力加成", "buff": "放置 buff",
    "draw": "抽牌", "banish": "放逐", "recycle": "回收", "discard": "弃牌",
    "return": "返回手牌", "look_at": "查看", "reveal": "展示", "stun": "眩晕",
    "counter": "反制（无效化）", "heal": "移除伤害", "temp_grant": "授予关键词",
    "other": "（未识别）",
}
_EVENT_ZH = {
    "play": "被打出时", "enter": "进场时", "conquer": "征服时", "hold": "据守时",
    "attack": "进攻时", "defend": "防守时", "die": "死亡时", "kill": "摧毁时",
    "draw": "抽牌时", "played_card": "打出卡牌时", "start_of_phase": "阶段开始时",
    "other": "特定条件满足时",
}
_REL_ZH = {"friendly": "友方", "enemy": "敌方", "your": "你的", "a": "一个", "an": "一个",
           "any": "任意", "each": "每个", "controller": "你", "self": "自身"}
_KIND_ZH = {"unit": "单位", "gear": "装备", "spell": "法术", "rune": "符文", "card": "卡牌",
            "player": "玩家", "battlefield": "战场"}


class EffectExplainer:
    def explain(self, name: str, text: str) -> dict:
        parsed = parse_card_effects(text or "", name)
        structure = []
        for ab in parsed.abilities:
            structure.append(self._describe(ab))
        return {
            "name": name,
            "text": text or "",
            "structure": structure,
            "parseable": parsed.parseable,
            "keywords": parsed.keywords,
            "note": "" if parsed.parseable else "结构解析不完整，以卡面原文为准（规则 001 卡面优先）",
        }

    def _describe(self, ab) -> str:
        parts = []
        # 能力类型
        kind_zh = {"triggered": "触发式能力", "activated": "主动技能",
                   "passive": "被动/规则", "instruction": "指令效果"}.get(ab.kind.value, ab.kind.value)
        # 依赖条件门
        cond = f"（仅在条件「{ab.condition_keyword}」满足时）" if ab.condition_keyword else ""
        # 触发条件
        if ab.trigger is not None:
            ev = _EVENT_ZH.get(ab.trigger.event.value, ab.trigger.event.value)
            subj = {"self": "此牌", "controller": "你", "friendly_unit": "友方单位",
                    "enemy_unit": "敌方单位", "any": "任意"}.get(ab.trigger.subject.value, "")
            head = f"{kind_zh}：当{subj}{ev}"
        elif ab.cost:
            head = f"{kind_zh}：支付【{ab.cost}】后"
        else:
            head = kind_zh
        parts.append(head + cond)
        # 指令序列
        if ab.instructions:
            seq = []
            for i, ins in enumerate(ab.instructions, 1):
                seq.append(f"  {i}. {self._instr(ins)}")
            parts.append("执行顺序：\n" + "\n".join(seq))
        if ab.keywords:
            parts.append(f"关键词：{', '.join(ab.keywords)}")
        return "\n".join(parts)

    def _instr(self, ins) -> str:
        verb = _OP_ZH.get(ins.op.value, ins.op.value)
        bits = [verb]
        if ins.amount is not None:
            bits.append(f"（{ins.amount}）")
        t = ins.target
        if t is not None and (t.card_kind or t.relation.value not in ("a", "an")):
            rel = _REL_ZH.get(t.relation.value, t.relation.value)
            kind = _KIND_ZH.get(t.card_kind, t.card_kind or "")
            loc = f"（{t.location}）" if t.location else ""
            bits.append(f"目标：{rel}{kind}{loc}")
        if ins.optional:
            bits.append("（你可以选择是否执行）")
        if ins.quals.get("this_turn"):
            bits.append("（本回合内）")
        return "".join(bits)
