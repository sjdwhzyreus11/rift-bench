"""对局驱动器 — 编排回合、agent 行动、清理与胜负。

协议:
  agent.observe(state, viewpoint) -> observation  (state 的全量副本按隐私过滤后的视图)
  agent.propose(observation) -> action            (dict 行动)

流程:
  setup → (可选 mulligan) → 回合循环:
    turn.start_turn → Main 阶段 agent 循环（每行动后 cleanup）→ pass → ending
    直到胜负（GameOver）或步数上限。

回放日志: 每个决策点的 {turn, player, phase, observation摘要, legal_actions, action, result}。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from riftbench.engine import cleanup as cleanup_mod
from riftbench.engine.actions import legal_actions, execute_action
from riftbench.engine.errors import GameOver, IllegalActionError
from riftbench.engine.model import Phase, PlayerId
from riftbench.engine.setup import setup_game
from riftbench.engine.state import GameState
from riftbench.engine.turn import start_turn


class Agent(Protocol):
    def observe(self, state: GameState, viewpoint: PlayerId) -> object: ...
    def propose(self, observation: object) -> dict: ...


@dataclass
class ReplayLog:
    """对局回放日志。"""
    entries: list[dict] = field(default_factory=list)

    def record(self, **kw) -> None:
        self.entries.append(kw)


@dataclass
class GameResult:
    """对局结果。"""
    winner: Optional[PlayerId]
    reason: str
    turns: int
    steps: int
    score_north: int
    score_south: int
    replay: ReplayLog


def run_game(north: Agent, south: Agent, deck_north, deck_south, db,
             seed: int | None = None, max_steps: int = 10000,
             mulligan_north: Optional[list[int]] = None,
             mulligan_south: Optional[list[int]] = None) -> GameResult:
    """运行一局对局。返回 GameResult。

    P2.2 主循环：cleanup(任务/Showdown开启) → fepr(链/Showdown/优先权) → 决策者行动。
    """
    from riftbench.engine import fepr as fepr_mod
    state = setup_game(deck_north, deck_south, db, seed=seed)
    agents = {PlayerId.NORTH: north, PlayerId.SOUTH: south}
    replay = ReplayLog()
    steps = 0
    turns_done = 0

    try:
        while not state.game_over:
            tp = state.turn_player
            start_turn(state)
            turns_done += 1
            replay.record(type="turn_start", turn=turns_done, player=tp.value,
                          scores={p.value: state.players[p].score for p in state.players})

            # 主阶段（含链/Showdown 的决策循环）
            main_ongoing = True
            while main_ongoing and not state.game_over:
                steps += 1
                if steps > max_steps:
                    raise GameOver(None, "达到步数上限")

                # 1) 清理任务（可能开启 Showdown/Combat）
                cleanup_mod.cleanup(state)
                if state.game_over:
                    break

                # 2) FEPR 驱动（链 Finalize/Resolve、Showdown 让过循环）
                result = fepr_mod.run_fepr(state)
                if state.game_over:
                    break

                # 3) 确定决策者
                if state.priority_player is None:
                    # Neutral Open：主阶段回合玩家
                    if state.phase == Phase.MAIN:
                        state.priority_player = state.turn_player
                    else:
                        main_ongoing = False
                        continue
                pid = state.priority_player

                # 4) 观察 + 提议 + 执行
                obs = agents[pid].observe(state, pid)
                try:
                    action = agents[pid].propose(obs)
                except Exception as e:
                    raise IllegalActionError(f"agent 提议异常: {e}")

                replay.record(type="step", step=steps, player=pid.value,
                              phase=state.phase.value,
                              state=state.derive_turn_state().value,
                              actions=[_fmt_action(a) for a in legal_actions(state, pid)],
                              chosen=_fmt_action(action))

                execute_action(state, pid, action)
                # pass 在 Open 主阶段 → 结束主阶段（_ending_phase → advance）
                if state.phase == Phase.ENDING:
                    main_ongoing = False

            if state.game_over:
                break
    except GameOver as go:
        state.game_over = True
        state.winner = go.winner
        return _finish(state, go.winner, go.reason, turns_done, steps, replay)

    return _finish(state, state.winner, state.game_over and "winner" or "game over",
                   turns_done, steps, replay)


def _finish(state: GameState, winner, reason, turns, steps, replay) -> GameResult:
    # winner 归一为 str（PlayerId.value）或 None，保证类型一致
    if winner is not None and hasattr(winner, "value"):
        winner = winner.value
    return GameResult(
        winner=winner,
        reason=reason,
        turns=turns,
        steps=steps,
        score_north=state.players[PlayerId.NORTH].score,
        score_south=state.players[PlayerId.SOUTH].score,
        replay=replay,
    )


def _fmt_action(a: dict) -> dict:
    return dict(a)