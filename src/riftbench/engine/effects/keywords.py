"""关键字执行（P2.1 子集）— 从 GameObject.keywords 应用规则。

P2.1 支持（按卡数）:
  - [Empower] / [Empowered]: 强化（buff 机制，规则 827/828）
  - [Tank] / [Backline]: 战斗伤害分配顺序
  - [Temporary]: 进场休眠 + 结束阶段摧毁（规则 816）
  - [Deathknell]: 死亡触发（由触发系统处理，规则 808）
  - [Stun] / [Deflect] / [Mighty] 等：状态标记
P2.3: Level / Hunt / Flow / Ambush / Equip / Hidden / Weaponmaster 等完整实现。
"""
from __future__ import annotations

from riftbench.engine.model import GameObject, PlayerId, ZoneType, readiness
from riftbench.engine.state import GameState


# 影响战斗分配顺序的关键字 → 优先级（低=先分配；Tank必须先、Backline必须后，规则 815/826）
ASSIGNMENT_PRIORITY = {
    "Tank": 0,
    "Assault": 1,
    "Backline": 9,
}
# 分配优先级: 数值越小越早分配


def assignment_priority(obj: GameObject) -> int:
    """战斗伤害分配的强制顺序（规则 465.2.c.6）。"""
    for kw in obj.keywords + obj.granted_keywords:
        if kw in ASSIGNMENT_PRIORITY:
            return ASSIGNMENT_PRIORITY[kw]
    return 5  # 默认中位


def apply_enters_battlefield_cues(state: GameState, obj: GameObject) -> None:
    """单位/装备进场时的关键字效果。
    [Temporary]: 进场休眠（规则 816；结束阶段再摧毁，由 turn 清理调用 expire_temporary）。"""
    if "Temporary" in obj.keywords and obj.is_unit:
        obj.readiness = readiness.EXHAUSTED


def expire_temporary(state: GameState, pid: PlayerId) -> None:
    """结束阶段清理: 摧毁所有带 [Temporary] 的单位（规则 816 '控制者开始阶段销毁'——MVP 用结束清理）。"""
    for oid, o in list(state.objects.items()):
        if o.controller == pid and o.is_unit and "Temporary" in (o.keywords + o.granted_keywords):
            if o.zone in (ZoneType.BASE, ZoneType.BATTLEFIELD):
                state.move_object(oid, ZoneType.TRASH, o.owner, None)


def clear_turn_state(state: GameState) -> None:
    """结束阶段清除本回合临时修正（317.2.c）: 临时战力、stun、buffs 持久（buff 是计数标）。
    temporary_might_mods 清空；stun 恢复。buffs 保留（跨回合）。"""
    for o in state.objects.values():
        o.temporary_might_mods.clear()
        o.stunned = False
        o.granted_keywords.clear()  # this turn 授予的关键字过期（MVP 简化全清）