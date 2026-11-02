"""GameState — 完整对局状态（规则 301-317/166-167/328）。

持有所有玩家、所有区域、游戏物体表、回合状态、结算链、战斗暂存。
确定性：随机性由外部 RNG (random.Random with seed) 注入，状态本身无 Math.random。
快照/恢复：供测试与回放（pydantic 深拷贝）。

区域组织:
  - 每玩家私有: hand, main_deck, rune_deck, trash, banishment, champion, legend, base
  - 共享: battlefield_zone (含多个战场), chain
  - 战场子区域 facedown 留 P2

Location 体系（规则 197-199）:
  - Base 是 Location（location_id = "base:<player>"）
  - 每个 Battlefield 是 Location（location_id = "bf:<n>"）
  - GameObject.location_id 指向所在 Location
"""
from __future__ import annotations

import copy
import random
from typing import Optional

from pydantic import BaseModel, Field

from riftbench.cards import CardDatabase
from riftbench.engine.model import (
    BattlefieldState,
    ControlStatus,
    GameObject,
    Phase,
    Player,
    PlayerId,
    RunePool,
    TurnState,
    Zone,
    ZoneType,
    Privacy,
    readiness,
)


VICTORY_SCORE_1V1 = 8  # 规则 485.3


class ChainItem(BaseModel):
    """结算链上的物品（规则 328-329）。

    P2.2: 卡牌打出/技能激活/触发入链成为 Pending Item。
    Finalize（337.1）后：
      - Unit/Gear/Add 技能 → 立即 Resolve（337.2）
      - 法术/其它技能 → 留在链上成为 Finalized，进入 Execute 窗口（338）
    """
    runtime_id: int               # 对应的 GameObject.runtime_id
    player: PlayerId              # 打出者/控制者
    finalized: bool = False       # 是否已 Finalize
    # P2.2 扩展
    location_id: Optional[str] = Field(None, description="单位/装备的落点（finalize 时确定）")
    kind: Optional[str] = Field(None, description="'unit'/'gear'/'spell'/'ability'（finalize 时确定）")
    is_add: bool = Field(False, description="Add 资源技能（429: finalize 即 resolve，不传优先权）")
    is_trigger: bool = Field(False, description="触发式能力入链（383.3）")
    source_obj: Optional[int] = Field(None, description="触发源 runtime_id（触发入链时）")
    source_ability_idx: Optional[int] = Field(None, description="触发源能力索引")
    # P2.3: Counter 标记（425）
    countered: bool = Field(False, description="已被无效化（425.1）——Resolve 时不执行效果")
    uncounterable: bool = Field(False, description="不可被反制（防反卡修饰层）")


