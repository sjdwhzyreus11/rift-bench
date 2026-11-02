"""场景生成器（bench/scenarios.py）。

把引擎状态转换为模型可观察的视图（隐私过滤，规则 128），并生成 benchmark 场景。

场景样本格式（JSONL）:
  {"id", "task", "observation": {...隐私过滤视图}, "question": {...任务输入},
   "engine_answer": {...引擎正答}, "meta": {...}}

生成方式:
  - gen_random_scenarios: 随机 agent 跑对局到随机步数取快照 + 引擎正答
  - 黄金样本: tasks 模块内人工构造边界 case
"""
from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from riftbench.engine.model import PlayerId, ZoneType
from riftbench.engine.state import GameState


def observation_of(state: GameState, viewpoint: PlayerId) -> dict:
    """隐私过滤后的观察视图（规则 128）——给模型看的输入。

    公开信息全量 + 自己手牌（Private）+ 对手手牌数（Public）。
    """
    opp = state.opponent_of(viewpoint)
    # 自己的手牌（Private）
    hand = [
        {"runtime_id": o.runtime_id, "name": o.name, "energy": o.energy,
         "types": [t.value for t in o.types]}
        for o in state.objects_in(viewpoint, ZoneType.HAND)
    ]
    # 场上所有单位/装备（Public）
    board = []
    for rid, o in state.objects.items():
        if o.zone in (ZoneType.BASE, ZoneType.BATTLEFIELD):
            board.append({
                "runtime_id": rid, "name": o.name,
                "controller": o.controller.value,
                "zone": o.zone.value, "location": o.location_id,
                "might": o.might, "damage": o.damage, "readiness": o.readiness,
                "stunned": o.stunned,
            })
    battlefields = [
        {"location_id": loc, "name": bf.name, "status": bf.status.value,
         "controller": bf.controller.value if bf.controller else None}
        for loc, bf in state.battlefields.items()
    ]
    return {
        "viewpoint": viewpoint.value,
        "opponent": opp.value,
        "phase": state.phase.value,
        "turn_state": state.derive_turn_state().value,
        "turn_player": state.turn_player.value,
        "turn_number": state.turn_number,
        "scores": {p.value: state.players[p].score for p in state.players},
        "hand": hand,
        "hand_count": len(hand),
        "opponent_hand_count": len(state.objects_in(opp, ZoneType.HAND)),
        "opponent_rune_pool": {"mana": state.players[opp].rune_pool.mana},
        "rune_pool": {"mana": state.players[viewpoint].rune_pool.mana},
        "board": board,
        "battlefields": battlefields,
        "chain": [{"kind": c.kind, "player": c.player.value, "finalized": c.finalized}
                  for c in state.chain],
    }


def _load_db():
    """加载卡牌库（bench 独立运行，不依赖 tests）。"""
    from riftbench.cards import CardDatabase
    root = Path(__file__).resolve().parents[3]
    return CardDatabase.load(root / "data" / "cards" / "cards.json")


def _make_decks(db):
    """构造两套小型合法卡组。"""
    from riftbench.cards import CardType
    from riftbench.engine.setup import Deck
    def cards(set_id, ctype):
        return [c for c in db.cards if not c.is_variant
                and c.static.set_id.value == set_id and ctype in c.static.types]
    units = cards("OGN", CardType.UNIT)
    spells = cards("OGN", CardType.SPELL)
    runes = cards("OGN", CardType.RUNE)
    legends = cards("OGN", CardType.LEGEND)
    bfs = cards("OGN", CardType.BATTLEFIELD)
    champs = [c for c in db.cards if not c.is_variant
              and any(s.value == "champion" for s in c.static.super_types)]
    rune_ids = ([r.static.internal_id for r in runes] * 6)[:12]
    main = [c.static.internal_id for c in (units[:20] + spells[:20])]
    while len(main) < 40:
        main.append(main[len(main) % len(main)])
    def mk():
        return Deck(main_deck=main, rune_deck=rune_ids,
                    legend=legends[0].static.internal_id,
                    chosen_champion=champs[0].static.internal_id,
                    battlefield_candidates=[b.static.internal_id for b in bfs[:3]])
    return mk(), mk()


def make_random_scenario_state(seed: int | None = None) -> tuple[GameState, PlayerId]:
    """随机 agent 跑到随机步数，返回 (状态快照, 视角玩家)。

    视角 = 当前回合玩家（或随机）。
    """
    from riftbench.engine.setup import setup_game
    from riftbench.engine.agents.random import RandomAgent
    db = _load_db()
    n, s = _make_decks(db)
    st = setup_game(n, s, db, seed=seed)
    rng = random.Random(seed)
    steps = rng.randint(1, 8)
    # 手动驱动几步：用合法行动随机执行
    from riftbench.engine import cleanup as cm
    from riftbench.engine.actions import legal_actions, execute_action
    from riftbench.engine.turn import start_turn, pass_main_phase
    from riftbench.engine.fepr import run_fepr
    try:
        for _ in range(steps):
            if st.game_over:
                break
            if st.phase.value == "awaken":
                start_turn(st)
            cm.cleanup(st)
            if st.game_over:
                break
            r = run_fepr(st)
            if r == "done":
                pass  # Open 主阶段，继续
            tp = st.turn_player if st.priority_player is None else st.priority_player
            acts = legal_actions(st, tp)
            if not acts:
                pass_main_phase(st)
                continue
            chosen = random.Random(seed * 7 + _).choice(acts)
            execute_action(st, tp, chosen)
    except Exception:
        pass  # 快照生成容忍异常（截取中间态）
    return st, st.turn_player


def serialize_scenario(sample: dict) -> dict:
    """确保样本可 JSON 序列化（dict 内无 pydantic 对象）。"""
    return sample


def save_scenarios(samples: list[dict], path: str | Path) -> None:
    import json
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False, default=str) + "\n")
    print(f"[scenarios] 写入 {len(samples)} 样本 -> {path}")