"""启发式对局 agent（engine/agents/heuristic.py）。

比 RandomAgent 聪明的中等 baseline，用于对局评测对照。
策略（贪心）:
  - Closed/Showdown: 若手牌有 [Reaction] 且合法 → 打出（响应）；否则让过
  - Open 主阶段:
    1. 激活未横置符文产法力（若想打的卡法力不足）
    2. 打出单位到战场（优先高战力）
    3. 移动活跃单位去战场（进攻/争夺）
    4. 打出法术
    5. 否则让过
"""
from __future__ import annotations

import random

from riftbench.engine.actions import legal_actions
from riftbench.engine.model import PlayerId, ZoneType
from riftbench.engine.state import GameState


class HeuristicAgent:
    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def observe(self, state: GameState, viewpoint: PlayerId) -> dict:
        hand = [{"runtime_id": o.runtime_id, "name": o.name, "energy": o.energy,
                 "types": [t.value for t in o.types], "keywords": list(o.keywords)}
                for o in state.objects_in(viewpoint, ZoneType.HAND)]
        acts = legal_actions(state, viewpoint)
        return {
            "viewpoint": viewpoint.value,
            "hand": hand,
            "phase": state.phase.value,
            "turn_state": state.derive_turn_state().value,
            "priority_player": state.priority_player.value if state.priority_player else None,
            "showdown": state.is_showdown(),
            "closed": state.is_closed(),
            "legal_actions": [{**a} for a in acts],
        }

    def propose(self, obs: dict) -> dict:
        legal = obs.get("legal_actions", [])
        if not legal:
            return {"type": "pass"}
        closed = obs.get("closed")
        showdown = obs.get("showdown")
        hand = obs.get("hand", [])

        # Closed/Showdown：优先 [Reaction] 牌
        if closed or showdown:
            reacts = [a for a in legal if a.get("type") == "play"
                      and a["hand_runtime_id"] in {o["runtime_id"] for o in hand
                                                   if "Reaction" in o.get("keywords", [])}]
            if reacts:
                return self.rng.choice(reacts)
            return {"type": "pass"}  # 让过优先权

        # Open 主阶段贪心
        runes = [a for a in legal if a.get("type") == "activate_rune"]
        plays = [a for a in legal if a.get("type") == "play"]
        moves = [a for a in legal if a.get("type") == "move"]

        # 1) 单位打到战场优先（高战力低费）
        unit_plays = []
        for a in plays:
            o = next((o for o in hand if o["runtime_id"] == a["hand_runtime_id"]), None)
            if o and "unit" in o.get("types", []) and (a.get("target_location_id") or "").startswith("bf:"):
                unit_plays.append((a, o))
        if unit_plays:
            unit_plays.sort(key=lambda x: -(x[1].get("energy", 0) or 0))
            return unit_plays[0][0]

        # 2) 移动进攻
        if moves:
            return moves[0]

        # 3) 单位打到基地
        base_plays = [a for a in plays
                      if (a.get("target_location_id") or "").startswith("base:")]
        if base_plays:
            return base_plays[0]

        # 4) 法术
        spell_plays = [a for a in plays]
        if spell_plays:
            return spell_plays[0]

        # 5) 符文
        if runes:
            return runes[0]

        return {"type": "pass"}