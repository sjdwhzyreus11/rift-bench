"""FAQ (官方答疑) 数据模型 (pydantic v2)。

来源：playriftbound.com 官方 FAQ 页（raw/faq/*.html）。

每个系列一个 FAQ 文档；条目 = 主题 + 问题 + 答案。
Origin 系列 FAQ 已废弃（页面开头声明不再反映现行规则），
故 origins 的全部条目 deprecated=true；其余系列 deprecated=false。

答案可能跨多个段落，文本为合并后的纯文本（规则符号 [C]/[M] 等原样保留）。
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class FaqSet(str, Enum):
    """FAQ 归属系列代码。"""
    OGN = "OGN"
    SFD = "SFD"
    UNL = "UNL"
    VEN = "VEN"


class FaqEntry(BaseModel):
    """一条 FAQ：主题 + 问题 + 答案。"""
    set: FaqSet = Field(..., description="所属系列")
    deprecated: bool = Field(False, description="是否已废弃 (仅 origins 全文废弃)")
    topic: str = Field("", description="所属主题 (卡片名/规则主题/文档小节)")
    question: str = Field(..., description="问题文本")
    answer: str = Field(..., description="答案文本 (跨段落合并)")


class FaqCollection(BaseModel):
    """完整 FAQ 集合。"""
    entries: list[FaqEntry] = Field(default_factory=list)

    def by_set(self, s: FaqSet) -> list[FaqEntry]:
        return [e for e in self.entries if e.set == s]

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "FaqCollection":
        """从 JSON 加载；同时兼容 `{"entries":[...]}` 对象与纯数组两种格式。"""
        raw = Path(path).read_text(encoding="utf-8")
        if raw.lstrip().startswith("["):
            import json
            data = json.loads(raw)
            return cls(entries=[FaqEntry.model_validate(x) for x in data])
        return cls.model_validate_json(raw)