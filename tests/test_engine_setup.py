"""setup 测试：初始布置（规则 110-118/485）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.engine.model import Phase, PlayerId, ZoneType
from _engine_helpers import make_state, make_two_decks, DB


def test_setup_players_and_zones():
    state = make_state(seed=42)
    assert set(state.players.keys()) == {PlayerId.NORTH, PlayerId.SOUTH}
    for pid in (PlayerId.NORTH, PlayerId.SOUTH):
        # 手牌4、主牌堆、符文牌堆12
        assert len(state.objects_in(pid, ZoneType.HAND)) == 4, "起手应4张"
        assert len(state.objects_in(pid, ZoneType.MAIN_DECK)) >= 36
        assert len(state.objects_in(pid, ZoneType.RUNE_DECK)) == 12
        # 传奇区与英雄区各1
        assert len(state.objects_in(pid, ZoneType.LEGEND)) == 1
        assert len(state.objects_in(pid, ZoneType.CHAMPION)) == 1


def test_setup_battlefields():
    state = make_state(seed=42)
    # 1v1 两个战场（485.4），初始 OPEN
    assert len(state.battlefields) == 2
    assert len(state.battlefield_order) == 2
    for bf in state.battlefields.values():
        assert bf.status.value == "open", "初始战场应为 OPEN（未被据守）"
        assert bf.controller is None


def test_turn_order_and_first():
    state = make_state(seed=42)
    # 回合队列两玩家，先手 is_first
    assert len(state.turn_order) == 2
    first = state.turn_order[0]
    assert state.players[first].is_first is True
    # 后手 extra_channel 标记
    second = state.turn_order[1]
    assert state.players[second].extra_channel_first_turn is True


def test_initial_phase():
    state = make_state(seed=42)
    assert state.phase == Phase.AWAKEN
    assert state.turn_number == 1
    assert state.victory_score == 8


def test_total_object_count_consistent():
    state = make_state(seed=42)
    # 2玩家×(1传奇+1英雄+4手牌+36主牌+12符文) + 2战场卡 = 2×54+2 = 110
    expected = 2 * (1 + 1 + 4 + 36 + 12) + 2
    assert len(state.objects) == expected, f"物体总数应为 {expected}，实得 {len(state.objects)}"


def test_deck_build_valid():
    n, s = make_two_decks()
    n.validate_counts()
    s.validate_counts()


def test_consistent_across_seeds():
    """不同 seed 产生不同起手（随机性生效），但结构一致。"""
    s1 = make_state(seed=1)
    s2 = make_state(seed=2)
    assert len(s1.objects) == len(s2.objects)
    # 至少 battlefields / rune decks 数一致
    assert len(s1.battlefields) == len(s2.battlefields)


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