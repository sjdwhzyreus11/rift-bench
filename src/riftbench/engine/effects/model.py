"""效果能力模型（pydantic v2）— DSL AST 定义。

从卡面文本（rules 等）解析出的结构化能力。覆盖卡面常见模式：
  - TriggeredAbility: "When/Whenever/At/As ... , <effect>"
  - ActivatedAbility: "[费用]: <effect>"（178 张卡含主动技能）
  - PassiveAbility: "I enter ready." / "I cost [1] less for ..." 等陈述
  - 指令 + 修饰符（you may / if / this turn / to a minimum of N）

设计目标：可执行（executor.py 遍历 instruction）且可回溯（source 保留原文）。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AbilityKind(str, Enum):
    TRIGGERED = "triggered"       # 触发式能力
    ACTIVATED = "activated"       # 主动技能
    PASSIVE = "passive"           # 被动/规则陈述
    INSTRUCTION = "instruction"   # 段内指令（法术效果等，无前置条件）


class TriggerEventType(str, Enum):
    """触发事件类型（规则 383.3-383.4 + 常见）。"""
    PLAY = "play"                 # 被打出（383.4.a Play Effects）
    ENTER = "enter"               # 进场（与 PLAY 相关但用于 "When I enter"）
    CONQUER = "conquer"           # 征服（383.4.c）
    HOLD = "hold"                 # 据守（383.4.d）
    ATTACK = "attack"             # 进攻（383.4.e）
    DEFEND = "defend"             # 防守（383.4.f）
    DIE = "die"                   # 死亡（Deathknell / When I die）
    KILL = "kill"                 # 摧毁（另一物体）
    BATTLEFIELD_SCORE = "battlefield_score"  # 战场得分时（含 hold/conquer 复合）
    DRAW = "draw"                 # 抽牌
    PLAYED_CARD = "played_card"   # 玩家打出任意卡（When you play a card）
    START_OF_PHASE = "start_of_phase"  # At the start of ...
    ATTACH = "attach"             # 贴附装备
    OTHER = "other"               # 未识别（低优先级）


class SubjectKind(str, Enum):
    """触发主体过滤器——触发能力的"我"是谁。"""
    SELF = "self"                 # "When I ..."
    CONTROLLER = "controller"     # "When you ..."
    FRIENDLY_UNIT = "friendly_unit"
    ENEMY_UNIT = "enemy_unit"
    ANY_UNIT = "any_unit"
    ANY = "any"


class InstructionOp(str, Enum):
    """指令操作（executor 分支依据）。"""
    PLAY = "play"                 # 打出卡牌（从手牌/废牌堆/主牌堆）
    KILL = "kill"                 # 摧毁
    DEAL = "deal"                 # 造成伤害
    READY = "ready"               # 变为活跃（读直）
    EXHAUST = "exhaust"           # 横置
    MOVE = "move"                 # 移动（标准移动的简化：区域间/战场间）
    RECALL = "recall"             # 召回（到基地）
    SCORE = "score"               # 得分
    GAIN = "gain"                 # 获得资源（Add [1]/[C]）
    GIVE_MIGHT = "give_might"     # 给予 +N[M]（this turn / permanent）
    BUFF = "buff"                 # 放置 buff 计数标（+1[M]）
    DRAW = "draw"                 # 抽牌
    BANISH = "banish"             # 放逐
    RECYCLE = "recycle"           # 回收（进主牌堆底）
    DISCARD = "discard"           # 弃牌
    RETURN = "return"             # 回手牌
    LOOK_AT = "look_at"           # 洞察/查看
    REVEAL = "reveal"             # 展示
    STUN = "stun"                 # 眩晕
    COUNTER = "counter"           # 无效化
    HEAL = "heal"                 # 移除伤害
    TEMP_GRANT = "temp_grant"     # 授予关键字（this turn）
    OTHER = "other"               # 未识别（忽略执行）


class TargetRelation(str, Enum):
    """目标与"我/你"的关系。"""
    A = "a"                       # 任意
    AN = "an"
    ANY = "any"
    SELF = "self"                 # "me"/"myself"
    CONTROLLER = "controller"     # "you"（玩家）
    FRIENDLY = "friendly"         # 友方
    ENEMY = "enemy"               # 敌方
    YOUR = "your"                 # 你的
    EACH = "each"                 # 每个


class TargetFilter(BaseModel):
    """目标过滤器 → 状态查询谓词。"""
    relation: TargetRelation = TargetRelation.A
    card_kind: Optional[str] = Field(None, description="unit/gear/spell/rune/card/player")
    location: Optional[str] = Field(None, description="here/hand/trash/main deck/base/battlefield")
    up_to: Optional[int] = Field(None, description="up to N")
    count: Optional[int] = Field(None, description="精确数量（如\"two\"）")
    arbitrary: bool = Field(False, description="真随机目标（general-purpose，非限定）")


class ConditionOperator(str, Enum):
    COMPARISON = "comparison"     # might >= N / energy <= N 等
    HAS_KEYWORD = "has_keyword"   # [Temporary] 等
    LOCATION = "location"         # 某位（好 handled 于 op 外）


class Condition(BaseModel):
    """"If ..." 前置/分支条件。"""
    op: ConditionOperator
    field: str                    # 'might'/'energy'/'keyword'/'attacked_this_turn'/'moved_this_turn'...
    comparator: Optional[str] = None  # >=/<=/=/>
    value: Optional[int] = None
    keyword: Optional[str] = None


class Instruction(BaseModel):
    """一条效果指令。"""
    op: InstructionOp
    target: TargetFilter = Field(default_factory=TargetFilter)
    amount: Optional[int] = Field(None, description="伤害量/张数/战力值/费用值")
    optional: bool = Field(False, description="'you may'：是否由控制者选择")
    condition: Optional[str] = Field(None, description="'If ...' 前缀原文（P2.1 简化：由 executor 或忽略）")
    quals: dict = Field(default_factory=dict, description="修饰符：this_turn/to_minimum/each/face_down 等")
    raw: str = Field("", description="原文片段（可回溯）")
    # 执行期解析出的目标（P2.1 运行时填充，不参与 AST 语义比较）
    resolved: list[int] = Field(default_factory=list, description="目标 runtime_id 列表（由 executor 重算）")


class Trigger(BaseModel):
    """触发条件描述。"""
    event: TriggerEventType
    subject: SubjectKind = SubjectKind.SELF
    qualifiers: list[str] = Field(default_factory=list)  # 如 ['attack_or_defend'] 合并触发


class Ability(BaseModel):
    """一个能力（触发/主动/被动/指令段）。"""
    kind: AbilityKind
    source: str = Field("", description="原文段（可回溯）")
    trigger: Optional[Trigger] = None
    cost: Optional[str] = Field(None, description="ACTIVATED 费用原文（如 '[T]'/'[1][C]'/'Discard 1'）")
    instructions: list[Instruction] = Field(default_factory=list)
    optional: bool = Field(False, description="'you may ...' 包裹整段")
    # 关键字（从文本提取 [X]），供 keywords.py
    keywords: list[str] = Field(default_factory=list)
    # P2.3 依赖关键字条件门（726-727）：'Empowered'/'Level N'/'Legion' 等
    condition_keyword: Optional[str] = Field(None, description="依赖关键字条件（如 'Empowered'/'Level 3'/'Legion'），满足才生效")

    @property
    def is_triggered(self) -> bool:
        return self.kind == AbilityKind.TRIGGERED

    @property
    def is_activated(self) -> bool:
        return self.kind == AbilityKind.ACTIVATED

    @property
    def is_passive(self) -> bool:
        return self.kind == AbilityKind.PASSIVE


class ParsedCardEffects(BaseModel):
    """一张卡的解析结果。"""
    card_internal_id: str = ""
    abilities: list[Ability] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    parser_warnings: list[str] = Field(default_factory=list)
    parseable: bool = Field(True, description="是否成功解析出至少一个能力/关键字")