"""勘误 (Card Errata) 数据模型 (pydantic v2)。

来源：playriftbound.com 官方勘误公告页（raw/errata/*.html）。

系列代码与卡牌库一致 (SetId 的 OGN/SFD/UNL/VEN)：
  OGN — Origins 起源 (set1)
  SFD — Spiritforged 铸魂淬炼 (set2)
  UNL — Unleashed 破限 (set3)
  VEN — Vendetta 化神争锋 (set4)

勘误条目为二元组：卡名 + 新文本 + 旧文本。
规则符号 ([C]/[M]/[1]/[A]/[T] 等) 与卡牌库 token 映射保持一致，原样保留。
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ErrataSet(str, Enum):
    """勘误归属系列代码。"""
    OGN = "OGN"
    SFD = "SFD"
    UNL = "UNL"
    VEN = "VEN"


class ErrataEntry(BaseModel):
    """一条卡牌勘误：卡名 + 新文本 + 旧文本。"""
    set: ErrataSet = Field(..., description="勘误归属系列")
    card_name: str = Field(..., description="卡名 (英文原文，去 HTML)")
    new_text: str = Field(..., description="勘误后文本 ([NEW TEXT])")
    old_text: str = Field(..., description="勘误前原文 ([OLD TEXT])")


class ErrataCollection(BaseModel):
    """完整勘误表。"""
    entries: list[ErrataEntry] = Field(default_factory=list)

    def by_set(self, s: ErrataSet) -> list[ErrataEntry]:
        return [e for e in self.entries if e.set == s]

    def card_names(self) -> list[str]:
        return [e.card_name for e in self.entries]

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ErrataCollection":
        """从 JSON 加载；同时兼容 `{"entries":[...]}` 对象与纯数组两种格式。"""
        raw = Path(path).read_text(encoding="utf-8")
        if raw.lstrip().startswith("["):
            import json
            data = json.loads(raw)
            return cls(entries=[ErrataEntry.model_validate(x) for x in data])
        return cls.model_validate_json(raw)