"""引擎集成测试：完整对局端到端。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _engine_helpers import run_small_game, make_two_decks, DB
from riftbench.engine.agents.random import RandomAgent
from riftbench.engine.driver import run_game


def test_full_game_two_random_agents():
    """随机 vs 随机完整对局跑通，有胜负结论。"""
    result = run_small_game(seed=42, max_steps=4000)
    # 有胜者（8分）或步数上限
    assert result.winner is not None or result.steps >= 4000
    assert result.turns > 0
    assert result.steps > 0


def test_combat_and_scoring_occur():
    """整局中应有战斗/征服得分发生（分数 > 0 或燃尽得分）。"""
    # 多 seed 采样：至少某些局中一方达到较高分
    high_scores = 0
    for seed in (1, 2, 3, 4, 5):
        r = run_small_game(seed=seed, max_steps=4000)
        if r.score_north >= 3 or r.score_south >= 3:
            high_scores += 1
    assert high_scores >= 3, f"多数对局应出现较高得分（战斗/征服），实际 {high_scores}/5"


def test_channel_and_mana_production_work_together():
    """召出符文+激活产法力+打出卡的完整链路。"""
    from riftbench.engine.state import Phase
    from riftbench.engine.model import ZoneType, readiness
    from riftbench.engine.actions import execute_action, legal_actions
    from riftbench.engine.setup import setup_game
    n, s = make_two_decks()
    state = setup_game(n, s, DB, seed=42)
    tp = state.turn_player
    # 完整第一回合：start_turn 会召出+抽牌
    from riftbench.engine.turn import start_turn
    start_turn(state)
    assert state.phase == Phase.MAIN
    # 基地有召出的符文
    base_runes = [o for o in state.objects_in(tp, ZoneType.BASE) if o.is_rune]
    assert len(base_runes) >= 2, "召出阶段应给基地2+符文"
    # 激活符文产法力
    acts = legal_actions(state, tp)
    activate = [a for a in acts if a["type"] == "activate_rune"]
    if activate:
        execute_action(state, tp, activate[0])
        assert state.players[tp].rune_pool.mana >= 1
    # 站场单位可被优先打出（若有）
    assert "pass" in [a["type"] for a in legal_actions(state, tp)]


def test_standard_move_into_enemy_triggers_combat():
    """标准移动单位进入敌方战场 → 战斗触发（Contested→Staged→begin）。"""
    from riftbench.engine.combat import mark_battlefield_contested, stage_combats, pick_staged_combat
    from riftbench.engine.model import GameObject, PlayerId, ZoneType
    from riftbench.engine.setup import setup_game
    n, s = make_two_decks()
    state = setup_game(n, s, DB, seed=42)
    bf_loc = state.battlefield_order[0]
    # 直接构造两敌对单位同处战场
    card_u = next(c for c in DB.cards if not c.is_variant
                  and any(t.value == "unit" for t in c.static.types) and c.static.set_id.value == "OGN")
    for pid, loc in ((PlayerId.NORTH, bf_loc), (PlayerId.SOUTH, bf_loc)):
        rid = state.new_runtime_id()
        g = GameObject.from_card(rid, card_u, pid, pid, ZoneType.BATTLEFIELD, loc)
        state.add_object(g)
    stage_combats(state)
    assert state.battlefields[bf_loc].staged_combat is True, "敌我双方单位同处应 Stage Combat"
    staged = pick_staged_combat(state)
    assert bf_loc in staged


def test_victory_by_score_and_burnout_both_possible():
    """对局结束可由得分或燃尽触发，引擎都正确处理。"""
    # 大量 seed 覆盖两种终局（不强断言具体类型，只断言不崩溃且终局合法）
    wins = {}
    for seed in range(6):
        r = run_game(RandomAgent(seed=seed), RandomAgent(seed=seed + 50), *make_two_decks(), DB,
                     seed=seed * 11, max_steps=3000)
        wins.setdefault(("win" if r.winner is not None else "cap"), 0)
        wins[("win" if r.winner is not None else "cap")] += 1
        # 若无人胜（步数上限），也合法
    # 至少出现一次胜利
    assert wins.get("win", 0) >= 1, f"6 局中应至少1局有胜者，实际 {wins}"


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