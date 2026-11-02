"""清理步骤（规则 318/320-324）。

清理固定步骤（323，顺序不可乱）——MVP 实现子集:
  323.1  判胜（分数≥胜利分且高于所有对手）
  323.5  有致命伤害的 Unit 死亡，进 Owner 废牌堆
  323.6  玩家失去对"无自己 Unit"且开环无战斗/对决中战场的控制（夺还）
  323.7  纠正性召回（MVP 简化为空——无 P2 的贴附/待命机制）
  323.8/323.9  Stage Showdown/Combat（Contested 战场）
  323.13  Neutral Open + Staged Combat → Turn Player 选战场开始 Combat

支持级联（322）与 Special Cleanup（324）: cleanup(state, special_steps=[])。

320/321: 清理期间不能 Finalize/Resolve 结算链物品（MVP 单态无链，天然满足）。
"""
from __future__ import annotations

from riftbench.engine.model import ControlStatus, PlayerId, ZoneType, readiness
from riftbench.engine.state import GameState
from riftbench.engine.scoring import check_victory


def cleanup(state: GameState, special_steps: list[tuple[str, str]] | None = None,
            _depth: int = 0) -> None:
    """执行一轮清理。special_steps 为 (step_id, loc) 列表（324 战斗/回合结束特殊步骤）。
    _depth 限制递归级联（322），防止无限循环。"""
    if _depth > 25:
        # 防御：级联过深（理论不应发生；P2 触发更完整后需复查）
        return
    # 320: 清理期间不能 Finalize/Resolve 链物品——MVP 单态无链，天然满足。

    # 323.1 判胜
    check_victory(state)

    # 323.5 致命伤害单位死亡
    _kill_lethal_units(state)

    # 323.6 战场控制夺还：玩家失去对"无自己 Unit"战场的控制（MVP 开环，无战斗中断）
    _reclaim_battlefields(state)

    # 324 特殊步骤（战斗清理在 combat.py 内联；此处接收回合结束特殊步骤等）
    # （317.2 回合结束清理的 heal/expire/pool 由 turn 直接处理，不在此）

    # 323.8/323.9 Stage Combat：Contested 战场检查敌我 Unit
    from riftbench.engine.combat import stage_combats, pick_staged_combat, begin_combat
    stage_combats(state)

    # 323.13 Neutral Open + Staged Combat → Turn Player 选战场开始（MVP：逐个触发）
    staged = pick_staged_combat(state)
    if staged:
        for bf_loc in list(staged):
            if state.is_closed():
                break  # 320: 链有物则不可（MVP 不会发生）
            before = _state_signature(state)
            begin_combat(state, bf_loc)  # 进入战斗 Showdown（464），伤害在 Showdown 关闭后
            # P2.2: begin_combat 只开启 Showdown（enter_showdown），不产生伤害。
            # 若已进入 Showdown → 暂停清理，交由 driver 驱动响应窗口（fepr）。
            if state.is_showdown():
                return
            if _state_signature(state) == before:
                bf = state.battlefields.get(bf_loc)
                if bf is not None:
                    bf.staged_combat = False
                continue
            # 战斗后再次清理级联（322）
            cleanup(state, _depth=_depth + 1)


def _state_signature(state: GameState) -> tuple:
    """一个轻量的状态签名，用于检测清理级联是否产生了新变化。"""
    return (
        tuple(sorted((o.runtime_id, o.zone.value, o.location_id, o.damage)
                     for o in state.objects.values())),
        tuple(sorted((b.location_id, b.controller.value if b.controller else None, b.status.value)
                     for b in state.battlefields.values())),
    )


def _kill_lethal_units(state: GameState) -> None:
    """323.5: 场上伤害≥战力的单位死亡进废牌堆。P2.1: 死亡前掷死亡事件。"""
    from riftbench.engine.effects.manager import fire
    for rid, o in list(state.objects.items()):
        if not o.is_unit:
            continue
        if o.zone not in (ZoneType.BASE, ZoneType.BATTLEFIELD):
            continue
        if o.damage >= o.effective_might:
            # 死亡事件（Deathknell / When I die）——须在移除前触发
            fire(state, "die", source_obj=rid, player=o.owner, location=o.location_id)
            state.move_object(rid, ZoneType.TRASH, o.owner, None)


def _reclaim_battlefields(state: GameState) -> None:
    """323.6: 玩家失去对"无自己 Unit"且开环无战斗中的战场的控制。"""
    for bf_loc, bf in state.battlefields.items():
        if bf.status != ControlStatus.CONTROLLED:
            continue
        controller = bf.controller
        if controller is None:
            continue
        # 该控制者是否在该战场仍有单位
        units = state.units_at_battlefield(bf_loc)
        has_unit = any(o.controller == controller for o in units)
        if not has_unit:
            # 无单位 → 夺还：变为 OPEN（MVP；若另一方有单位则进行了战斗处理）
            bf.controller = None
            bf.status = ControlStatus.OPEN
            bf.contested_by = None