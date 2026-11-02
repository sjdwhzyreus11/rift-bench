"""T5 堆栈/触发结算预测 — 给定出牌序列预测终态。

样本: 状态快照 + 一个拟议行动（打出一张牌）→ 预测结算后关键状态字段。

引擎正答: 在副本状态上执行该行动 → 驱动 FEPR → 记录终态关键字段
  （该卡是否进 trash / 目标单位伤害 / 分数变化 / 手牌数变化）。
"""
from __future__ import annotations

from riftbench.engine.actions import legal_actions
from riftbench.engine.errors import IllegalActionError
from riftbench.engine.model import PlayerId, ZoneType
from riftbench.engine.state import GameState


def _pick_play_action(state: GameState, viewpoint: PlayerId, rng):
    """挑一个可执行的 play 行动（若有）。"""
    acts = legal_actions(state, viewpoint)
    plays = [a for a in acts if a.get("type") == "play"]
    return rng.choice(plays) if plays else None


def _terminal_fields(state: GameState, question) -> dict:
    """从结算后状态提取关键字段（供模型预测 & 引擎正答）。"""
    action = question.get("action", {})
    rid = action.get("hand_runtime_id")
    fields = {}
    obj = state.objects.get(rid) if rid else None
    if obj is not None:
        fields["card_zone"] = obj.zone.value  # trash/hand/battlefield/base
        fields["card_owner_hand_count"] = len(state.objects_in(obj.owner, ZoneType.HAND))
    # 分数
    fields["scores"] = {p.value: state.players[p].score for p in state.players}
    return fields


def generate(state: GameState, viewpoint: PlayerId, rng, meta: dict | None = None) -> dict:
    from riftbench.engine.play import play_card
    action = _pick_play_action(state, viewpoint, rng)
    if action is None:
        return None  # 无 play 行动，跳过
    # 副本执行
    snap = state.snapshot()
    try:
        from riftbench.engine.fepr import run_fepr
        # 简化：直接用 play_card 兼容接口（begin+finalize+resolve）
        play_card(state, viewpoint, action["hand_runtime_id"],
                  action.get("target_location_id"))
        run_fepr(state)
        result = _terminal_fields(state, {"action": action})
    except Exception:
        state.restore(snap)
        return None
    finally:
        state.restore(snap)  # 恢复原状态（样本含快照，不在原状态执行）
    return {
        "question": {"task": "T5", "action": action},
        "engine_answer": result,
        "meta": {"task": "T5", **(meta or {})},
    }


def answer(state: GameState, question: dict) -> dict:
    """引擎正答：在副本上执行并返回终态字段。"""
    from riftbench.engine.play import play_card
    from riftbench.engine.fepr import run_fepr
    snap = state.snapshot()
    try:
        action = question.get("action", {})
        pid = state.turn_player
        play_card(state, pid, action.get("hand_runtime_id"),
                  action.get("target_location_id"))
        run_fepr(state)
        return _terminal_fields(state, question)
    finally:
        state.restore(snap)