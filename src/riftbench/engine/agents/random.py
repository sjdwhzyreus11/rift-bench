"""随机 baseline agent。

协议:
  observe(state, viewpoint) -> Observation  按隐私等级（规则 128）过滤后的视图
  propose(observation) -> action            从合法行动集随机选（引擎提供），按 RNG seed 确定性

MVP 简化:
  - Observation 含该玩家的手牌、公开场上信息、分数、符文池、合法行动（供随机选择）。
  - random agent 不做规则推理——它直接消费 legal_actions（引擎给出），这是 baseline 定位。
"""
from __future__ import annotations

import random

from riftbench.engine.actions import legal_actions
from riftbench.engine.model import PlayerId, Privacy, ZoneType
from riftbench.engine.state import GameState


class RandomAgent:
    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def observe(self, state: GameState, viewpoint: PlayerId) -> dict:
        # 按隐私过滤：手牌（Private，仅自己）、场公开信息
        hand = [{"runtime_id": o.runtime_id, "name": o.name, "energy": o.energy}
                for o in state.objects_in(viewpoint, ZoneType.HAND)]
        opp = state.opponent_of(viewpoint)
        battlefields = []
        for loc, bf in state.battlefields.items():
            battlefields.append({
                "location_id": loc, "name": bf.name, "status": bf.status.value,
                "controller": bf.controller.value if bf.controller else None,
            })
        units_on_board = []
        for rid, o in state.objects.items():
            if o.controller == viewpoint and o.zone in (ZoneType.BASE, ZoneType.BATTLEFIELD) and o.is_unit:
                units_on_board.append({"runtime_id": rid, "name": o.name, "might": o.might,
                                       "location": o.location_id, "readiness": o.readiness})
        return {
            "viewpoint": viewpoint.value,
            "hand": hand,
            "hand_count": len(hand),
            "opponent_hand_count": len(state.objects_in(opp, ZoneType.HAND)),
            "battlefields": battlefields,
            "my_units": units_on_board,
            "my_score": state.players[viewpoint].score,
            "opp_score": state.players[opp].score,
            "rune_pool_mana": state.players[viewpoint].rune_pool.mana,
            "legal_actions": [{**a} for a in legal_actions(state, viewpoint)],
        }

    def propose(self, observation: dict) -> dict:
        legal = observation.get("legal_actions", [])
        if not legal:
            return {"type": "pass"}
        # 带倾向的随机 baseline（避免纯随机导致对局冗长）：
        # 优先 激活符文产法力 → 打出单位/装备 → 移动单位到战场 → 打出法术 → pass
        def weight(a: dict) -> int:
            t = a["type"]
            if t == "activate_rune":
                return 0
            if t == "play":
                obj_type = _guess_card_kind(a)
                return 1 if obj_type in ("unit", "gear") else 2
            if t == "move":
                return 1
            if t == "pass":
                return 6
            return 3

        weighted = []
        for a in legal:
            w = weight(a)
            weighted.extend([a] * (10 - w))
        if not weighted:
            return self.rng.choice(legal)
        return self.rng.choice(weighted)


def _guess_card_kind(action: dict) -> str:
    """从 play 行动猜卡牌类型（MVP 简化：未知返回 'other'）。"""
    # 真实对象类型由 action 附带（agent 视角的 observation 里没有完整 obj），
    # MVP 简化：play 行动统一优先于 spell；具体单位/装备差异由观察完整性决定。
    return "unit"