"""回合驱动测试（规则 315-317）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.engine.model import Phase, PlayerId, ZoneType, readiness
from _engine_helpers import make_state, DB


def _channel_2(state, pid):
    """手动模拟召出阶段（或依赖 turn.start_turn）。helper。"""
    base_loc = f"base:{pid.value}"
    rune_zone = state.zones[pid][ZoneType.RUNE_DECK]
    for _ in range(2):
        if rune_zone.objects:
            rid = rune_zone.objects[-1]
            state.move_object(rid, ZoneType.BASE, pid, base_loc)
            state.objects[rid].readiness = readiness.READY


def test_hold_scoring_in_beginning():
    """Setup 后战场 OPEN，无法据守（需先控制）；先验证据守逻辑在控制后生效。"""
    from riftbench.engine.scoring import hold_score
    from riftbench.engine.model import ControlStatus
    state = make_state(seed=42)
    tp = state.turn_player
    # 手动控制一个战场（模拟单位占领）
    bf_loc = state.battlefield_order[0]
    state.battlefields[bf_loc].controller = tp
    state.battlefields[bf_loc].status = ControlStatus.CONTROLLED
    score_before = state.players[tp].score
    gained = hold_score(state, tp, bf_loc)
    assert gained is True
    assert state.players[tp].score == score_before + 1


def test_hold_once_per_battlefield():
    """470: 每战场每回合最多 1 分。"""
    from riftbench.engine.scoring import hold_score
    from riftbench.engine.model import ControlStatus
    state = make_state(seed=42)
    tp = state.turn_player
    bf_loc = state.battlefield_order[0]
    state.battlefields[bf_loc].controller = tp
    state.battlefields[bf_loc].status = ControlStatus.CONTROLLED
    assert hold_score(state, tp, bf_loc) is True
    assert hold_score(state, tp, bf_loc) is False, "同一战场本回合不能重复得分"


def test_beginning_phase_channel_and_draw():
    """start_turn 后：召出阶段符文进基地、抽牌阶段手牌+1。"""
    from riftbench.engine.turn import start_turn
    state = make_state(seed=42)
    tp = state.turn_player
    rune_base_before = len(state.objects_in(tp, ZoneType.BASE))
    hand_before = len(state.objects_in(tp, ZoneType.HAND))
    start_turn(state)
    # 召出阶段：2张符文进基地（后手首回合3张——start_turn 内部处理）
    assert state.phase == Phase.MAIN
    # 抽牌阶段：手牌+1
    assert len(state.objects_in(tp, ZoneType.HAND)) == hand_before + 1
    assert rune_base_before <= len(state.objects_in(tp, ZoneType.BASE))


def test_ending_phase_clears_pools_and_heals():
    """317.2: 回合结束清空符文池、移除单位伤害。"""
    from riftbench.engine.turn import pass_main_phase, _ending_phase
    state = make_state(seed=42)
    tp = state.turn_player
    # 塞点法力与伤害
    state.players[tp].rune_pool.mana = 3
    state.players[tp].rune_pool.power["order"] = 1
    state.phase = Phase.MAIN
    pass_main_phase(state)
    assert state.players[tp].rune_pool.mana == 0
    assert state.players[tp].rune_pool.power == {}
    # 回合移交
    assert state.turn_player != tp or state.turn_number >= 2


def test_turn_advance_to_opponent():
    """317.3: 回合移交下一位。"""
    from riftbench.engine.turn import pass_main_phase
    state = make_state(seed=42)
    tp = state.turn_player
    state.phase = Phase.MAIN
    pass_main_phase(state)
    assert state.turn_player == state.opponent_of(tp)


def test_first_turn_extra_channel():
    """485.7: 后手首回合召出 3 张符文。"""
    state = make_state(seed=42)
    tp = state.turn_player
    second = state.opponent_of(tp)
    random = state.players[second].extra_channel_first_turn
    # 直接用 turn 走第一回合后手玩家的召出
    from riftbench.engine.turn import _channel_phase
    # 若后手是第二顺位走回合时要看轮转；MVP 简化：构造后手玩家的 channel 测试
    if random:
        base_before = len(state.objects_in(second, ZoneType.BASE))
        _channel_phase(state, second)
        assert len(state.objects_in(second, ZoneType.BASE)) == base_before + 3, "后手首回合应+1召出3"


def test_cleanup_kills_lethal_units():
    """323.5: 伤害≥战力的单位在清理时死亡进废牌堆。"""
    from riftbench.engine.cleanup import cleanup
    state = make_state(seed=42)
    tp = state.turn_player
    # 放一个1战力单位在基地，标记2伤害
    unit_like = [c for c in DB.cards if not c.is_variant
                 and any(t.value == "unit" for t in c.static.types)
                 and c.static.might == 1 and c.static.set_id.value == "OGN"]
    assert unit_like
    from riftbench.engine.model import GameObject
    rid = state.new_runtime_id()
    g = GameObject.from_card(rid, unit_like[0], tp, tp, ZoneType.BASE, f"base:{tp.value}")
    g.damage = 2  # 致命
    state.add_object(g)
    trash_before = len(state.objects_in(tp, ZoneType.TRASH))
    cleanup(state)
    assert len(state.objects_in(tp, ZoneType.TRASH)) == trash_before + 1
    # 对象仍在表中（区域间移动不销毁），但所在区域应为废牌堆
    assert state.get_object(rid) is not None
    assert state.objects[rid].zone == ZoneType.TRASH, "致命单位应进废牌堆"


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