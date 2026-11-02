"""极简触发（规则 383.3-383.4，MVP 仅 a/c/d）。

MVP 触发支持:
  - 打出效果（Play Effects, 383.4.a）: 单位/装备进场后立即执行。
    但 P1 决策"纯结构骨架，不解析效果文本"→ 实际执行留 P2。
    本模块仅提供**触发点接口**（排序/时机），MVP 不解析任何效果文本。
  - 征服/据守得分触发（383.4.c/d）: MVP 只记账，触发点留空。

P2: 在此接口上挂效果解释器。
"""
from __future__ import annotations

from riftbench.engine.model import PlayerId
from riftbench.engine.state import GameState


def on_permanent_entered(state: GameState, owner: PlayerId, controller: PlayerId,
                         object, location_id: str) -> None:
    """单位/装备进场触发点（383.4.a.2 植入时机）。
    P1: 不解析效果文本，空实现。P2: 解析 "When you play me" 文本执行。"""


def on_conquer_or_hold(state: GameState, pid: PlayerId, battle_location: str, kind: str) -> None:
    """征服/据守得分触发点（383.4.c/d）。
    P1: 只记账已在 scoring 完成，此处空。P2: 解析 "When I conquer/hold" 文本。"""