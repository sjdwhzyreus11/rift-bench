"""T2 合法性判断 — 拟议行动合法/非法（引擎 legal_actions 判定）。

样本: {question: {task, action}, engine_answer: {legal: bool}}
生成: ①从合法集取真正行动（合法正例）②非法行动（非回合玩家/无效id，非法负例）
engine_answer 由引擎真实判定（validate_action），权威。
"""
from __future__ import annotations

from riftbench.engine.actions import legal_actions, validate_action
from riftbench.engine.errors import IllegalActionError
from riftbench.engine.model import PlayerId, ZoneType
from riftbench.engine.state import GameState


def _build_question(state: GameState, viewpoint: PlayerId, rng) -> dict:
    """构造一个拟议行动（可能合法可能非法）。"""
    acts = legal_actions(state, viewpoint)
    if acts and rng.random() < 0.5:
        return {"task": "T2", "action": rng.choice(acts)}
    # 非法行动构造
    opp = state.opponent_of(viewpoint)
    opp_hand = list(state.objects_in(opp, ZoneType.HAND))
    if opp_hand:
        # 打对手手牌（非本人不能打）
        return {"task": "T2", "action": {"type": "play",
                                         "hand_runtime_id": opp_hand[0].runtime_id,
                                         "target_location_id": None}}
    return {"task": "T2", "action": {"type": "play", "hand_runtime_id": 99999,
                                     "target_location_id": None}}


def generate(state: GameState, viewpoint: PlayerId, rng, meta: dict | None = None) -> dict:
    question = _build_question(state, viewpoint, rng)
    return {
        "question": question,
        "engine_answer": answer(state, question),
        "meta": {"task": "T2", **(meta or {})},
    }


def answer(state: GameState, question: dict) -> dict:
    """引擎正答：validate_action 判定。"""
    action = question.get("action", {})
    # 用 question 中隐含的视角（generate 传 viewpoint）——简化：依次尝试两玩家
    for pid in state.turn_order:
        try:
            validate_action(state, pid, action)
            return {"legal": True}
        except IllegalActionError:
            continue
    return {"legal": False}