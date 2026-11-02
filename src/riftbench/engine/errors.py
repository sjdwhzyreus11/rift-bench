"""引擎异常。"""
from __future__ import annotations

from typing import Optional


class IllegalActionError(Exception):
    """玩家提议的行动非法（费用不足/时机不对/目标非法/产生非法状态）。

    driver 捕获后要求 agent 重提议，或按策略判负。
    """

    def __init__(self, reason: str, *, action: Optional[dict] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.action = action


class GameOver(Exception):
    """对局结束。携带胜者 (PlayerId) 或 None（平局/步数上限）。"""

    def __init__(self, winner: Optional[str], reason: str = "") -> None:
        super().__init__(f"winner={winner} reason={reason}")
        self.winner = winner
        self.reason = reason
