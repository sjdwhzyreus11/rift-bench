"""待测模型接口（bench/models.py）。

ModelAdapter 协议:
  answer(question: dict) -> dict
    question = 任务的输入（含状态观察视图 + 任务具体问题）
    answer   = 模型输出（judge 对比 engine_answer）

实现:
  RandomModel     — 随机猜测（naive baseline，展示任务难度下限）
  HeuristicModel  — 简单启发式（中等 baseline，显著优于 random）
  LLMAdapter      — LLM 接口（可插拔接 Claude/OpenAI，本轮不实际调 API）
"""
from __future__ import annotations

import random
from typing import Protocol


class ModelAdapter(Protocol):
    name: str

    def answer(self, question: dict) -> dict: ...


class RandomModel:
    """随机 baseline：对每类任务随机输出。"""
    name = "random"

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def answer(self, question: dict) -> dict:
        task = question.get("task")
        if task == "T2":
            # 合法性：随机 True/False
            return {"legal": self.rng.random() < 0.5}
        if task == "T3":
            # 行动枚举：从问题提供的候选里随机挑几个
            candidates = question.get("candidates", [])
            k = self.rng.randint(0, min(3, len(candidates)))
            picked = self.rng.sample(candidates, k) if candidates else []
            return {"actions": picked}
        if task in ("T5", "T6"):
            # 状态预测：随机猜（None = 无法作答）
            return {"result": None}
        return {}


class HeuristicModel:
    """启发式 baseline：简单规则。

    核心：对引擎输出的合法行动集做"带倾向的选择"——优先打出单位到战场、
    优先进攻移动、[Reaction] 牌在响应窗口倾向打出。对 T2/T3 用简单规则。
    """
    name = "heuristic"

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def answer(self, question: dict) -> dict:
        task = question.get("task")
        if task == "T3":
            return {"actions": self._pick_actions(question)}
        if task == "T2":
            # 启发式判合法：若拟议行动是"像样"的行动（含 target_location）则倾向合法
            action = question.get("action", {})
            plausible = self._plausible(action)
            return {"legal": plausible}
        if task in ("T5", "T6"):
            return {"result": None}
        return {}

    def _pick_actions(self, question: dict) -> list[dict]:
        """从候选行动里按启发式挑：优先 play(move) 到战场的单位、activate_rune、move 进攻。"""
        candidates = question.get("candidates", [])
        if not candidates:
            return []
        def score(a: dict) -> float:
            t = a.get("type")
            if t == "activate_rune":
                return 10
            if t == "play":
                loc = a.get("target_location_id") or ""
                return 6 if (loc.startswith("bf:") or loc in question.get("battlefields", [])) else 4
            if t == "move":
                return 5
            if t == "pass":
                return 1
            return 3
        ranked = sorted(candidates, key=score, reverse=True)
        return ranked[:2]  # 取最优前2

    def _plausible(self, action: dict) -> bool:
        t = action.get("type")
        if t in ("pass", "activate_rune"):
            return True
        if t == "play":
            return bool(action.get("hand_runtime_id"))
        if t == "move":
            return bool(action.get("unit_runtime_id"))
        return False


class LLMAdapter:
    """LLM 接口（可插拔）。本轮不实际调 API——answer 原样返回 question，供 harness 流程测试。

    接入真实 LLM：
      1. 把 question 的状态视图渲染为自然语言 prompt
      2. 调用 anthropic/openai SDK
      3. 解析模型输出为 {task 对应字段}
    """
    name = "llm"

    def __init__(self, model_name: str = "claude", api_key: str | None = None) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self._configured = bool(api_key)

    @property
    def is_configured(self) -> bool:
        return self._configured

    def answer(self, question: dict) -> dict:
        if not self._configured:
            # 未配置：返回占位（harness 可跳过或标记 skipped）
            return {"result": None, "skipped": True}
        # TODO(P3 后期): 渲染 prompt + 调 SDK + 解析
        raise NotImplementedError("LLMAdapter 需配置 API key 并实现 prompt 渲染")