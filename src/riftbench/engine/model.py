"""游戏物体、区域、玩家基础类型（规则 107-108/119/124/128/140-179）。

设计要点:
  - GameObject = 卡牌库 Card 引用 + 运行时状态。跨区移动成新物体（规则 124），
    故每个 GameObject 有唯一运行时 id，而非直接复用 Card。
  - Zone 按隐私三档（规则 128）标注：Secret/Private/Public。
  - 枚举值取自规则术语（英文权威基准）。
  - MVP 单态状态机：TurnState 只用 NORMAL_OPEN，但枚举预留四态供 P2。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from riftbench.cards.model import Card, CardType, Domain, SuperType


# ---------- 枚举 ----------

class PlayerId(str, Enum):
    """玩家标识。1v1 为 NORTH / SOUTH。"""
    NORTH = "north"
    SOUTH = "south"


class Privacy(str, Enum):
    """区域隐私等级（规则 128.3-128.5）。
    Secret  — 谁都不能看（主牌堆/符文牌堆的牌序）。
    Private — 仅拥有者/场上控制者可看（手牌、面朝下牌）。
    Public  — 所有人可看（场上、废牌堆、放逐区、传奇区等）。
    """
    SECRET = "secret"
    PRIVATE = "private"
    PUBLIC = "public"


class ZoneType(str, Enum):
    """区域类型。场地 (Board) vs 非场地 (Non-Board)，规则 107-108。"""
    # Board（场地）
    BASE = "base"                    # 基地，每玩家一个，是 Location
    BATTLEFIELD_ZONE = "battlefield_zone"  # 战场区，容纳多个战场
    BATTLEFIELD = "battlefield"      # 单个战场，是 Location
    FACEDOWN = "facedown"            # 待命区（战场子区域，容量1，P2）
    LEGEND = "legend"                # 传奇区，非 Location
    # Non-Board（非场地）
    CHAIN = "chain"                  # 结算链
    TRASH = "trash"                  # 废牌堆
    CHAMPION = "champion"            # 英雄区（选定英雄）
    MAIN_DECK = "main_deck"          # 主牌堆
    RUNE_DECK = "rune_deck"          # 符文牌堆
    BANISHMENT = "banishment"        # 放逐区
    HAND = "hand"                    # 手牌


class Phase(str, Enum):
    """回合阶段（规则 315-317）。"""
    AWAKEN = "awaken"          # 唤醒阶段
    BEGINNING = "beginning"    # 开始阶段
    MAIN = "main"              # 主阶段
    ENDING = "ending"          # 回合结束阶段


class TurnState(str, Enum):
    """回合状态机四态（规则 307-310）。MVP 只用 NORMAL_OPEN。"""
    NORMAL_OPEN = "normal_open"        # 普通 + 开环
    NORMAL_CLOSED = "normal_closed"    # 普通 + 闭环（结算链存在）
    SHOWDOWN_OPEN = "showdown_open"    # 法术对决 + 开环
    SHOWDOWN_CLOSED = "showdown_closed"  # 法术对决 + 闭环


class readiness:
    """进场/活跃状态。"""
    READY = "ready"      # 活跃（可行动）
    EXHAUSTED = "exhausted"  # 横置（休眠/已使用）
    DORMANT = "dormant"   # 休眠进场（单位默认）


class ControlStatus(str, Enum):
    """战场控制/争夺状态（规则 170.11/190.3）。"""
    OPEN = "open"              # 未被任何玩家控制
    CONTROLLED = "controlled"  # 被某玩家控制
    CONTESTED = "contested"    # 争夺中（有敌对单位进入未控战场）


# ---------- 游戏物体 ----------

class GameObject(BaseModel):
    """运行时游戏物体 = 静态属性快照 + 运行时状态。

    规则 119: Game Object 是可产生效果或作为行动前提的游戏件。
    规则 124: 从非场地区域进/出即成新物体——故用 runtime_id 区分实例，
    而非直接用 Card.internal_id（同一张卡可被多次打出成不同物体）。

    静态属性（types/domains/might/energy/super_types）在创建时从 CardStatic
    拷贝快照，使 GameObject 自包含、无需运行时回查卡牌库。
    """
    runtime_id: int = Field(..., description="引擎内唯一运行时 id")
    card_internal_id: str = Field(..., description="卡牌库 internal_id（溯源用）")
    name: str = Field(..., description="卡名（便于日志）")
    owner: PlayerId = Field(..., description="所属玩家")
    controller: PlayerId = Field(..., description="当前控制者")
    zone: ZoneType = Field(..., description="所在区域")
    location_id: Optional[str] = Field(None, description="所在 Location 的 id（基地id/战场id），非 Location 区域为 None")

    # 静态属性快照（创建时从 CardStatic 拷贝）
    types: list[CardType] = Field(default_factory=list)
    domains: list[Domain] = Field(default_factory=list)
    super_types: list[SuperType] = Field(default_factory=list)
    might: Optional[int] = Field(None, description="战力 [M]（仅单位）")
    energy: Optional[int] = Field(None, description="基础法力费用")
    is_basic_rune: bool = Field(False, description="是否基础符文（规则 164，MVP 能量来源）")

    # 运行时状态（进场时按规则 124 清除临时修正）
    readiness: str = readiness.EXHAUSTED  # 默认休眠（单位）；装备进场会设 READY
    damage: int = 0                       # 已标记伤害
    buffs: list = Field(default_factory=list, description="buff 计数标（规则 701-702，P2 扩展）")
    attached_to: Optional[int] = Field(None, description="贴附目标的 runtime_id（装备用）")
    attachments: list[int] = Field(default_factory=list, description="贴附在此物体上的 runtime_id 列表")
    attacker: bool = False                # 战斗中进攻方标记（规则 464.2.c.3）
    defender: bool = False                # 战斗中防守方标记

    # P2 预留字段（MVP 不用，但建模存在）
    granted_keywords: list[str] = Field(default_factory=list)
    temporary_might_mods: list = Field(default_factory=list)

    # P2.1 效果引擎字段
    keywords: list[str] = Field(default_factory=list, description="卡面文本中的关键字标记（供 keywords 模块）")
    stunned: bool = Field(False, description="眩晕（规则 423，不贡献战力、行动受限）")
    card_text: str = Field("", description="卡面效果文本快照（供效果解析，无需回查卡库）")

    # P2.3 深度规则字段（存储于 state.ability_cache 解析后的结构；此处保留派生状态）
    empowered: bool = Field(False, description="[Empowered] 强化状态（规则 827/828）")
    xp: int = Field(0, description="经验（规则 728，Level 门控）")
    active_abilities: list[int] = Field(default_factory=list, description="依赖关键字条件满足时激活的能力索引")
    damage_immune: bool = Field(False, description="[damage_immune] 免伤（连续效果层）")
    # 连续效果层（continuous.py 更新；effective_might/费用读取）
    continuous_might_mod: int = Field(0, description="连续效果层的战力修正（477.3 算术层，含依赖关键字条件授予）")
    continuous_cost_mod: int = Field(0, description="连续效果层的费用修正（costs N less）")
    # P2.3 解析结果注册表（存于 GameObject 自包含；continuous.py/replacement.py 读取）
    continuous_effects: list[dict] = Field(default_factory=list, description="[{layer,modifier,value,condition}] 持续修正")
    replacement_effects: list[dict] = Field(default_factory=list, description="[{trigger,replacement,value,condition}] 替换效果")

    # ---------- 派生属性 ----------
    @property
    def is_unit(self) -> bool:
        return CardType.UNIT in self.types

    @property
    def is_gear(self) -> bool:
        return CardType.GEAR in self.types

    @property
    def is_spell(self) -> bool:
        return CardType.SPELL in self.types

    @property
    def is_rune(self) -> bool:
        return CardType.RUNE in self.types

    @property
    def is_battlefield(self) -> bool:
        return CardType.BATTLEFIELD in self.types

    @property
    def is_legend(self) -> bool:
        return CardType.LEGEND in self.types

    @property
    def is_permanent(self) -> bool:
        """永久物 = 单位/装备/传奇/战场（场上停留的）。符文不是永久物（规则 161.1.a）。"""
        return any(t in self.types for t in
                   (CardType.UNIT, CardType.GEAR, CardType.LEGEND, CardType.BATTLEFIELD))

    @property
    def is_token(self) -> bool:
        return SuperType.TOKEN in self.super_types

    @property
    def effective_might(self) -> int:
        """有效战力 = 基础 might + buffs(703) + 连续效果层 + 临时修正。
        眩晕单位战力不计入战斗/行动（规则 423.2）。
        """
        if self.might is None:
            return 0
        base = self.might
        buff_might = sum(1 for b in self.buffs) if self.buffs else 0
        mod_might = sum(m for m in self.temporary_might_mods if isinstance(m, (int, float)))
        value = base + buff_might + self.continuous_might_mod + mod_might
        if self.stunned:
            value = 0
        return max(0, value)

    @classmethod
    def from_card(cls, runtime_id: int, card: Card, owner: PlayerId, controller: PlayerId,
                  zone: ZoneType, location_id: Optional[str] = None) -> "GameObject":
        """从卡牌库 Card 创建运行时 GameObject（拷贝静态属性快照）。"""
        s = card.static
        is_basic = SuperType.BASIC in s.super_types
        return cls(
            runtime_id=runtime_id,
            card_internal_id=s.internal_id,
            name=s.name,
            owner=owner,
            controller=controller,
            zone=zone,
            location_id=location_id,
            types=list(s.types),
            domains=list(s.domains),
            super_types=list(s.super_types),
            might=s.might,
            energy=s.energy,
            is_basic_rune=is_basic,
            card_text=card.effects.text,
        )


# ---------- 区域 ----------

class Zone(BaseModel):
    """区域容器。每个玩家拥有自己的一份非共享区域；场地共享但按玩家归属。"""
    zone_type: ZoneType
    owner: Optional[PlayerId] = Field(None, description="所属玩家（共享区域为 None）")
    privacy: Privacy
    objects: list[int] = Field(default_factory=list, description="GameObject.runtime_id 列表")
    capacity: Optional[int] = Field(None, description="容量上限（如 facedown=1）；None=无上限")
    location_id: Optional[str] = Field(None, description="战场/基地的 Location id")

    def is_public(self) -> bool:
        return self.privacy == Privacy.PUBLIC

    def is_secret(self) -> bool:
        return self.privacy == Privacy.SECRET

    def is_private(self) -> bool:
        return self.privacy == Privacy.PRIVATE


# ---------- 玩家 ----------

class RunePool(BaseModel):
    """符文池（规则 165）。MVP 只用 mana；power 留 P2。"""
    mana: int = 0      # Energy（法力），支付数字费用
    power: dict[str, int] = Field(default_factory=dict, description="符能，按 Domain 分（P2 扩展）")

    def clear(self) -> None:
        self.mana = 0
        self.power.clear()


class Player(BaseModel):
    """玩家运行时状态。"""
    player_id: PlayerId
    score: int = 0
    rune_pool: RunePool = Field(default_factory=RunePool)
    # 区域引用按 zone_type 索引（state 维护，此处仅占位）
    # mulligan / 先手标记
    is_first: bool = False
    # 后手首召出阶段 +1 符文标记（规则 485.7）
    extra_channel_first_turn: bool = False
    # 本回合已得分战场记账（规则 470）：set of battlefield location_id
    scored_battlefields_this_turn: set[str] = Field(default_factory=set)
    # P2.3: 经验（规则 728，Level/Hunt 门控）
    xp: int = Field(0, description="经验（无上限，[Level N]/[Hunt] 门控）")

    def add_score(self, n: int = 1) -> None:
        """得分（规则 194.4: 分数不为负；此处加分不会变负）。"""
        self.score = max(0, self.score + n)


class BattlefieldState(BaseModel):
    """单个战场的运行时状态。"""
    location_id: str
    card_internal_id: str         # 战场卡
    name: str
    # 控制者（CONTROLLED 时）与控制状态
    controller: Optional[PlayerId] = None
    status: ControlStatus = ControlStatus.OPEN
    # 谁令其进入 Contested（进攻方候选，规则 190.3/464.2.c.1）
    contested_by: Optional[PlayerId] = None
    # 是否 Staged Combat（待发生战斗，规则 461/323.9）
    staged_combat: bool = False
