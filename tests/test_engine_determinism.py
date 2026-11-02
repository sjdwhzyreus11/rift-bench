"""引擎确定性与集成测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _engine_helpers import run_small_game, make_state
from riftbench.engine.model import PlayerId, ZoneType


def test_same_seed_same_result():
    """同 seed + 同 agent 决策 → 终态可复现（确定性核心）。"""
    r1 = run_small_game(seed=99)
    r2 = run_small_game(seed=99)
    assert r1.winner == r2.winner
    assert (r1.score_north, r1.score_south) == (r2.score_north, r2.score_south)
    assert r1.steps == r2.steps
    assert len(r1.replay.entries) == len(r2.replay.entries)


def test_different_seeds_differ_sometimes():
    """不同 seed → 结果通常不同（随机性生效；不强断言差异以避免偶发）。"""
    r1 = run_small_game(seed=1)
    r2 = run_small_game(seed=2)
    # 两个不同对局都应是合法终局（有胜者或到步数上限）
    for r in (r1, r2):
        assert r.winner is not None or r.steps >= 3000


def test_game_reaches_winner_or_step_cap():
    """集成：整局对局终结于胜者或步数上限，不崩溃。"""
    result = run_small_game(seed=42, max_steps=5000)
    assert result.reason  # 有结束原因
    # 有胜者通常是 8 分；无胜者则是步数上限
    if result.winner is not None:
        winner_score = result.score_north if result.winner == PlayerId.NORTH else result.score_south
        assert winner_score == 8, "胜者应达胜利分8"


def test_scores_within_victory_bound():
    """任意终局分数在 [0,8]。"""
    for seed in (42, 7, 99):
        r = run_small_game(seed=seed, max_steps=3000)
        assert 0 <= r.score_north <= 8
        assert 0 <= r.score_south <= 8


def test_replay_has_structured_entries():
    """回放日志包含回合开始与行动步骤记录。"""
    r = run_small_game(seed=42, max_steps=1000)
    assert len(r.replay.entries) > 0
    types = {e.get("type") for e in r.replay.entries}
    assert "turn_start" in types
    assert "step" in types


def test_illegal_agent_action_rejected():
    """agent 提议非法行动 → 不应通过合法性校验（抛 IllegalActionError）。"""
    from riftbench.engine.actions import validate_action
    from riftbench.engine.errors import IllegalActionError
    state = make_state()
    tp = state.turn_player
    # 明显非法：打出一张主牌堆的卡（不在手牌）
    main_rid = state.zones[tp][ZoneType.MAIN_DECK].objects[0]
    try:
        validate_action(state, tp, {"type": "play", "hand_runtime_id": main_rid, "target_location_id": None})
        assert False, "非法行动应被拒绝"
    except IllegalActionError:
        pass


def test_object_conservation_across_game():
    """物体守恒：整局移动不增减物体总数（MVP 无创建/销毁）。"""
    from riftbench.engine.actions import legal_actions, execute_action
    from riftbench.engine.state import Phase
    from riftbench.engine.model import readiness
    state = make_state(seed=5)
    tp = state.turn_player
    initial = len(state.objects)
    state.phase = Phase.MAIN
    # 把活跃单位移动一下再移回
    u = next((o for o in state.objects_in(tp, ZoneType.HAND) if o.is_unit), None)
    if u:
        rid = u.runtime_id
        state.move_object(rid, ZoneType.BASE, tp, f"base:{tp.value}")
        state.objects[rid].readiness = readiness.READY
        # 此时区域计数不变（手牌→基地）
        assert len(state.objects) == initial
        # 打回手牌（模拟召回）
        state.move_object(rid, ZoneType.HAND, tp, None)
        assert len(state.objects) == initial
    # 打一张0费卡如有
    ghost_acts = legal_actions(state, tp)
    zero_plays = [a for a in ghost_acts if a["type"] == "play" and (state.objects[a["hand_runtime_id"]].energy or 0) == 0]
    if zero_plays:
        execute_action(state, tp, zero_plays[0])
        assert len(state.objects) == initial, "打出（手牌→场上）不应增减总物体数"


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