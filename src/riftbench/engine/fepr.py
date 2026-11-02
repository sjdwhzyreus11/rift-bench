"""FEPR 循环（规则 332-340）+ Showdown 驱动（341-348）— 链与法术对决核心。

FEPR 四步（337-340）:
  Step 1 Finalize（337）: 最老 Pending（FIFO）逐项 finalize；Unit/Gear/Add 立即 Resolve（337.2），法术留链。
  Step 2 Execute（338）: 链上最新 Finalized 控制者获 Priority（337.4），可打 [Reaction] 或让过。
  Step 3 Pass（339）: 让过传给下一位；全让过（pass_streak≥玩家数）→ Step 4。
  Step 4 Resolve（340）: LIFO 结算最新 Finalized（340.1）→ 链空回 Open（340.2）。

Showdown（341-348）: 战斗 Showdown 由 combat.begin_combat 进入（enter_showdown + Attacker 获 Focus）。
  玩家在 Showdown Open 可打 [Action]/[Reaction] 或让过（showdown_passes）；全让过 → 关闭：
    战斗 → combat.proceed_after_showdown（伤害+结算）；非战斗 → leave_showdown。

对 driver 的契约：run_fepr(state) 返回
  'needs_decision' — priority/focus 玩家待决策（driver 让 agent 行动或 pass）
  'done'           — 链空且无 Showdown 需处理（继续正常回合循环）
"""
from __future__ import annotations

from riftbench.engine.errors import IllegalActionError
from riftbench.engine.model import PlayerId
from riftbench.engine.play import finalize_pending, resolve_immediately, resolve_spell
from riftbench.engine.state import ChainItem, GameState


def _pending_items(state: GameState) -> list[ChainItem]:
    return [c for c in state.chain if not c.finalized]


def _finalized_items(state: GameState) -> list[ChainItem]:
    return [c for c in state.chain if c.finalized]


def finalize_pending_items(state: GameState) -> None:
    """Step 1：FIFO 逐项 finalize 所有 Pending（337.1.b）。"""
    from riftbench.engine.effects.events import finalize_trigger_item
    while _pending_items(state):
        item = _pending_items(state)[0]
        if item.is_trigger:
            # 触发项：无费用/落点，直接标 finalized
            finalize_trigger_item(state, item)
            # Add 类触发已在 enqueue 时立即 resolve；其余留在链上
            continue
        try:
            finalize_pending(state, item)
        except IllegalActionError:
            continue  # finalize_pending 内部已移除该 Pending 并回滚


def grant_priority_after_finalize(state: GameState) -> None:
    """337.4：无 Pending → 链上最新 Finalized 控制者获 Priority。"""
    fin = _finalized_items(state)
    if not fin:
        return
    state.priority_player = fin[-1].player
    state.pass_streak = 0


def has_all_passed(state: GameState) -> bool:
    """339.1：所有玩家连续让过。"""
    return state.pass_streak >= len(state.turn_order)


def pass_action(state: GameState, pid: PlayerId) -> None:
    """统一让过（339/347.2）：Closed → pass_streak；Showdown Open → showdown_passes。"""
    if state.is_closed():
        state.pass_priority()
        state.pass_streak += 1
    elif state.is_showdown():
        state.pass_priority()
        state.showdown_passes += 1
    else:
        # Neutral Open：让过结束主阶段（turn 驱动）
        from riftbench.engine.turn import pass_main_phase
        pass_main_phase(state)


def resolve_top(state: GameState) -> None:
    """Step 4 Resolve（340）：LIFO 结算最新 Finalized。"""
    from riftbench.engine.effects.events import resolve_trigger_item
    fin = _finalized_items(state)
    if not fin:
        state.pass_streak = 0
        _after_resolve(state)
        return
    item = fin[-1]
    if item.is_trigger:
        # 触发项：执行 source 能力指令
        resolve_trigger_item(state, item)
        if item in state.chain:
            state.chain.remove(item)
    elif item.kind == "spell":
        resolve_spell(state, item)
    else:
        resolve_immediately(state, item)
    state.pass_streak = 0
    _after_resolve(state)


def _after_resolve(state: GameState) -> None:
    """链清空回 Open（340.2）+ Focus 轮转（346，MVP 简化触发/Add 链不轮转）。"""
    state.priority_player = None
    state.update_turn_state()
    if state.is_showdown() and not state.is_closed():
        if state.focus_player is not None and len(state.turn_order) > 1:
            idx = state.turn_order.index(state.focus_player)
            state.focus_player = state.turn_order[(idx + 1) % len(state.turn_order)]
            state.priority_player = state.focus_player


def close_showdown(state: GameState) -> None:
    """Showdown 全让过 → 关闭（348）。战斗 → 伤害+结算；非战斗 → 回 Neutral Open。"""
    bf_loc = state.showdown_location
    if bf_loc and state.is_showdown():
        from riftbench.engine.combat import proceed_after_showdown
        state.leave_showdown()
        proceed_after_showdown(state, bf_loc)
    else:
        state.leave_showdown()


def run_fepr(state: GameState) -> str:
    """驱动一步。返回 'needs_decision' 或 'done'。"""
    guard = 0
    while True:
        guard += 1
        if guard > 500:
            raise IllegalActionError("FEPR 死循环保护")

        # Step 1 Finalize 所有 Pending（含 Unit/Add 立即 resolve）
        finalize_pending_items(state)

        # Showdown Open 且无链：玩家让过循环（348）
        if state.is_showdown() and not state.is_closed():
            if state.showdown_passes >= len(state.turn_order):
                state.showdown_passes = 0
                close_showdown(state)
                continue  # 关闭后可能触发新战斗/链
            if state.priority_player is None:
                # Showdown Open：Focus 玩家获 Priority（335.1）
                if state.focus_player is not None:
                    state.priority_player = state.focus_player
                elif state.turn_order:
                    state.give_focus(state.turn_order[0])
            return "needs_decision"

        # 链处理
        if not state.chain:
            state.pass_streak = 0
            _after_resolve(state)
            return "done"

        # 有 Pending 未 finalize（finalize 失败）→ 保护
        if _pending_items(state):
            raise IllegalActionError("存在无法 finalize 的 Pending 项")

        # 只有 Finalized 项
        if state.priority_player is None or has_all_passed(state):
            if state.priority_player is None:
                grant_priority_after_finalize(state)
            if has_all_passed(state):
                resolve_top(state)
                continue
            return "needs_decision"
        return "needs_decision"