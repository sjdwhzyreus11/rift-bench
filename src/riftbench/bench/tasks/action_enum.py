"""T3 合法行动枚举 — 给定状态枚举全体合法行动（precision/recall/F1）。

样本: {question: {task, candidates: 候选行动列表}, engine_answer: {actions: 合法集}}
candidates = 合法集 + 若干非法扰动（供模型挑选，衡量它能否筛出合法）。
"""
from __future__ import annotations

from riftbench.engine.actions import legal_actions
from riftbench.engine.model import PlayerId, ZoneType
from riftbench.engine.state import GameState


def _norm_action(a: dict) -> str:
    """行动规范化为可哈希字符串（去 target_location 排序影响）。"""
    parts = [str(a.get("type"))]
    for k in ("hand_runtime_id", "target_location_id", "unit_runtime_id",
              "to_location_id", "rune_runtime_id", "obj_id", "ability_idx"):
        v = a.get(k)
        if v is not None:
            parts.append(f"{k}={v}")
    return "|".join(parts)


def _add_distractor(legit: set[str], state: GameState, viewpoint: PlayerId) -> list[dict]:
    """加 1-2 个非法扰动行动。"""
    distract: list[dict] = []
    opp = state.opponent_of(viewpoint)
    opp_hand = list(state.objects_in(opp, ZoneType.HAND))
    if opp_hand:
        d = {"type": "play", "hand_runtime_id": opp_hand[0].runtime_id,
             "target_location_id": None}
        if _norm_action(d) not in legit:
            distract.append(d)
    if len(distract) < 2:
        d2 = {"type": "move", "unit_runtime_id": 99999, "to_location_id": "base:north"}
        if _norm_action(d2) not in legit:
            distract.append(d2)
    return distract


def generate(state: GameState, viewpoint: PlayerId, rng, meta: dict | None = None) -> dict:
    legit = legal_actions(state, viewpoint)
    legit_norm = {_norm_action(a) for a in legit}
    distract = _add_distractor(legit_norm, state, viewpoint)
    candidates = [dict(a) for a in legit] + distract
    rng.shuffle(candidates)
    return {
        "question": {"task": "T3", "candidates": candidates},
        "engine_answer": {"actions": [dict(a) for a in legit]},
        "meta": {"task": "T3", "legit_count": len(legit),
                 "distract_count": len(distract), **(meta or {})},
    }


def answer(state: GameState, question: dict) -> dict:
    """引擎正答：从 candidates 中筛出合法集。"""
    candidates = question.get("candidates", [])
    legit_norm = set()
    for pid in state.turn_order:
        try:
            for a in legal_actions(state, pid):
                legit_norm.add(_norm_action(a))
        except Exception:
            pass
    return {"actions": [a for a in candidates if _norm_action(a) in legit_norm]}