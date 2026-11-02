"""得分与胜负（规则 467-472, 193-196, 431）。

得分方式:
  - Hold 据守（469.2）: Beginning Phase 中回合玩家对维持控制的战场得分。
  - Conquer 征服（469.1）: 获得一个本回合未得分的战场控制权时得分。
  470: 每战场每回合通过任一方式最多 1 分。
  471.1.b: Conquer 时离胜利线只差 1 分且未拿下全部战场 → 改为抽 1 牌。
  472/194.2: 清理时分数≥胜利分且高于所有对手 → 获胜。
  431: Burn Out（燃尽）。

MVP 触发接口: hold_conquer_trigger(state, pid, bf_loc) 是 P2 征服/据守效果的钩子，MVP 为空。
"""
from __future__ import annotations

from riftbench.engine.errors import GameOver
from riftbench.engine.model import PlayerId, ZoneType
from riftbench.engine.state import GameState


def _already_scored(state: GameState, pid: PlayerId, bf_loc: str) -> bool:
    return bf_loc in state.players[pid].scored_battlefields_this_turn


def _mark_scored(state: GameState, pid: PlayerId, bf_loc: str) -> None:
    state.players[pid].scored_battlefields_this_turn.add(bf_loc)


def hold_score(state: GameState, pid: PlayerId, bf_loc: str) -> bool:
    """据守得分（469.2）。回合玩家在 Beginning 阶段对已控制的战场执行。
    返回是否得分。MVP: 若战场是 OPEN（无控制者）不算据守。
    P2.1: 得分后触发据守事件（Hold Effects, 383.4.d）。
    """
    bf = state.battlefields.get(bf_loc)
    if bf is None:
        return False
    # 据守需要该战场被 pid 控制且本回合未得分（规则 469.2）
    if bf.controller != pid or bf.status.value != "controlled":
        return False
    if _already_scored(state, pid, bf_loc):
        return False
    gain = _score_point(state, pid, bf_loc)
    if gain:
        _mark_scored(state, pid, bf_loc)
        _fire_ability_event(state, "hold", pid, bf_loc)
    return gain


def conquer_score(state: GameState, pid: PlayerId, bf_loc: str) -> bool:
    """征服得分（469.1）。玩家获得本回合未得分战场的控制权时调用。
    返回是否得分。P2.1: 得分后触发征服事件（Conquer Effects, 383.4.c）。
    """
    if _already_scored(state, pid, bf_loc):
        return False
    gain = _score_point(state, pid, bf_loc)
    if gain:
        _mark_scored(state, pid, bf_loc)
        _fire_ability_event(state, "conquer", pid, bf_loc)
    return gain


def _fire_ability_event(state: GameState, kind: str, pid: PlayerId, bf_loc: str) -> None:
    """征服/据守后掷触发事件（仅对相关单位的在场触发）。"""
    from riftbench.engine.effects.manager import fire
    # 触发源：该控制者在场、即此战场（或任意场）的征服触发——由 events 匹配 subject/控制器
    fire(state, kind, player=pid, location=bf_loc)


def _score_point(state: GameState, pid: PlayerId, bf_loc: str) -> bool:
    """核心得分动作（规则 471）。应用 471.1.b 最后一分封顶。
    返回是否真正得 1 分（False = 改为抽1牌）。"""
    player = state.players[pid]
    # 471.1.b: 若玩家 score == victory_score - 1（离胜利线只差1分），且本回合未拿下全部战场，
    # 则改为抽1牌。
    if player.score >= state.victory_score - 1:
        all_locations = set(state.battlefields.keys()) or set(state.battlefield_order)
        if not all_locations.issubset(player.scored_battlefields_this_turn | {bf_loc}):
            # 改为抽1张（不执行"抽牌"副作用，仅占位：MVP 在抽牌阶段有独立逻辑；此处返回 False）
            return False
    # 正常得分（471.1: 最多 Gain 1 点）
    player.add_score(1)
    return True


def check_victory(state: GameState) -> None:
    """清理步骤判胜（323.1/472）。若玩家分数≥胜利分且高于所有对手 → GameOver。"""
    if state.game_over:
        return
    best = max(state.players.values(), key=lambda p: p.score)
    if best.score >= state.victory_score:
        # 高于所有对手
        if all(p.player_id == best.player_id or p.score < best.score
               for p in state.players.values()):
            state.winner = best.player_id
            state.game_over = True
            raise GameOver(best.player_id.value, "达到胜利分数且高于对手")


def burnout(state: GameState, pid: PlayerId) -> None:
    """燃尽（规则 431）: 主牌堆不够抽时——把废牌堆洗回主牌堆→选对手 Gain 1→补完余下。
    MVP: 由 draw 流程触发。431.3.c.1 反复燃尽超胜利线立即判胜。"""
    player = state.players[pid]
    zalopp = state.opponent_of(pid)
    trash_zone = state.zones[pid][ZoneType.TRASH]
    main_zone = state.zones[pid][ZoneType.MAIN_DECK]
    # 431.2.b: 把废牌堆洗回主牌堆（随机化）
    if trash_zone.objects:
        trash_ids = list(trash_zone.objects)
        state.rng.shuffle(trash_ids)
        for rid in trash_ids:
            state.move_object(rid, ZoneType.MAIN_DECK, pid, None)
            # 放回主牌堆顶？Burn Out 后主牌堆 = 废牌堆洗过，作为新牌堆顶顺序
        # merge: main_zone.objects 已 append，位置在尾部（视为牌堆底部）；洗后应作为整堆
        main_zone.objects = trash_ids + main_zone.objects
    # 431.2.c: 选对手 Gain 1 点
    state.players[zalopp].add_score(1)
    # 431.3.c.1: 反复燃尽中对手超胜利线 → 立即判胜（不等清理）
    opp = state.players[zalopp]
    if opp.score >= state.victory_score and all(
            p.player_id == zalopp or p.score < opp.score for p in state.players.values()):
        state.winner = zalopp
        state.game_over = True
        raise GameOver(zalopp.value, "燃尽致胜")


def cycle_turn_scored_tracking(state: GameState) -> None:
    """回合结束/新一轮开始时清除"本回合已得分"记账（470）。"""
    for p in state.players.values():
        p.scored_battlefields_this_turn.clear()