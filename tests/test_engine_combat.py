"""简化战斗测试（规则 459-466）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.engine.model import ControlStatus, GameObject, PlayerId, ZoneType, readiness
from _engine_helpers import DB


def _make(state, pid, loc, might, name, energy=0):
    """构造一个指定战力的单位进某位置。"""
    card = next((c for c in DB.cards if not c.is_variant
                 and any(t.value == "unit" for t in c.static.types)
                 and (c.static.might or 0) == might and c.static.set_id.value == "OGN"), None)
    if card is None:
        card = next(c for c in DB.cards if not c.is_variant
                    and any(t.value == "unit" for t in c.static.types))
    rid = state.new_runtime_id()
    g = GameObject.from_card(rid, card, pid, pid, ZoneType.BATTLEFIELD, loc)
    g.might = might
    g.readiness = readiness.READY
    state.add_object(g)
    return g


def test_enter_open_battlefield_controls():
    """190.3.a.1: 单位进入 OPEN 战场 → 进入者控制战场。"""
    from _engine_helpers import make_state
    from riftbench.engine.combat import mark_battlefield_contested
    state = make_state()
    bf_loc = state.battlefield_order[0]
    _make(state, PlayerId.NORTH, bf_loc, 3, "u1")
    mark_battlefield_contested(state, bf_loc, PlayerId.NORTH)
    bf = state.battlefields[bf_loc]
    assert bf.status == ControlStatus.CONTROLLED
    assert bf.controller == PlayerId.NORTH


def test_opponent_entry_contests():
    """敌方单位进入已控战场 → CONTESTED。"""
    from _engine_helpers import make_state
    from riftbench.engine.combat import mark_battlefield_contested
    state = make_state()
    bf_loc = state.battlefield_order[0]
    state.battlefields[bf_loc].controller = PlayerId.NORTH
    state.battlefields[bf_loc].status = ControlStatus.CONTROLLED
    mark_battlefield_contested(state, bf_loc, PlayerId.SOUTH)
    assert state.battlefields[bf_loc].status == ControlStatus.CONTESTED
    assert state.battlefields[bf_loc].contested_by == PlayerId.SOUTH


def test_combat_stronger_attacker_wins():
    """同战场 5M 攻 vs 2M 守 → 进攻方全灭防守方，征服得分。"""
    from _engine_helpers import make_state
    from riftbench.engine.combat import begin_combat, mark_battlefield_contested
    from riftbench.engine.scoring import conquer_score
    from riftbench.engine.fepr import close_showdown
    state = make_state()
    bf_loc = state.battlefield_order[0]
    # 先北方控制战场，南方进入制造 Contested（南方为 Attacker）
    _make(state, PlayerId.NORTH, bf_loc, 2, "def")
    state.battlefields[bf_loc].controller = PlayerId.NORTH
    state.battlefields[bf_loc].status = ControlStatus.CONTROLLED
    _make(state, PlayerId.SOUTH, bf_loc, 5, "atk")
    mark_battlefield_contested(state, bf_loc, PlayerId.SOUTH)
    assert state.battlefields[bf_loc].status == ControlStatus.CONTESTED
    score_before = state.players[PlayerId.SOUTH].score
    begin_combat(state, bf_loc)   # 进入战斗 Showdown（464）
    assert state.is_showdown(), "战斗应进入 Showdown 态"
    close_showdown(state)         # 全部让过 → 关闭 → 伤害+结算（465/466）
    # 南方胜：5M 秒杀 2M
    bf = state.battlefields[bf_loc]
    assert bf.controller == PlayerId.SOUTH, "南方应确立控制"
    assert bf.status == ControlStatus.CONTROLLED
    assert state.players[PlayerId.SOUTH].score >= score_before


def test_combat_damage_assignment_lethal_priority():
    """465.2.c.3: 必须先给一个单位分配致命才能转下一个。"""
    from riftbench.engine.combat import _assign_damage
    from riftbench.cards.model import CardType
    # 3 个 2M 单位，5 点伤害：先给每个凑致命，余数给第一个仍存活
    mk = lambda i, m, n: GameObject(runtime_id=i, card_internal_id=f"x{i}",
        name=n, owner=PlayerId.NORTH, controller=PlayerId.NORTH,
        zone=ZoneType.BATTLEFIELD, location_id="bf",
        types=[CardType.UNIT], might=m, energy=0)
    a, b, c = mk(1, 2, "a"), mk(2, 2, "b"), mk(3, 2, "c")
    _assign_damage([a, b, c], 5)
    # 算法：先对 a:2 致命, b:2 致命(剩余5-住→但c.3要求先凑一个再转，实际逐个凑)，余1给最先仍存活
    # 实现逐个凑致命：a=2, b=2, c=1（每单位直接给到致命所需，余数给第一个未致命）
    assert (a.damage, b.damage, c.damage) in [(2, 2, 1), (2, 1, 2), (1, 2, 2)], \
        f"{a.damage},{b.damage},{c.damage} 应满足致命优先"


def test_assignment_never_overkills_when_other_targets():
    """465.2.c.4: 有其他目标时不能对单目标超额分配。"""
    from riftbench.engine.combat import _assign_damage
    from riftbench.cards.model import CardType
    mk = lambda i, m, n: GameObject(runtime_id=i, card_internal_id=f"x{i}",
        name=n, owner=PlayerId.NORTH, controller=PlayerId.NORTH,
        zone=ZoneType.BATTLEFIELD, location_id="bf",
        types=[CardType.UNIT], might=m, energy=0)
    a, b, c = mk(1, 3, "a"), mk(2, 3, "b"), mk(3, 3, "c")
    _assign_damage([a, b, c], 5)
    # 每人最多致命3，5分：a3,b2,c0（不超额给a）
    assert a.damage <= 3 and b.damage == 2 and c.damage == 0, f"{a.damage},{b.damage},{c.damage}"


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