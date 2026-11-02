"""P2.3 深度规则测试 — 连续效果层 / 替换效果 / Counter / 依赖关键字。

覆盖:
  - 连续效果层（473-480）: +N[M] 持续修正、cost N less、免伤、层收敛
  - 替换效果（367-370）: prevent N 减伤、double 翻倍、damage_immune 免疫
  - Counter（425）: 反制法术进废牌堆不执行、防反卡不可反制
  - 依赖关键字（726-727）: [Empowered][>] / [Level N][>] 条件门控
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.engine.model import (
    ControlStatus, GameObject, Phase, PlayerId, ZoneType, readiness,
)
from _engine_helpers import make_state, DB


def _unit_card(might=2):
    return next(c for c in DB.cards if not c.is_variant
                and any(t.value == "unit" for t in c.static.types)
                and (c.static.might or 0) == might)


def _mk_unit(state, pid, card, loc, ready=True, might=None):
    rid = state.new_runtime_id()
    g = GameObject.from_card(rid, card, pid, pid, ZoneType.HAND)
    if might:
        g.might = might
    state.add_object(g)
    zone = ZoneType.BASE if loc.startswith("base") else ZoneType.BATTLEFIELD
    state.move_object(rid, zone, pid, loc)
    if ready:
        state.objects[rid].readiness = readiness.READY
    return rid


# ---------- 连续效果层（473-480） ----------

def test_continuous_might_mod():
    """连续效果 +N[M] 计入 effective_might。"""
    state = make_state(seed=42)
    tp = state.turn_player
    rid = _mk_unit(state, tp, _unit_card(2), f"base:{tp.value}")
    obj = state.objects[rid]
    obj.continuous_effects = [{"modifier": "might_plus", "value": 3}]
    from riftbench.engine.effects.continuous import recompute_continuous
    recompute_continuous(state, obj)
    assert obj.effective_might == 2 + 3, f"连续+M 应生效: {obj.effective_might}"


def test_continuous_cost_mod():
    """连续效果 cost N less 计入总费用。"""
    from riftbench.engine.costs import determine_total_cost
    state = make_state(seed=42)
    tp = state.turn_player
    rid = _mk_unit(state, tp, _unit_card(2), f"base:{tp.value}")
    obj = state.objects[rid]
    obj.energy = 5
    obj.continuous_effects = [{"modifier": "cost_minus", "value": 2}]
    from riftbench.engine.effects.continuous import recompute_continuous
    recompute_continuous(state, obj)
    assert determine_total_cost(obj) == 3, "cost N less 应生效"


def test_damage_immune():
    """免伤（连续效果层）：伤害被完全豁免。"""
    state = make_state(seed=42)
    tp = state.turn_player
    opp = state.opponent_of(tp)
    rid = _mk_unit(state, opp, _unit_card(2), f"base:{opp.value}")
    obj = state.objects[rid]
    obj.continuous_effects = [{"modifier": "damage_immune", "value": True}]
    from riftbench.engine.effects.continuous import recompute_continuous
    recompute_continuous(state, obj)
    assert obj.damage_immune is True
    # 被 deal 3 伤害 → 不受伤
    src_id = _mk_unit(state, tp, _unit_card(1), f"base:{tp.value}")
    from riftbench.engine.effects.executor import execute_ability
    ab = {"kind": "instruction", "instructions": [
        {"op": "deal", "target": {"relation": "enemy", "card_kind": "unit"}, "amount": 3}]}
    execute_ability(state, state.objects[src_id], ab)
    assert state.objects[rid].damage == 0, "免伤单位不应受伤"


# ---------- 替换效果（367-370） ----------

def test_prevent_damage():
    """prevent N 伤害减伤。"""
    from riftbench.engine.effects.replacement import apply_damage
    state = make_state(seed=42)
    tp = state.turn_player
    rid = _mk_unit(state, tp, _unit_card(2), f"base:{tp.value}")
    obj = state.objects[rid]
    obj.replacement_effects = [{"trigger": "damage", "replacement": "prevent", "value": 3}]
    # 5 伤害被 prevent 3 → 实际 2
    assert apply_damage(state, obj, 5) == 2
    # prevent 超出 → 0
    assert apply_damage(state, obj, 1) == 0


def test_double_damage():
    """double 伤害翻倍。"""
    from riftbench.engine.effects.replacement import apply_damage
    state = make_state(seed=42)
    tp = state.turn_player
    rid = _mk_unit(state, tp, _unit_card(2), f"base:{tp.value}")
    obj = state.objects[rid]
    obj.replacement_effects = [{"trigger": "damage", "replacement": "double", "value": 2}]
    assert apply_damage(state, obj, 3) == 6, "double 应翻倍"


def test_replacement_immune_overrides():
    """替换免疫伤害：返回 0。"""
    from riftbench.engine.effects.replacement import apply_damage
    state = make_state(seed=42)
    tp = state.turn_player
    rid = _mk_unit(state, tp, _unit_card(2), f"base:{tp.value}")
    obj = state.objects[rid]
    obj.replacement_effects = [{"trigger": "damage", "replacement": "damage_immune", "value": True}]
    assert apply_damage(state, obj, 9) == 0


# ---------- Counter（425） ----------

def test_counter_marks_target():
    """Counter 标记链上最近对手法术为 countered。"""
    from riftbench.engine.play import begin_play
    from riftbench.engine.fepr import finalize_pending_items
    from riftbench.engine.effects.executor import _op_counter
    state = make_state(seed=42)
    tp = state.turn_player
    opp = state.opponent_of(tp)
    state.phase = Phase.MAIN
    state.priority_player = tp
    state.players[tp].rune_pool.mana = 20
    # 对手打出非 Reaction 法术 → Finalize 留在链上
    opp_spell = next((o for o in state.objects_in(opp, ZoneType.HAND) if o.is_spell
                      and "Reaction" not in o.keywords), None)
    if opp_spell is None:
        return
    # 直接模拟：把对手的牌放到手牌再打
    begin_play(state, opp, opp_spell.runtime_id)
    finalize_pending_items(state)
    # 我方用 Counter 反制（_op_counter 标记最近非 Reaction 法术）
    _op_counter(state, tp)
    target = state.chain[-1]
    assert target.countered is True, "对手法术应被标记 countered"


def test_countered_spell_no_effect():
    """被 Counter 的法术结算时进废牌堆、不执行效果（425.1）。"""
    from riftbench.engine.play import resolve_spell
    from riftbench.engine.state import ChainItem
    state = make_state(seed=42)
    tp = state.turn_player
    spell = next((o for o in state.objects_in(tp, ZoneType.HAND) if o.is_spell), None)
    if spell is None:
        return
    rid = spell.runtime_id
    # 构造：法术在链上已 finalized 且被 counter
    item = ChainItem(runtime_id=rid, player=tp, finalized=True, kind="spell", countered=True)
    state.chain.append(item)
    # 结算前记录该卡效果是否影响状态（此处用 score 类法术难以直接断言，
    # 用 zone 断言：被 counter 的法术结算后进 trash 而非留链）
    resolve_spell(state, item)
    assert state.objects[rid].zone == ZoneType.TRASH, "被反制法术应进废牌堆"


def test_uncounterable_ignores_counter():
    """防反卡：Counter 不生效。"""
    from riftbench.engine.play import begin_play
    from riftbench.engine.fepr import finalize_pending_items
    from riftbench.engine.effects.executor import _op_counter
    state = make_state(seed=42)
    tp = state.turn_player
    opp = state.opponent_of(tp)
    state.phase = Phase.MAIN
    state.priority_player = tp
    state.players[tp].rune_pool.mana = 20
    opp_spell = next((o for o in state.objects_in(opp, ZoneType.HAND) if o.is_spell
                      and "Reaction" not in o.keywords), None)
    if opp_spell is None:
        return
    begin_play(state, opp, opp_spell.runtime_id)
    finalize_pending_items(state)
    state.chain[-1].uncounterable = True  # 防反修饰
    _op_counter(state, tp)
    assert state.chain[-1].countered is False, "防反卡不可被反制"


# ---------- 依赖关键字（726-727） ----------

def test_empowered_condition_gate():
    """[Empowered][>] 条件门：未强化不生效，强化后生效。"""
    from riftbench.engine.effects.executor import execute_ability
    state = make_state(seed=42)
    tp = state.turn_player
    rid = _mk_unit(state, tp, _unit_card(2), f"base:{tp.value}")
    obj = state.objects[rid]
    sb = state.players[tp].score
    # [Empowered][>] I score 1 —— 未 empowered 不执行
    ab = {"kind": "instruction", "condition_keyword": "Empowered",
          "instructions": [{"op": "score", "target": {}}]}
    execute_ability(state, obj, ab)
    assert state.players[tp].score == sb, "未强化时条件能力不应生效"
    # 强化后生效
    obj.empowered = True
    execute_ability(state, obj, ab)
    assert state.players[tp].score == sb + 1, "强化后条件能力应生效"


def test_level_condition_gate():
    """[Level N][>] 条件门：经验不足不生效，达标后生效。"""
    from riftbench.engine.effects.executor import execute_ability
    state = make_state(seed=42)
    tp = state.turn_player
    rid = _mk_unit(state, tp, _unit_card(2), f"base:{tp.value}")
    obj = state.objects[rid]
    sb = state.players[tp].score
    ab = {"kind": "instruction", "condition_keyword": "Level 3",
          "instructions": [{"op": "score", "target": {}}]}
    execute_ability(state, obj, ab)
    assert state.players[tp].score == sb, "xp<3 时不应生效"
    state.players[tp].xp = 3
    execute_ability(state, obj, ab)
    assert state.players[tp].score == sb + 1, "xp>=3 时应生效"


def test_parser_detects_condition_keyword():
    """parser 识别 [Empowered][>] 结构设 condition_keyword。"""
    from riftbench.engine.effects.parser import parse_card_effects
    r = parse_card_effects("[Empowered][>] I have +1 [M].", "x")
    assert r.abilities and r.abilities[0].condition_keyword == "Empowered"
    r2 = parse_card_effects("[Level 6][>] This costs [2] less.", "y")
    assert r2.abilities and r2.abilities[0].condition_keyword == "Level 6"


def test_continuous_parser():
    """parser 识别持续修正（+N[M] / costs N less / 免伤）。"""
    from riftbench.engine.effects.continuous import parse_continuous_effects
    eff = parse_continuous_effects("I have +2 [M]. I cost 1 less. I don't take damage.")
    mods = [e["modifier"] for e in eff]
    assert "might_plus" in mods
    assert "cost_minus" in mods
    assert "damage_immune" in mods


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {type(e).__name__} {e}"); failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)