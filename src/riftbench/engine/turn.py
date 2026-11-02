"""回合驱动（规则 315-317 + 302-306）。

回合流程:
  315.1 Awaken 阶段: 回合玩家读直自己控制的所有可读直物体（解横置）。
  315.2 Beginning 阶段:
    a. 开始步骤（MVP 空接口 315.2.a.1）
    b. 得分步骤（315.2.b.2）: 回合玩家对所有控制战场执行 Hold 据守
    c. 召出阶段（315.3.b）: 从符文牌堆顶 Channel 2（后手首回合 +1）
    d. 抽牌阶段（315.4.b）: 抽1；牌堆空则 Burn Out
  316 Main 阶段: 开主阶段前所有玩家符文池清空(316.3)；玩家自由行动直到 Pass
  317 Ending 阶段: 结束步骤(空) → 失效步骤(heal/pool清空)

MVP: 主阶段由 driver/agent 循环调用 legal_actions/execute_action，直到 pass。
MUlligan: 首回合由 driver 在处理前调用。
"""
from __future__ import annotations

from riftbench.engine.errors import GameOver
from riftbench.engine.model import Phase, PlayerId, ZoneType, readiness
from riftbench.engine.state import GameState
from riftbench.engine.scoring import hold_score, cycle_turn_scored_tracking


def start_turn(state: GameState) -> None:
    """开始回合玩家的新一轮。返回当前回合玩家。"""
    tp = state.turn_player
    state.phase = Phase.AWAKEN

    # 315.1 Awaken: 读直
    _awaken(state, tp)

    # 315.2 Beginning
    state.phase = Phase.BEGINNING
    _beginning_phase(state, tp)

    # 315.2.b 得分步骤（Hold）
    _holding_step(state, tp)

    # 315.3 召出阶段（Channel）
    _channel_phase(state, tp)

    # 315.4 抽牌阶段
    _draw_phase(state, tp)

    # 316 Main
    state.phase = Phase.MAIN
    # 316.3 开主阶段前所有玩家符文池清空
    state.clear_rune_pools_all()


def _awaken(state: GameState, tp: PlayerId) -> None:
    """唤醒阶段: 回合玩家读直自己控制的所有单位/装备（解除横置）。"""
    for o in state.objects.values():
        if o.controller == tp and o.readiness == readiness.EXHAUSTED:
            if o.is_unit or o.is_gear:
                o.readiness = readiness.READY


def _beginning_phase(state: GameState, tp: PlayerId) -> None:
    """315.2.a 开始步骤: MVP 空（触发留 P2）。"""


def _holding_step(state: GameState, tp: PlayerId) -> None:
    """315.2.b 得分步骤: 回合玩家对控制的每个战场执据守。"""
    for bf_loc, bf in state.battlefields.items():
        if bf.controller == tp and bf.status.value == "controlled":
            hold_score(state, tp, bf_loc)


def _channel_phase(state: GameState, tp: PlayerId) -> None:
    """315.3 召出阶段: 从符文牌堆顶 Channel 2 张（后手首回合 +1）。
    符能进场到基地，默认活跃（430.2.a）。"""
    player = state.players[tp]
    n = 2
    if player.extra_channel_first_turn and state.is_first_turn_of_game:
        n = 3  # 485.7 后手首回合额外 Channel 1
        player.extra_channel_first_turn = False  # 仅首回合
    base_loc = f"base:{tp.value}"
    rune_zone = state.zones[tp][ZoneType.RUNE_DECK]
    for _ in range(n):
        if not rune_zone.objects:
            break
        rid = rune_zone.objects[-1]
        obj = state.objects[rid]
        state.move_object(rid, ZoneType.BASE, tp, base_loc)
        obj.readiness = readiness.READY  # 430.2.a Channel 默认活跃


def _draw_phase(state: GameState, tp: PlayerId) -> None:
    """315.4 抽牌阶段: 抽1；主牌堆空则 Burn Out。P2.1: 抽牌后触发抽牌事件。"""
    from riftbench.engine.effects.manager import fire
    main_zone = state.zones[tp][ZoneType.MAIN_DECK]
    if main_zone.objects:
        rid = main_zone.objects[-1]
        state.move_object(rid, ZoneType.HAND, tp, None)
        fire(state, "draw", player=tp)
    else:
        # 燃尽（431.2）: 若废牌堆有牌先回收；无则反复燃尽给对手1分
        _handle_burnout(state, tp)


def _handle_burnout(state: GameState, tp: PlayerId) -> None:
    """抽牌阶段燃尽（431）。MVP 简化: 回收→对手+1→若仍空则反复。"""
    opponent = state.opponent_of(tp)
    trash_zone = state.zones[tp][ZoneType.TRASH]
    main_zone = state.zones[tp][ZoneType.MAIN_DECK]
    # 把废牌堆洗回主牌堆
    if trash_zone.objects:
        trash_ids = list(trash_zone.objects)
        state.rng.shuffle(trash_ids)
        # 移回主牌堆（作为新牌堆）
        for rid in trash_ids:
            state.move_object(rid, ZoneType.MAIN_DECK, tp, None)
        main_zone.objects[:] = trash_ids + [r for r in main_zone.objects if r not in trash_ids]
        # 抽1
        rid = main_zone.objects[-1]
        state.move_object(rid, ZoneType.HAND, tp, None)
    else:
        # 废牌堆也空 → 燃尽（431.3），给对手1分直到对方≥胜利线或字面无牌可抽
        while not main_zone.objects and not trash_zone.objects:
            state.players[opponent].add_score(1)
            opp = state.players[opponent]
            if (opp.score >= state.victory_score and all(
                    p.player_id == opponent or p.score < opp.score
                    for p in state.players.values())):
                state.winner = opponent
                state.game_over = True
                raise GameOver(opponent.value, "燃尽方无牌可抽，对手胜")
            break  # MVP 简化：每轮至多给1分（防死循环）；真实规则会反复燃尽但 MVP 以一次为准


def pass_main_phase(state: GameState) -> None:
    """玩家让过，结束主阶段流转到 Ending Phase。由 driver 在 agent 返回 pass 后调用。"""
    tp = state.turn_player
    state.phase = Phase.ENDING
    _ending_phase(state, tp)


def _ending_phase(state: GameState, tp: PlayerId) -> None:
    """317 Ending 阶段: 结束步骤(空)→失效步骤(317.2)。"""
    # 317.2.b Heal 所有 Unit
    for o in state.objects.values():
        if o.is_unit and o.zone in (ZoneType.BASE, ZoneType.BATTLEFIELD):
            o.damage = 0
    # 317.2.c "this turn" 效果过期（临时战力/眩晕/授予关键字）
    from riftbench.engine.effects.keywords import clear_turn_state, expire_temporary
    clear_turn_state(state)
    expire_temporary(state, tp)
    # 317.2.d 所有玩家符文池清空
    state.clear_rune_pools_all()
    # 清理"本回合已得分"记账（下一回合用）
    cycle_turn_scored_tracking(state)
    # 317.3 移交回合
    _advance_turn(state)


def _advance_turn(state: GameState) -> None:
    """回合队列下一位成为 Turn Player（317.3）。"""
    state.turn_player_index = (state.turn_player_index + 1) % len(state.turn_order)
    state.turn_number += 1
    state.is_first_turn_of_game = False
    state.phase = Phase.AWAKEN