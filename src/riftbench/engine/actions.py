"""玩家行动与合法性（规则 349-358/413-431/144-145/445, P2.2 状态机）。

行动类型（dict 表示，供 agent 提议与回放日志）:
  {"type": "play", "hand_runtime_id": int, "target_location_id": str|None}
  {"type": "move", "unit_runtime_id": int, "to_location_id": str}   # 标准移动
  {"type": "pass"}        # Closed/Showdown 中=让过优先权(339); Open=结束主阶段
  {"type": "activate_rune", "rune_runtime_id": int}                 # 横置符文产出法力
  {"type": "activate", "obj_id": int, "ability_idx": int}           # 主动技能

合法行动按四态状态机 + 优先权过滤:
  - Neutral Open: 回合玩家（持 Priority）可打出任意卡/移动/激活/符文
  - Neutral Closed: 仅持 Priority 者可打 [Reaction]（309.1.a）+ 让过
  - Showdown Open: 持 Focus 者可打 [Action]/[Reaction]（308.1.a）+ 让过
  - Showdown Closed: 仅 [Reaction]（309.1.a ∩ 308.1.a）+ 让过
"""
from __future__ import annotations

from typing import Optional

from riftbench.cards.model import CardType
from riftbench.engine.costs import can_pay_with_pool, determine_total_cost
from riftbench.engine.errors import IllegalActionError
from riftbench.engine.model import GameObject, Phase, PlayerId, ZoneType, readiness
from riftbench.engine.state import GameState


def can_act(state: GameState, pid: PlayerId) -> bool:
    """pid 当前是否有行动权（持有优先权，或 Neutral Open 回合玩家）。"""
    if state.priority_player is not None:
        return state.priority_player == pid
    # 无优先权：仅 Neutral Open 主阶段回合玩家可行动（335/310.1.a）
    return (not state.is_closed() and not state.is_showdown()
            and state.phase == Phase.MAIN and state.turn_player == pid)


def is_turn_player_can_act(state: GameState, pid: PlayerId) -> bool:
    """兼容旧名：主阶段开环回合玩家。"""
    return can_act(state, pid)


def legal_actions(state: GameState, pid: PlayerId) -> list[dict]:
    """枚举 pid 当前可执行的行动（按状态机 + 优先权过滤）。"""
    if not can_act(state, pid):
        return []

    actions: list[dict] = []
    closed = state.is_closed()
    showdown = state.is_showdown()

    # 手牌打出（按状态过滤 [Reaction]/[Action]）
    hand = state.objects_in(pid, ZoneType.HAND)
    base_loc = f"base:{pid.value}"
    for obj in hand:
        kws = _obj_keywords(state, obj)
        has_reaction = "Reaction" in kws
        has_action = "Action" in kws
        if closed and not has_reaction:
            continue  # Closed 态仅 [Reaction]
        if showdown and not closed and not (has_action or has_reaction):
            continue  # Showdown Open 仅 [Action]/[Reaction]
        cost = determine_total_cost(obj)
        if cost == 0 or can_pay_with_pool(state, pid, cost):
            if obj.is_spell:
                actions.append({"type": "play", "hand_runtime_id": obj.runtime_id,
                                "target_location_id": None})
            else:
                locs = [base_loc] if obj.is_gear else [base_loc] + list(state.battlefields.keys())
                for loc in dict.fromkeys(locs):
                    actions.append({"type": "play", "hand_runtime_id": obj.runtime_id,
                                    "target_location_id": loc})

    if closed or showdown:
        # Closed/Showdown：标准移动/符文/主动技能不可（无 Discretionary 权）；只有让过
        actions.append({"type": "pass"})
        return actions

    # Neutral Open：主阶段全套行动
    for obj in state.objects.values():
        if (obj.controller == pid and obj.is_unit
                and obj.readiness == readiness.READY
                and obj.zone in (ZoneType.BASE, ZoneType.BATTLEFIELD)):
            if obj.zone == ZoneType.BASE:
                for bf_loc in state.battlefields:
                    actions.append({"type": "move", "unit_runtime_id": obj.runtime_id,
                                    "to_location_id": bf_loc})
            else:
                actions.append({"type": "move", "unit_runtime_id": obj.runtime_id,
                                "to_location_id": f"base:{pid.value}"})

    for obj in state.objects_in(pid, ZoneType.BASE):
        if obj.is_basic_rune and obj.readiness == readiness.READY:
            actions.append({"type": "activate_rune", "rune_runtime_id": obj.runtime_id})

    from riftbench.engine.effects.executor import can_activate
    for oid, abilities in state.ability_cache.items():
        obj = state.objects.get(oid)
        if obj is None or obj.controller != pid:
            continue
        if obj.zone not in (ZoneType.BASE, ZoneType.BATTLEFIELD):
            continue
        for ai, ab in enumerate(abilities):
            if ab.get("kind") != "activated":
                continue
            if can_activate(state, obj, ab):
                actions.append({"type": "activate", "obj_id": oid, "ability_idx": ai})

    actions.append({"type": "pass"})
    return actions


