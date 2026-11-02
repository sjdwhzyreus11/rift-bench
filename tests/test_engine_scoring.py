"""得分与胜负测试（规则 467-472/193-196/431）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.engine.errors import GameOver
from riftbench.engine.model import ControlStatus, PlayerId, ZoneType
from _engine_helpers import make_state


def test_scoring_not_negative():
    """194.4: 分数不为负。"""
    from riftbench.engine.model import Player
    p = Player(player_id=PlayerId.NORTH)
    p.add_score(1)
    assert p.score == 1
    assert p.score >= 0


def test_conquer_and_hold_tracking():
    """469/470: 征服得分与每战场每回合一次。"""
    from riftbench.engine.scoring import conquer_score, hold_score
    state = make_state(seed=42)
    tp = state.turn_player
    bf_loc = state.battlefield_order[0]
    state.battlefields[bf_loc].controller = tp
    state.battlefields[bf_loc].status = ControlStatus.CONTROLLED
    # 征服得分
    assert conquer_score(state, tp, bf_loc) is True
    assert state.players[tp].score == 1
    # 同一战场再征服 → False
    assert conquer_score(state, tp, bf_loc) is False
    # 据守同一战场 → False（本回合已记）
    assert hold_score(state, tp, bf_loc) is False


def test_score_two_battlefields_in_turn():
    """两个不同战场各得1分。"""
    from riftbench.engine.scoring import conquer_score
    state = make_state(seed=42)
    tp = state.turn_player
    for bf_loc in state.battlefield_order:
        state.battlefields[bf_loc].controller = tp
        state.battlefields[bf_loc].status = ControlStatus.CONTROLLED
    assert conquer_score(state, tp, state.battlefield_order[0]) is True
    assert conquer_score(state, tp, state.battlefield_order[1]) is True
    assert state.players[tp].score == 2


def test_final_point_restriction():
    """471.1.b: 离胜利线只差1分且未拿下全部战场 → 改为抽牌不得分。
    若本回合已覆盖全部战场得分点，则允许拿最后一分。"""
    from riftbench.engine.scoring import conquer_score
    state = make_state(seed=42)
    tp = state.turn_player
    state.players[tp].score = state.victory_score - 1  # 7
    # 只控制并征服一个战场，未拿下全部（2个）→ 改抽牌
    bf_loc = state.battlefield_order[0]
    state.battlefields[bf_loc].controller = tp
    state.battlefields[bf_loc].status = ControlStatus.CONTROLLED
    gained = conquer_score(state, tp, bf_loc)
    assert gained is False, "未拿下全部战场时最后一分应改为抽牌"
    assert state.players[tp].score == 7

    # 本回合已在另一战场得过分（scored 覆盖 bf1）+ 现在征服 bf0 → 允许最后一分
    state2 = make_state(seed=43)
    tp2 = state2.turn_player
    state2.players[tp2].score = state2.victory_score - 1
    other = state2.battlefield_order[1]
    state2.battlefields[other].controller = tp2
    state2.battlefields[other].status = ControlStatus.CONTROLLED
    state2.players[tp2].scored_battlefields_this_turn.add(other)  # 本回合已在 bf1 得分
    bf0 = state2.battlefield_order[0]
    state2.battlefields[bf0].controller = tp2
    state2.battlefields[bf0].status = ControlStatus.CONTROLLED
    assert conquer_score(state2, tp2, bf0) is True
    assert state2.players[tp2].score == 8


def test_check_victory():
    """472/323.1: 达到胜利分且高于对手 → GameOver。"""
    from riftbench.engine.scoring import check_victory
    state = make_state(seed=42)
    tp = state.turn_player
    opp = state.opponent_of(tp)
    state.players[tp].score = 8
    state.players[opp].score = 5
    try:
        check_victory(state)
        assert False, "应抛 GameOver"
    except GameOver as go:
        assert go.winner == tp.value


def test_victory_not_on_tie():
    """194.2: 同分不分胜负。"""
    from riftbench.engine.scoring import check_victory
    state = make_state(seed=42)
    for p in state.players.values():
        p.score = 8  # 双方同分
    try:
        check_victory(state)
        assert not state.game_over, "同分不应判胜"
    except GameOver:
        assert False, "同分不应抛 GameOver"


def test_burnout_gives_opponent_point():
    """431.2.c: 燃尽给对手1分。"""
    from riftbench.engine.turn import _handle_burnout
    state = make_state(seed=42)
    tp = state.turn_player
    opp = state.opponent_of(tp)
    opp_before = state.players[opp].score
    # 清空主牌堆与废牌堆
    state.zones[tp][ZoneType.MAIN_DECK].objects.clear()
    state.zones[tp][ZoneType.TRASH].objects.clear()
    state.rng = None  # 需要 rng 但这里只用 shuffle on empty
    import random
    state.rng = random.Random(1)
    _handle_burnout(state, tp)
    assert state.players[opp].score == opp_before + 1


def test_cycle_scored_tracking():
    """回合结束清除"本回合已得分"。"""
    from riftbench.engine.scoring import cycle_turn_scored_tracking
    state = make_state(seed=42)
    tp = state.turn_player
    state.players[tp].scored_battlefields_this_turn.add("bf:north")
    cycle_turn_scored_tracking(state)
    assert state.players[tp].scored_battlefields_this_turn == set()


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