class GameState(BaseModel):
    """完整对局状态。"""

    # ---------- 玩家 ----------
    players: dict[PlayerId, Player] = Field(default_factory=dict)

    # ---------- 游戏物体表 ----------
    objects: dict[int, GameObject] = Field(default_factory=dict)
    next_runtime_id: int = 1

    # ---------- 区域 ----------
    # 每玩家区域: player_id -> zone_type -> Zone (private per-player zones)
    zones: dict[PlayerId, dict[ZoneType, Zone]] = Field(default_factory=dict)

    # 共享战场区: 战场本身（BattlefieldState）+ 战场上的物体 Zone。
    battlefields: dict[str, BattlefieldState] = Field(default_factory=dict)  # location_id -> state
    battlefield_order: list[str] = Field(default_factory=list)  # 战场排列顺序
    battlefield_zones: dict[str, Zone] = Field(default_factory=dict)
        # location_id -> Zone (zone_type=BATTLEFIELD，容纳该战场上的物体)

    # 结算链（共享单条）
    chain: list[ChainItem] = Field(default_factory=list)
    chain_zone: Zone = Field(default_factory=lambda: Zone(zone_type=ZoneType.CHAIN, owner=None,
                                                          privacy=Privacy.PUBLIC))
        # 结算链上的物体容器（zone_type=CHAIN）

    # ---------- 回合状态 ----------
    turn_order: list[PlayerId] = Field(default_factory=list)
    turn_player_index: int = 0
    phase: Phase = Phase.AWAKEN
    # P2.2: turn_state 改为派生属性（Showdown? × Closed?），见下面 property。
    # P1 兼容：字段保留但优先用派生值。默认 NORMAL_OPEN。
    turn_state: TurnState = TurnState.NORMAL_OPEN
    turn_number: int = 1
    # 本回合是否为先手玩家第一回合（用于首回合调整）
    is_first_turn_of_game: bool = True

    # ---------- 优先权 / 焦点 / Showdown（P2.2）----------
    priority_player: Optional[PlayerId] = Field(None, description="当前持有优先权的玩家（312，任意时刻至多一人）")
    focus_player: Optional[PlayerId] = Field(None, description="Showdown Open 态持有焦点的玩家（313）")
    showdown_active: bool = Field(False, description="Showdown/Combat 进行中（308.1）")
    showdown_location: Optional[str] = Field(None, description="战斗 Showdown 的战场 location_id")
    pass_streak: int = Field(0, description="连续让过计数（339.1: 达玩家数则全让过→Resolve）")
    showdown_passes: int = Field(0, description="Showdown 态让过计数（348: 达玩家数则关 Showdown）")

    # ---------- 胜负 ----------
    victory_score: int = VICTORY_SCORE_1V1
    winner: Optional[PlayerId] = None
    game_over: bool = False

    # ---------- 效果引擎（P2.1）----------
    # 事件类型 -> 在场物体的触发注册（每物体一条，含能力索引）
    trigger_registry: dict[str, list[dict]] = Field(default_factory=dict)
        # {event_value: [{"obj_id": int, "ability_idx": int}, ...]}
    # 物体的解析后能力缓存（避免重复解析）：obj_id -> list[Ability dict]
    ability_cache: dict[int, list[dict]] = Field(default_factory=dict)
    # 触发结算中的事件栈（防重入/递归环）——MVP 立即结算，记录用
    processing_events: list[str] = Field(default_factory=list)

    # ---------- RNG（不入序列化快照，恢复时由外部重设）----------
    # pydantic 不序列化 random.Random；用 model_config exclude
    rng: Optional[random.Random] = None

    model_config = {"arbitrary_types_allowed": True}

    # ---------- 派生访问 ----------
    @property
    def turn_player(self) -> PlayerId:
        return self.turn_order[self.turn_player_index]

    def get_player(self, pid: PlayerId) -> Player:
        return self.players[pid]

    def opponent_of(self, pid: PlayerId) -> PlayerId:
        """1v1：另一名玩家。"""
        for p in self.turn_order:
            if p != pid:
                return p
        raise ValueError("no opponent")

    def get_object(self, runtime_id: int) -> Optional[GameObject]:
        return self.objects.get(runtime_id)

    def new_runtime_id(self) -> int:
        rid = self.next_runtime_id
        self.next_runtime_id += 1
        return rid

    # ---------- 区域访问 ----------
    def zone_of(self, pid: PlayerId, zt: ZoneType) -> Zone:
        return self.zones[pid][zt]

    def objects_in(self, pid: PlayerId, zt: ZoneType) -> list[GameObject]:
        zone = self.zones[pid][zt]
        return [self.objects[rid] for rid in zone.objects if rid in self.objects]

    def _container(self, zone_type: ZoneType, controller: PlayerId,
                   location_id: Optional[str]) -> Zone:
        """物体所在 Zone 容器。
        战场上的物体归到共享 battlefield_zones[location_id]；结算链归 chain_zone；
        其余归到每玩家 zones。"""
        if zone_type == ZoneType.BATTLEFIELD:
            if location_id is None or location_id not in self.battlefield_zones:
                raise KeyError(f"战场 {location_id!r} 没有 zone")
            return self.battlefield_zones[location_id]
        if zone_type == ZoneType.CHAIN:
            return self.chain_zone
        return self.zones[controller][zone_type]

    def all_board_objects(self) -> list[GameObject]:
        """场上所有物体（基地+战场区+战场上的物体）。"""
        result = []
        for pid in self.players:
            result.extend(self.objects_in(pid, ZoneType.BASE))
        for bf_zone in self.battlefield_zones.values():
            result.extend(self.objects[rid] for rid in bf_zone.objects if rid in self.objects)
        return result

    def battlefield_objects_all(self) -> list[int]:
        """所有战场上的物体 runtime_id（不含战场卡本身）。"""
        rids: list[int] = []
        for bf_zone in self.battlefield_zones.values():
            rids.extend(rid for rid in bf_zone.objects if rid in self.objects)
        return rids

    def units_at(self, location_id: str) -> list[GameObject]:
        """某 Location（基地或战场）上的所有单位。"""
        return [o for o in self.objects.values()
                if o.is_unit and o.location_id == location_id]

    def units_at_battlefield(self, bf_location_id: str) -> list[GameObject]:
        return [o for o in self.objects.values()
                if o.is_unit and o.zone == ZoneType.BATTLEFIELD and o.location_id == bf_location_id]

    def objects_at_location(self, location_id: str) -> list[GameObject]:
        return [o for o in self.objects.values() if o.location_id == location_id]

    def objects_at_battlefield(self, bf_location_id: str) -> list[GameObject]:
        return [o for o in self.objects.values()
                if o.zone == ZoneType.BATTLEFIELD and o.location_id == bf_location_id]

    def controllers_at_battlefield(self, bf_location_id: str) -> set[PlayerId]:
        """该战场上有单位的控制者集合（用于战斗触发判定）。"""
        return {o.controller for o in self.units_at_battlefield(bf_location_id)}

    # ---------- 状态机 ----------
    # ---------- 状态机 ----------
    def is_closed(self) -> bool:
        """结算链存在则闭环态（规则 309.1）。"""
        return len(self.chain) > 0

    def is_showdown(self) -> bool:
        """Showdown/Combat 进行中（规则 308.1）。"""
        return self.showdown_active

    def derive_turn_state(self) -> TurnState:
        """派生四态（Showdown? × Closed?，规则 307-310）。"""
        closed = self.is_closed()
        sd = self.is_showdown()
        if sd and closed:
            return TurnState.SHOWDOWN_CLOSED
        if sd and not closed:
            return TurnState.SHOWDOWN_OPEN
        if not sd and closed:
            return TurnState.NORMAL_CLOSED
        return TurnState.NORMAL_OPEN

    def update_turn_state(self) -> None:
        """把 turn_state 字段同步为派生值（供日志/快照/兼容读取）。"""
        self.turn_state = self.derive_turn_state()

    # ---------- Showdown 管理 ----------
    def enter_showdown(self, location: Optional[str] = None) -> None:
        """进入 Showdown 态（规则 344/464）。"""
        self.showdown_active = True
        self.showdown_location = location
        self.update_turn_state()

    def leave_showdown(self) -> None:
        """离开 Showdown 态（规则 348）。"""
        self.showdown_active = False
        self.showdown_location = None
        self.focus_player = None
        self.update_turn_state()

    # ---------- 优先权 / 焦点 ----------
    def give_priority(self, pid: PlayerId) -> None:
        """授予优先权（规则 312.3：无持有者则创建，有则转移）。"""
        self.priority_player = pid

    def pass_priority(self) -> None:
        """让过优先权：传给回合顺序下一位（338.1.b / 339.2）。"""
        if self.priority_player is None:
            return
        idx = self.turn_order.index(self.priority_player)
        nxt = self.turn_order[(idx + 1) % len(self.turn_order)]
        self.priority_player = nxt

    def give_focus(self, pid: PlayerId) -> None:
        """授予焦点（313.2：获焦点同时获优先权）。"""
        self.focus_player = pid
        self.priority_player = pid

    # ---------- 符文池 ----------
    def clear_rune_pools_all(self) -> None:
        """所有玩家符文池清空（规则 167: 每玩家主阶段开始 + 每玩家回合结束）。"""
        for p in self.players.values():
            p.rune_pool.clear()

    def clear_rune_pool(self, pid: PlayerId) -> None:
        self.players[pid].rune_pool.clear()

    # ---------- 快照 / 恢复 ----------
    def snapshot(self) -> "GameState":
        """深拷贝快照（不含 rng；恢复时由调用方重设 rng 状态）。"""
        snap = self.model_copy(deep=True)
        snap.rng = self.rng  # 共享同一 RNG 实例（快照不回滚 RNG）
        return snap

    def restore(self, snap: "GameState") -> None:
        """从快照恢复（rng 保持当前实例）。"""
        rng = self.rng
        restored = snap.model_copy(deep=True)
        for f in type(restored).model_fields:
            setattr(self, f, getattr(restored, f))
        self.rng = rng

    # ---------- 工具 ----------
    def add_object(self, obj: GameObject) -> None:
        self.objects[obj.runtime_id] = obj
        zone = self._container(obj.zone, obj.controller, obj.location_id)
        zone.objects.append(obj.runtime_id)

    def remove_object(self, runtime_id: int) -> Optional[GameObject]:
        obj = self.objects.pop(runtime_id, None)
        if obj is not None:
            zone = self._container(obj.zone, obj.controller, obj.location_id)
            if runtime_id in zone.objects:
                zone.objects.remove(runtime_id)
        return obj

    def move_object(self, runtime_id: int, new_zone: ZoneType,
                    new_controller: PlayerId, new_location_id: Optional[str] = None) -> None:
        """移动物体到新区域。规则 124: 跨场地区域（非场地<->场地）成新物体——
        清除临时修正（伤害/buff/授予关键字/攻防标记）。场地内移动（基地↔战场）不清。"""
        obj = self.objects[runtime_id]
        # 从旧区域移除
        old_zone = self._container(obj.zone, obj.controller, obj.location_id)
        if runtime_id in old_zone.objects:
            old_zone.objects.remove(runtime_id)
        was_board = obj.zone in (ZoneType.BASE, ZoneType.BATTLEFIELD)
        new_board = new_zone in (ZoneType.BASE, ZoneType.BATTLEFIELD)
        # 跨非场地边界 → 成为新物体，清临时修正（规则 124.1）
        if was_board != new_board:
            obj.damage = 0
            obj.buffs.clear()
            obj.granted_keywords.clear()
            obj.temporary_might_mods.clear()
            obj.attacker = False
            obj.defender = False
            obj.stunned = False
        # 设置新位置
        obj.controller = new_controller
        obj.zone = new_zone
        obj.location_id = new_location_id
        # 加入新区域
        new_z = self._container(new_zone, new_controller, new_location_id)
        new_z.objects.append(runtime_id)
        # P2.1 触发钩子：进出场地触发管理（延迟 import 避免循环）
        if was_board and not new_board:
            from riftbench.engine.effects.manager import on_board_leave
            on_board_leave(self, obj)
        elif new_board and not was_board:
            from riftbench.engine.effects.manager import on_board_enter
            on_board_enter(self, obj)
