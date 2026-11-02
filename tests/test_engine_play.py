"""打出流程与费用测试（规则 349-359/131/201-206/356/444/164.2.a）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.engine.errors import IllegalActionError
from riftbench.engine.model import Phase, PlayerId, ZoneType, readiness
from _engine_helpers import make_state


def _set_main_turn(state):
    """进入回合玩家的主阶段。"""
    state.phase = Phase.MAIN


def test_play_zero_cost_unit_to_base():
    """打出0费单位：进场到基地、休眠（143.4）。"""
    from riftbench.engine.play import play_card
    state = make_state(seed=42)
    tp = state.turn_player
    _set_main_turn(state)
    # 找手牌中的0费单位
    unit_in_hand = [o for o in state.objects_in(tp, ZoneType.HAND) if o.is_unit and (o.energy or 0) == 0]
    if not unit_in_hand:
        return  # 该 seed 起手无0费单位，跳过（不视为失败）
    obj = unit_in_hand[0]
    base_before = len(state.objects_in(tp, ZoneType.BASE))
    res = play_card(state, tp, obj.runtime_id, f"base:{tp.value}")
    assert res.kind == "unit"
    assert len(state.objects_in(tp, ZoneType.BASE)) == base_before + 1
    o2 = state.objects[obj.runtime_id]
    assert o2.zone == ZoneType.BASE
    assert o2.readiness == readiness.EXHAUSTED, "单位进场应休眠（143.4）"


def test_play_spell_pays_cost_goes_trash():
    """法术：支付费用→进结算链→进废牌堆（359.3），不执行效果（MVP）。"""
    from riftbench.engine.play import play_card
    from riftbench.engine.costs import produce_mana_from_runes
    from riftbench.engine.model import readiness
    state = make_state(seed=42)
    tp = state.turn_player
    _set_main_turn(state)
    spell_in_hand = [o for o in state.objects_in(tp, ZoneType.HAND) if o.is_spell]
    if not spell_in_hand:
        return  # 无法术跳过
    spell = spell_in_hand[0]
    cost = spell.energy or 0
    # 先召出符文到基地再产法力支付
    rune_zone = state.zones[tp][ZoneType.RUNE_DECK]
    for _ in range(3):
        if rune_zone.objects:
            rid = rune_zone.objects[-1]
            state.move_object(rid, ZoneType.BASE, tp, f"base:{tp.value}")
            state.objects[rid].readiness = readiness.READY
    produced = produce_mana_from_runes(state, tp, 3)
    assert produced == 3, "应能召出符文并产法力"
    mana_before = state.players[tp].rune_pool.mana
    trash_before = len(state.objects_in(tp, ZoneType.TRASH))
    res = play_card(state, tp, spell.runtime_id, None)
    assert res.kind == "spell"
    assert len(state.objects_in(tp, ZoneType.TRASH)) == trash_before + 1, "法术应进废牌堆"
    assert state.get_object(spell.runtime_id) is not None
    assert state.objects[spell.runtime_id].zone == ZoneType.TRASH
    # 费用已扣（法力消耗了 cost）
    assert state.players[tp].rune_pool.mana == mana_before - cost


def test_play_illegal_wrong_phase():
    """非主阶段打出应非法。"""
    from riftbench.engine.play import play_card
    state = make_state(seed=42)
    tp = state.turn_player
    assert state.phase == Phase.AWAKEN  # setup 后未进主阶段
    unit = [o for o in state.objects_in(tp, ZoneType.HAND) if o.is_unit][0]
    try:
        play_card(state, tp, unit.runtime_id, f"base:{tp.value}")
        assert False, "非主阶段打出应抛 IllegalActionError"
    except IllegalActionError:
        pass
    # 原子回滚：物体仍回手牌
    assert state.objects[unit.runtime_id].zone == ZoneType.HAND


def test_play_insufficient_mana_rolls_back():
    """费用不足：原子回滚（358.5），卡牌回手、池不扣。"""
    from riftbench.engine.play import play_card
    state = make_state(seed=42)
    tp = state.turn_player
    _set_main_turn(state)
    # 2费单位，池空且无可用符文
    unit = [o for o in state.objects_in(tp, ZoneType.HAND) if o.is_unit and (o.energy or 0) >= 2]
    if not unit:
        return
    obj = unit[0]
    mana_before = state.players[tp].rune_pool.mana
    try:
        play_card(state, tp, obj.runtime_id, f"base:{tp.value}")
        assert False, "费用不足应抛异常"
    except IllegalActionError:
        pass
    assert state.objects[obj.runtime_id].zone == ZoneType.HAND, "卡牌应回手（回滚）"
    assert state.players[tp].rune_pool.mana == mana_before


def test_base_rune_produces_mana():
    """164.2.a: 基础符文横置产出1法力。"""
    from riftbench.engine.costs import produce_mana_from_runes
    state = make_state(seed=42)
    tp = state.turn_player
    # 放一个基础符文到基地
    if not state.objects_in(tp, ZoneType.RUNE_DECK):
        return
    rune_zone = state.zones[tp][ZoneType.RUNE_DECK]
    rid = rune_zone.objects[-1]
    state.move_object(rid, ZoneType.BASE, tp, f"base:{tp.value}")
    obj = state.objects[rid]
    obj.readiness = readiness.READY
    mana_before = state.players[tp].rune_pool.mana
    produced = produce_mana_from_runes(state, tp, 1)
    assert produced == 1
    assert state.players[tp].rune_pool.mana == mana_before + 1
    assert obj.readiness == readiness.EXHAUSTED, "横置符文产出后应变为横置"


def test_legal_actions_include_move_when_unit_ready():
    """合法行动包含标准移动（单位活跃可移动）。"""
    from riftbench.engine.actions import legal_actions
    from riftbench.engine.model import ControlStatus
    state = make_state(seed=42)
    tp = state.turn_player
    _set_main_turn(state)
    # 放一个活跃单位到基地
    if not state.objects_in(tp, ZoneType.HAND):
        return
    unit = [o for o in state.objects_in(tp, ZoneType.HAND) if o.is_unit][0]
    state.move_object(unit.runtime_id, ZoneType.BASE, tp, f"base:{tp.value}")
    state.objects[unit.runtime_id].readiness = readiness.READY
    acts = legal_actions(state, tp)
    moves = [a for a in acts if a["type"] == "move"]
    assert len(moves) >= 1, "活跃单位应有移动行动"
    assert moves[0]["to_location_id"] in state.battlefields


def test_standard_move_exhausts_unit():
    """标准移动横置单位（144.2）。"""
    from riftbench.engine.actions import execute_action
    from riftbench.engine.model import ControlStatus
    state = make_state(seed=42)
    tp = state.turn_player
    _set_main_turn(state)
    unit = [o for o in state.objects_in(tp, ZoneType.HAND) if o.is_unit][0]
    rid = unit.runtime_id
    state.move_object(rid, ZoneType.BASE, tp, f"base:{tp.value}")
    state.objects[rid].readiness = readiness.READY
    bf_loc = state.battlefield_order[0]
    execute_action(state, tp, {"type": "move", "unit_runtime_id": rid, "to_location_id": bf_loc})
    o = state.objects[rid]
    assert o.zone == ZoneType.BATTLEFIELD and o.location_id == bf_loc
    assert o.readiness == readiness.EXHAUSTED, "移动应横置单位"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}"); failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)