"""riftbench.cards: 卡牌双层数据模型。

呼应开发计划书 §4.2 的双层卡牌模型：
  - 静态属性层（CardStatic）: 可查询特征 — 费用/战力/类型/特性/标签等。
  - 效果脚本层（CardEffects）: 保留卡面原始文本（去 HTML），供后续 DSL 解析。

数据源：playriftbound.com 官方卡牌库 (PCS API + Sanity CMS)，英文。
"""
from riftbench.cards.model import (
    CardType,
    Domain,
    Rarity,
    Orientation,
    SuperType,
    SetId,
    CardStatic,
    CardEffects,
    Card,
    CardDatabase,
)

__all__ = [
    "CardType",
    "Domain",
    "Rarity",
    "Orientation",
    "SuperType",
    "SetId",
    "CardStatic",
    "CardEffects",
    "Card",
    "CardDatabase",
]
