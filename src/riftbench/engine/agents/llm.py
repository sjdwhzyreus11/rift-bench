"""LLM 对局 agent 接口（engine/agents/llm.py）。

Adapter 模式：observe → 渲染为自然语言 prompt → 调 LLM → 解析为合法行动 → 引擎过滤。
本轮不实际调 API（未配置 key 时回退到 heuristic/pass），预留接入点。

接入真实 LLM 的步骤（P3 后期/用户提供 key 后）:
  1. 在 _build_prompt 中把 obs（含手牌/场上/分数/合法行动）渲染为游戏状态描述
  2. 在 _call_llm 中调用 anthropic/openai SDK
  3. 在 _parse_action 中把模型输出解析为 {type, hand_runtime_id, ...}
"""
from __future__ import annotations

from riftbench.engine.actions import legal_actions
from riftbench.engine.model import PlayerId, ZoneType
from riftbench.engine.state import GameState


class LLMAgent:
    def __init__(self, model: str = "claude", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self._configured = bool(api_key)

    @property
    def is_configured(self) -> bool:
        return self._configured

    def observe(self, state: GameState, viewpoint: PlayerId) -> dict:
        acts = legal_actions(state, viewpoint)
        return {
            "viewpoint": viewpoint.value,
            "phase": state.phase.value,
            "turn_state": state.derive_turn_state().value,
            "showdown": state.is_showdown(),
            "closed": state.is_closed(),
            "hand": [{"runtime_id": o.runtime_id, "name": o.name, "energy": o.energy}
                     for o in state.objects_in(viewpoint, ZoneType.HAND)],
            "score": state.players[viewpoint].score,
            "legal_actions": [{**a} for a in acts],
        }

    def propose(self, obs: dict) -> dict:
        legal = obs.get("legal_actions", [])
        if not legal:
            return {"type": "pass"}
        if not self._configured:
            # 未配置：回退到启发式（打第一个非 pass 行动，否则 pass）
            for a in legal:
                if a.get("type") != "pass":
                    return a
            return {"type": "pass"}
        # TODO(P3 后期): _build_prompt(obs) -> _call_llm(prompt) -> _parse_action
        raise NotImplementedError("LLMAgent 需配置 API key")