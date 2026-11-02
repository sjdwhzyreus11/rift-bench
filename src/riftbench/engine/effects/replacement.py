"""替换效果引擎（规则 367-370）— 统一"would X 发生 → 改做 Y"概念。

替换类型（ReplacementEffect.replacement）:
  - prevent:  "prevent the next N damage" → 伤害减 N（至 0）
  - double:   "Double all damage that would be dealt to it" → 伤害 ×2
  - damage_immune: "can't be dealt damage" → 伤害全免（连续效果层也设，此处兜底）
  - instead:  "would die → recall instead" 等 → 改执行替代动作（MVP 先支持死亡→召回/放逐）

规则 370.2: 每个替换效果对同一事件只应用一次。
规则 370.4: 同时离开场的物体仍可应用其替换效果（MVP 简化：只扫在场）。

伤害应用点（executor._op_deal / combat._assign_damage）调 apply_damage 获取实际伤害。
"""
from __future__ import annotations

import re
from typing import Optional

from riftbench.engine.model import GameObject, ZoneType
from riftbench.engine.state import GameState


# ---------- 解析 ----------

_PREVENT_RE = re.compile(r"\bprevent(?: the next)?\s*(\d+)?\s*damage\b", re.IGNORECASE)
_DOUBLE_RE = re.compile(r"\bdouble all damage\b|\bdouble the damage\b", re.IGNORECASE)
_IMMUNE_RE = re.compile(r"\b(?:don'?t take damage|can'?t be dealt damage)\b", re.IGNORECASE)
_WOULD_DIE_RE = re.compile(r"\bwould die\b", re.IGNORECASE)
_INSTEAD_RECALL_RE = re.compile(r"\b(?:recall|return)(?: me| it| this)? instead\b", re.IGNORECASE)
_INSTEAD_BANISH_RE = re.compile(r"\bbanish(?: me| it| this)? instead\b", re.IGNORECASE)


def parse_replacement_effects(text: str) -> list[dict]:
    """从卡面文本提取替换效果。返回 [{trigger, replacement, value}]。"""
    effects: list[dict] = []
    for m in _PREVENT_RE.finditer(text):
        val = int(m.group(1)) if m.group(1) else 1
        effects.append({"trigger": "damage", "replacement": "prevent", "value": val})
    if _DOUBLE_RE.search(text):
        effects.append({"trigger": "damage", "replacement": "double", "value": 2})
    if _IMMUNE_RE.search(text):
        effects.append({"trigger": "damage", "replacement": "damage_immune", "value": True})
    if _WOULD_DIE_RE.search(text):
        if _INSTEAD_RECALL_RE.search(text):
            effects.append({"trigger": "death", "replacement": "recall_instead", "value": True})
        elif _INSTEAD_BANISH_RE.search(text):
            effects.append({"trigger": "death", "replacement": "banish_instead", "value": True})
    return effects


def register_replacement(state: GameState, obj: GameObject) -> None:
    """进场/解析时注册替换效果（去重）。"""
    if obj.replacement_effects:
        return
    parsed = parse_replacement_effects(obj.card_text)
    if parsed:
        obj.replacement_effects = parsed


# ---------- 伤害替换应用 ----------

def apply_damage(state: GameState, target: GameObject, amount: int) -> int:
    """对 target 应用伤害替换效果，返回实际应造成的伤害（规则 367）。

    替换来源：target 自身的替换效果 + 持续效果层的 damage_immune。
    每效果仅应用一次（370.2，MVP 简化按注册顺序一次）。
    """
    # 连续效果层免伤
    if getattr(target, "damage_immune", False):
        return 0
    # 替换效果
    for ef in target.replacement_effects:
        if ef.get("trigger") != "damage":
            continue
        rep = ef.get("replacement")
        if rep == "prevent":
            amount = max(0, amount - ef.get("value", 1))
        elif rep == "double":
            amount *= ef.get("value", 2)
        elif rep == "damage_immune":
            return 0
    return amount


def apply_death_replacement(state: GameState, obj: GameObject) -> Optional[str]:
    """死亡替换：返回替代动作（'recall_instead'/'banish_instead'）或 None（正常死亡）。"""
    for ef in obj.replacement_effects:
        if ef.get("trigger") == "death":
            rep = ef.get("replacement")
            if rep == "recall_instead":
                return "recall_instead"
            if rep == "banish_instead":
                return "banish_instead"
    return None


def _is_on_board(state: GameState, obj: GameObject) -> bool:
    return obj.zone in (ZoneType.BASE, ZoneType.BATTLEFIELD)