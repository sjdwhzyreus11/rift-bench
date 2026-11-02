"""T6 战斗结算预测 — 给定战斗局面预测结果。

样本: 战斗局面（战场双方单位战力）+ 谁攻击 → 预测 {胜者/存活/控制/征服得分}。

引擎正答: 在副本上 begin_combat + 关闭 Showdown → 记录结果字段。
"""
from __future__ import annotations

from riftbench.engine.model import ControlStatus, GameObject, PlayerId, ZoneType
from riftbench.engine.state import GameState


def _load_db():
    from riftbench.cards import CardDatabase
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    return CardDatabase.load(root / "data" / "cards" / "cards.json")


def _mk_unit(state: GameState, pid: PlayerId, bf_loc: str, might: int) -> GameObject:
    """构造指定战力单位放到战场。"""
    db = _load_db()
    card = next((c for c in db.cards if not c.is_variant
                 and any(t.value == "unit" for t in c.static.types)
                 and (c.static.might or 0) == might), None)
    if card is None:
        card = next(c for c in db.cards if not c.is_variant
                    and any(t.value == "unit" for t in c.static.types))
    rid = state.new_runtime_id()
    g = GameObject.from_card(rid, card, pid, pid, ZoneType.BATTLEFIELD, bf_loc)
    g.might = might
    state.add_object(g)
    return g


def _build_combat(state: GameState, rng):
    """构造 Contested 战斗局面。返回 (bf_loc, attacker, defender)。"""
    bf_loc = state.battlefield_order[0]
    north, south = PlayerId.NORTH, PlayerId.SOUTH
    # 北方先控，南方进入制造 Contested（南方=攻击方）
    a_might, d_might = rng.choice([(3, 1), (5, 2), (2, 2), (1, 3)])
    state.battlefields[bf_loc].controller = north
    state.battlefields[bf_loc].status = ControlStatus.CONTROLLED
    _mk_unit(state, north, bf_loc, d_might)   # 防守方
    _mk_unit(state, south, bf_loc, a_might)   # 攻击方
    state.battlefields[bf_loc].status = ControlStatus.CONTESTED
    state.battlefields[bf_loc].contested_by = south
    return bf_loc, south, north


def _result_fields(state: GameState, bf_loc: str, attacker: PlayerId, defender: PlayerId) -> dict:
    bf = state.battlefields[bf_loc]
    survivors = {
        "north": [o for o in state.units_at_battlefield(bf_loc) if o.controller == PlayerId.NORTH],
        "south": [o for o in state.units_at_battlefield(bf_loc) if o.controller == PlayerId.SOUTH],
    }
    return {
        "controller": bf.controller.value if bf.controller else None,
        "status": bf.status.value,
        "north_survivors": len(survivors["north"]),
        "south_survivors": len(survivors["south"]),
        "north_score": state.players[PlayerId.NORTH].score,
        "south_score": state.players[PlayerId.SOUTH].score,
    }


def generate(state: GameState, viewpoint: PlayerId, rng, meta: dict | None = None) -> dict:
    from riftbench.engine.combat import begin_combat
    from riftbench.engine.fepr import close_showdown
    snap = state.snapshot()
    try:
        bf_loc, attacker, defender = _build_combat(state, rng)
        begin_combat(state, bf_loc)
        close_showdown(state)
        result = _result_fields(state, bf_loc, attacker, defender)
    except Exception:
        return None
    finally:
        state.restore(snap)
    return {
        "question": {"task": "T6", "battlefield": bf_loc, "attacker": attacker.value},
        "engine_answer": result,
        "meta": {"task": "T6", **(meta or {})},
    }


def answer(state: GameState, question: dict) -> dict:
    """引擎正答：在副本上构造并结算战斗。"""
    from riftbench.engine.combat import begin_combat
    from riftbench.engine.fepr import close_showdown
    from riftbench.engine.model import ControlStatus as CS, PlayerId
    snap = state.snapshot()
    try:
        bf_loc = question.get("battlefield")
        attacker = PlayerId(question.get("attacker"))
        defender = state.opponent_of(attacker)
        # 重建局面（question 含战场信息）
        state.battlefields[bf_loc].status = CS.CONTESTED
        state.battlefields[bf_loc].contested_by = attacker
        begin_combat(state, bf_loc)
        close_showdown(state)
        return _result_fields(state, bf_loc, attacker, defender)
    finally:
        state.restore(snap)