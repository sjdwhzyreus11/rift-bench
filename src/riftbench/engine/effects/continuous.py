"""连续效果层（规则 473-480）— 持续修正的计算与收敛。

连续效果类型（ContinuousEffect modifier）:
  - might_plus:   "I have +N [M]" → 算术层战力修正
  - cost_minus:   "I cost N less" → 算术层费用修正
  - damage_immune:"I don't take damage" / "can't be dealt damage" → 免伤
  - keyword_grant:"I have [Keyword]" → 能力层授予关键字

三层应用顺序（477）:
  1. Trait-Altering（改变特质）→ 2. Ability-Altering（改变能力）→ 3. Arithmetic（加减）
MVP: 重点实现算术层（might/cost）+ 能力层关键字授予。特质层（改类型/特性）留 P2 收尾。

规则 476: 反复应用至收敛——recompute 汇总所有连续效果，写入 GameObject 的
continuous_might_mod / continuous_cost_mod / damage_immune 字段（供 effective_might/费用读取）。
"""
from __future__ import annotations

import re
from typing import Optional

from riftbench.engine.model import GameObject
from riftbench.engine.state import GameState


# ---------- 解析：从卡面文本识别持续修正 ----------

_HAVE_MIGHT_RE = re.compile(r"\b(?:I|it|this)\s+have?\s+\+\s*(\d+)\s*\[?[MS]\]?", re.IGNORECASE)
_HAVE_MIGHT_NEG_RE = re.compile(r"\b(?:I|it|this)\s+have?\s+-?\s*(\d+)\s*\[?[MS]\]?\b", re.IGNORECASE)
_COST_LESS_RE = re.compile(r"\bcosts?\s+\[?(\d+)\]?\s+less\b|\bcosts?\s+(\d+)\s+less\b", re.IGNORECASE)
_IMMUNE_DAMAGE_RE = re.compile(r"\b(?:don'?t take damage|can'?t be dealt damage|takes? no damage)\b", re.IGNORECASE)
_HAVE_KEYWORD_RE = re.compile(r"\b(?:I|it|this)\s+have\?\s*(\[[A-Za-z ]+\])", re.IGNORECASE)


def parse_continuous_effects(text: str) -> list[dict]:
    """从卡面文本提取持续修正效果。返回 [{modifier, value, ...}]。"""
    effects: list[dict] = []
    # +N [M]（排除 "this turn" 临时——那是临时修正，非连续）
    for m in _HAVE_MIGHT_RE.finditer(text):
        effects.append({"modifier": "might_plus", "value": int(m.group(1))})
    # costs N less
    for m in _COST_LESS_RE.finditer(text):
        val = int(m.group(1) or m.group(2) or 0)
        effects.append({"modifier": "cost_minus", "value": val})
    # 免疫伤害
    if _IMMUNE_DAMAGE_RE.search(text):
        effects.append({"modifier": "damage_immune", "value": True})
    # 关键字授予
    for m in _HAVE_KEYWORD_RE.finditer(text):
        effects.append({"modifier": "keyword_grant", "keyword": m.group(1)})
    return effects


def register_continuous(state: GameState, obj: GameObject) -> None:
    """进场/解析时注册连续效果（去重）。"""
    if obj.continuous_effects:
        return
    parsed = parse_continuous_effects(obj.card_text)
    if parsed:
        obj.continuous_effects = parsed
    # 也处理 [Empowered]/[Level] 依赖关键字（由 keywords.py 做条件授予，此处登记能力层）
    recompute_continuous(state, obj)


def recompute_continuous(state: GameState, obj: GameObject) -> None:
    """重算 obj 的连续效果（476 收敛）。写入 continuous_might_mod/cost_mod/damage_immune。"""
    might = 0
    cost = 0
    immune = False
    for ef in obj.continuous_effects:
        mod = ef.get("modifier")
        if mod == "might_plus":
            might += ef.get("value", 0)
        elif mod == "cost_minus":
            cost += ef.get("value", 0)
        elif mod == "damage_immune":
            immune = True
    obj.continuous_might_mod = might
    obj.continuous_cost_mod = cost
    obj.damage_immune = immune


def recompute_all(state: GameState) -> None:
    """全表重算所有在场物体的连续效果（层收敛，规则 476）。"""
    for o in state.objects.values():
        if o.zone in ("base", "battlefield") or True:
            recompute_continuous(state, o)


# 便捷查询

def effective_might(state: GameState, obj: GameObject) -> int:
    """含连续效果层的有效战力。"""
    return obj.effective_might


def is_damage_immune(state: GameState, obj: GameObject) -> bool:
    """是否免伤（连续效果层）。"""
    return bool(getattr(obj, "damage_immune", False))