"""卡牌双层数据模型 (pydantic v2)。

字段对齐 playriftbound.com PCS API 的卡牌对象。枚举值取自实际爬取数据。

双层模型（开发计划书 §4.2）:
  CardStatic  — 静态可查询特征层：费用/战力/类型/特性/标签/稀有度/编号。
  CardEffects — 效果脚本层：保留卡面原始英文文本（去 HTML 标签），供后续
                解析为可执行 DSL。当前阶段仅存原始文本，不做语义解析。
  Card        = CardStatic + CardEffects + 资产元数据 + 变体指针。
  CardDatabase— 全卡集合，按 (set, collectorNumber) 主版本去重，变体挂主版本下。
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


# ---------- 枚举 ----------

class CardType(str, Enum):
    """卡牌类型 (cardType.type[].id)。一个游戏物体可多类型。"""
    UNIT = "unit"
    SPELL = "spell"
    GEAR = "gear"          # 装备
    LEGEND = "legend"      # 传奇
    BATTLEFIELD = "battlefield"
    RUNE = "rune"


class Domain(str, Enum):
    """符文特性 / 阵营 (domain.values[].id)。6 色 + 无色。"""
    ORDER = "order"
    MIND = "mind"
    BODY = "body"
    FURY = "fury"
    CALM = "calm"
    CHAOS = "chaos"
    COLORLESS = "colorless"


class Rarity(str, Enum):
    """稀有度 (rarity.value.id)。"""
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    SHOWCASE = "showcase"   # 全画/展示版（视为变体）


class Orientation(str, Enum):
    """卡图方向。portrait=竖版主版本，landscape=横版变体。"""
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class SuperType(str, Enum):
    """超类型 (cardType.superType[].id)。无固有类型语义但可被规则引用。

    实际数据值（来自 playriftbound 卡牌库）:
      champion  — 英雄 (仅单位，对应选定英雄/英雄标签)
      signature — 专属 (对应规则 103.2.d 专属卡限制)
      basic     — 基础符文 (规则 163-164 的 6 种基础符文)
      token     — 指示物/计数物 (规则 179，非主牌堆卡牌)
    """
    CHAMPION = "champion"
    SIGNATURE = "signature"
    BASIC = "basic"
    TOKEN = "token"


class SetId(str, Enum):
    """系列代码 (set.value.id)。映射 rift-bench set 编号。"""
    OGN = "OGN"   # Origins — 起源 (set1)
    SFD = "SFD"   # Spiritforged — 铸魂淬炼 (set2)
    UNL = "UNL"   # Unleashed — 破限 (set3)
    VEN = "VEN"   # Vendetta — 化神争锋 (set4)
    OGS = "OGS"   # Proving Grounds — 新手系列


# ---------- 静态属性层 ----------

class CardStatic(BaseModel):
    """可查询特征层 — 引擎/构筑校验/检索直接使用。"""
    internal_id: str = Field(..., description="PCS 内部 id，如 unl-131-219")
    collector_number: int = Field(..., description="收藏编号")
    name: str = Field(..., description="卡名 (英)")
    public_code: str = Field(..., description="公开码，如 UNL-131/219")
    set_id: SetId
    types: list[CardType] = Field(default_factory=list, description="可多类型；Token 卡可能为空")
    super_types: list[SuperType] = Field(default_factory=list, description="超类型，如 token/hero/exclusive")
    domains: list[Domain] = Field(default_factory=list, description="可多特性")
    rarity: Rarity
    orientation: Orientation = Orientation.PORTRAIT
    energy: Optional[int] = Field(None, description="法力费用 (energy.value.id)")
    might: Optional[int] = Field(None, description="战力 [M] (might.value.id，仅单位)")
    tags: list[str] = Field(default_factory=list, description="标签 id 列表，如 hero/champion/gear 等")
    illustrator: Optional[str] = None
    aliases: list[str] = Field(default_factory=list, description="官方别名/全名（如勘误用全名而卡库用简称时），用于勘误/FAQ 按名匹配")

    @property
    def is_unit(self) -> bool:
        return CardType.UNIT in self.types

    @property
    def is_token(self) -> bool:
        return SuperType.TOKEN in self.super_types

    @property
    def key(self) -> tuple[str, int]:
        """主版本去重键 (set_id, collector_number)。"""
        return (self.set_id.value, self.collector_number)


# ---------- 效果脚本层 ----------

class CardEffects(BaseModel):
    """效果脚本层 — 当前保留卡面原始英文文本（token 已替换为规则符号）。

    后续 Phase：将 text 解析为结构化技能 AST（被动/替换/主动/触发式/延迟/内嵌/关联），
    供引擎效果解释器执行。现阶段以原始文本为解析源，accessibility_text 作交叉校验。

    token 映射（与英文核心规则术语对齐）:
      :rb_energy_N:  -> [N]            (N 点法力)
      :rb_rune_<d>:  -> [C]            (此牌自身特性符能，d=fury/order/...)
      :rb_rune_rainbow: -> [A]         (任意特性符能)
      :rb_exhaust:   -> [T]            (横置)
      :rb_might:     -> [M]            (战力 Might；accessibilityText 用 [S]=Strength，同义，统一取规则术语 [M])
    """
    text: str = Field("", description="卡面规则文本 (英，token 已替换为规则符号，去 HTML)")
    text_raw: str = Field("", description="卡面规则文本原始 HTML (含 :rb_ token，备查)")
    accessibility_text: str = Field("", description="无障碍描述 = 类型+名+效果文本 (英，权威对照)")


# ---------- 卡牌资产 ----------

class CardAssets(BaseModel):
    """卡牌视觉资产。"""
    card_image_url: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None


# ---------- 完整卡牌 ----------

class Card(BaseModel):
    """一张卡牌 = 静态层 + 效果层 + 资产 + 变体指针。"""
    static: CardStatic
    effects: CardEffects
    assets: CardAssets = Field(default_factory=CardAssets)
    is_variant: bool = Field(False, description="是否为变体（showcase/landscape/alt art）")
    variants: list[str] = Field(default_factory=list, description="变体的 internal_id 列表（挂在主版本下）")


# ---------- 全卡数据库 ----------

class CardDatabase(BaseModel):
    """全卡集合。按 (set, collector_number) 主版本去重；变体挂主版本下。

    索引:
      by_id:        internal_id -> Card
      by_set_number:(set_id, collector_number) -> Card (主版本)
      by_name:      name -> list[Card]
    """
    cards: list[Card] = Field(default_factory=list)
    # 派生索引（序列化时排除）
    _by_id: dict[str, Card] = {}
    _by_key: dict[tuple[str, int], Card] = {}
    _by_name: dict[str, list[Card]] = {}

    def build_indexes(self) -> None:
        self._by_id = {c.static.internal_id: c for c in self.cards}
        self._by_key = {c.static.key: c for c in self.cards if not c.is_variant}
        self._by_name = {}
        for c in self.cards:
            self._by_name.setdefault(c.static.name, []).append(c)

    def get(self, internal_id: str) -> Optional[Card]:
        return self._by_id.get(internal_id)

    def get_main(self, set_id: str, collector_number: int) -> Optional[Card]:
        return self._by_key.get((set_id, collector_number))

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "CardDatabase":
        db = cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
        db.build_indexes()
        return db
