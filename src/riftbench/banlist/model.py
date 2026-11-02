"""rift-bench 禁卡表数据模型。

来源：playriftbound.com rules-hub 页（权威禁卡表，2026-07-16 更新）+
      july-ban-list-updates 公告页（历史禁卡更新记录）。

赛制:
  STANDARD — 1v1 标准 Constructed（v1.0 锁定赛制）
  TEAM_2V2 — 2v2 Constructed（含 STANDARD 全部 + 额外禁卡）
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BanFormat(str, Enum):
    STANDARD = "standard"        # 1v1 Standard Constructed
    TEAM_2V2 = "team_2v2"        # 2v2 Constructed


class BanCategory(str, Enum):
    """禁卡类型分类（对应 rules-hub 禁卡表的分组）。"""
    CARD = "card"                # 卡牌（单位/装备/法术）
    BATTLEFIELD = "battlefield"  # 战场
    LEGEND = "legend"            # 传奇（仅 2v2 额外禁）


class BanEntry(BaseModel):
    """一条禁卡记录。"""
    name: str = Field(..., description="官方禁卡表中的卡名（英文原文）")
    category: BanCategory
    formats: list[BanFormat] = Field(..., description="在哪些赛制下被禁")
    card_internal_id: Optional[str] = Field(None, description="匹配到的卡牌 internal_id；未匹配为 None")
    card_public_code: Optional[str] = None
    match_note: Optional[str] = Field(None, description="名称匹配说明（如模糊匹配/未匹配原因）")


class Banlist(BaseModel):
    """完整禁卡表。"""
    last_updated: str = Field(..., description="官方更新日期")
    source_url: str
    entries: list[BanEntry] = Field(default_factory=list)

    def by_format(self, fmt: BanFormat) -> list[BanEntry]:
        return [e for e in self.entries if fmt in e.formats]