def _obj_keywords(state: GameState, obj: GameObject) -> list[str]:
    from riftbench.engine.effects.manager import ensure_parsed
    ensure_parsed(state, obj)
    return obj.keywords


def validate_action(state: GameState, pid: PlayerId, action: dict) -> None:
    """校验单个行动是否合法；不合法抛 IllegalActionError。直接重算全量再查。"""
    legal = legal_actions(state, pid)
    for la in legal:
        if _action_equal(la, action):
            return
    raise IllegalActionError(f"非法行动 {action} 对于玩家 {pid}")


def _action_equal(a: dict, b: dict) -> bool:
    if a.get("type") != b.get("type"):
        return False
    if a.get("type") == "play":
        return (a.get("hand_runtime_id") == b.get("hand_runtime_id")
                and a.get("target_location_id") == b.get("target_location_id"))
    if a.get("type") == "move":
        return (a.get("unit_runtime_id") == b.get("unit_runtime_id")
                and a.get("to_location_id") == b.get("to_location_id"))
    if a.get("type") == "activate_rune":
        return a.get("rune_runtime_id") == b.get("rune_runtime_id")
    if a.get("type") == "activate":
        return (a.get("obj_id") == b.get("obj_id")
                and a.get("ability_idx") == b.get("ability_idx"))
    return True  # pass 等无参行动


def execute_action(state: GameState, pid: PlayerId, action: dict) -> None:
    """执行已验证的行动。play → begin_play（入链）；pass → 让过/结束。"""
    from riftbench.engine.play import begin_play

    validate_action(state, pid, action)
    t = action["type"]
    if t == "play":
        begin_play(state, pid, action["hand_runtime_id"], action.get("target_location_id"))
    elif t == "move":
        _standard_move(state, pid, action["unit_runtime_id"], action["to_location_id"])
    elif t == "activate_rune":
        from riftbench.engine.costs import produce_mana_from_runes
        produce_mana_from_runes(state, pid, 1)
    elif t == "activate":
        from riftbench.engine.effects.executor import activate_ability
        ok = activate_ability(state, pid, action["obj_id"], action["ability_idx"])
        if not ok:
            raise IllegalActionError(f"主动技能无法激活 {action}")
    elif t == "pass":
        _handle_pass(state, pid)
    else:
        raise IllegalActionError(f"未知行动类型 {t}")


def _handle_pass(state: GameState, pid: PlayerId) -> None:
    """让过（339）：Closed/Showdown 中传优先权；Open 中由 turn 驱动结束主阶段。"""
    if state.is_closed() or state.is_showdown():
        from riftbench.engine.fepr import pass_action
        pass_action(state, pid)
    else:
        # Open 主阶段 pass → 结束主阶段（turn 驱动）
        from riftbench.engine.turn import pass_main_phase
        pass_main_phase(state)


def _standard_move(state: GameState, pid: PlayerId, unit_runtime_id: int,
                   to_location_id: str) -> None:
    """标准移动（规则 445/144.4）：基地↔战场；代价=横置该单位（144.2）。"""
    obj = state.objects.get(unit_runtime_id)
    if obj is None or not obj.is_unit or obj.controller != pid:
        raise IllegalActionError("移动目标不是己方单位")
    if obj.readiness != readiness.READY:
        raise IllegalActionError("单位已横置，不能移动")
    is_to_battlefield = to_location_id in state.battlefields
    current_on_board = obj.zone == ZoneType.BATTLEFIELD
    if is_to_battlefield == current_on_board:
        raise IllegalActionError(f"无效移动: {obj.zone} -> {to_location_id}")
    state.move_object(obj.runtime_id,
                      ZoneType.BATTLEFIELD if is_to_battlefield else ZoneType.BASE,
                      pid, to_location_id)
    obj.readiness = readiness.EXHAUSTED
    if is_to_battlefield:
        from riftbench.engine.combat import mark_battlefield_contested
        mark_battlefield_contested(state, to_location_id, pid)