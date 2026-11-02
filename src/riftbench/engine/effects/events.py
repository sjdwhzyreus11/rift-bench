"""事件系统 — 触发式能力的事件一等对象与注册匹配（规则 383）。

P2.1 简化: 事件发生时匹配注册的触发 → 按序排入队列 → 立即逐条结算（无响应窗口）。
P2.2 改为: 触发作为 Pending Chain Item 入链，经 FEPR/优先权结算。

事件种类与触发词对应（TriggerEventType）:
  PLAY / ENTER / CONQUER / HOLD / ATTACK / DEFEND / DIE / KILL / DRAW / PLAYED_CARD。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from riftbench.engine.model import PlayerId, ZoneType
from riftbench.engine.state import GameState


class Event(BaseModel):
    """一个游戏事件。一等对象（供触发匹配与回放）。"""
    kind: str                            # TriggerEventType.value
    source_obj: Optional[int] = Field(None, description="触发源的 runtime_id（'me'）")
    player: Optional[PlayerId] = None   # 相关玩家（触发归属）
    target_obj: Optional[int] = Field(None, description="事件目标（被杀/被攻击的单位等）")
    location: Optional[str] = Field(None, description="战场 location_id 或 base id")
    extra: dict = Field(default_factory=dict)


def register_object_triggers(state: GameState, obj_id: int) -> None:
    """物体进场/创建时，把其触发式能力注册进 trigger_registry（幂等）。"""
    obj = state.objects.get(obj_id)
    if obj is None:
        return
    abilities = state.ability_cache.get(obj_id)
    if abilities is None:
        return
    for idx, ab in enumerate(abilities):
        if ab.get("kind") == "triggered":
            ev = ab.get("trigger", {}).get("event")
            if ev:
                entries = state.trigger_registry.setdefault(ev, [])
                # 幂等：已有同一 (obj_id, ability_idx) 则跳过
                if any(e["obj_id"] == obj_id and e["ability_idx"] == idx for e in entries):
                    continue
                entries.append({"obj_id": obj_id, "ability_idx": idx})


def unregister_object_triggers(state: GameState, obj_id: int) -> None:
    """物体离场时，移除其所有注册。"""
    for ev, entries in list(state.trigger_registry.items()):
        state.trigger_registry[ev] = [e for e in entries if e["obj_id"] != obj_id]
        if not state.trigger_registry[ev]:
            del state.trigger_registry[ev]


@staticmethod
def _event_matches_source(event: Event, obj_id: int) -> bool:
    """事件归属过滤：
      play/enter/die/attack/defend: 仅事件源物体自身触发。
      其它（conquer/hold/draw/start_of_phase）: 由 player 归属判断，全部在场物体触发。
    """
    if event.kind in ("play", "enter", "die", "attack", "defend"):
        return event.source_obj == obj_id
    return True


def fire_event(state: GameState, event: Event) -> None:
    """掷出事件：匹配在场物体的触发，立即逐条结算。

    P2.1 排序: 匹配到的触发按 (ob_idx, 注册顺序)。MVP 简化按注册顺序。
    """
    if state.game_over:
        return
    entries = state.trigger_registry.get(event.kind, [])
    if not entries:
        return
    # 防止递归风暴：同一事件同一物体不重入
    state.processing_events.append(event.kind)
    try:
        matched: list[tuple] = []  # (obj, ab, entry)
        for entry in list(entries):
            obj = state.objects.get(entry["obj_id"])
            if obj is None or obj.zone not in (ZoneType.BASE, ZoneType.BATTLEFIELD):
                continue
            abilities = state.ability_cache.get(entry["obj_id"], [])
            if entry["ability_idx"] >= len(abilities):
                continue
            ab = abilities[entry["ability_idx"]]
            if not ab.get("trigger"):
                continue
            # subject 归属过滤：
            trig = ab.get("trigger", {})
            subject = trig.get("subject", "self")
            if subject == "controller" and event.player is not None \
                    and obj.controller != event.player:
                continue  # 'When you ...' 只有控制者自己的物体触发
            if subject == "self" and not _event_matches_source(event, obj.runtime_id):
                continue
            if event.player is not None and obj.controller != event.player:
                # 非 source 特定事件（conquer/hold）：仅该玩家在场物体触发
                if event.kind in ("conquer", "hold") and obj.controller != event.player:
                    continue
            matched.append((obj, ab, entry))
        # 排序（383.3.d.1）：同控制者自选序；多玩家从回合玩家起按回合顺序（MVP 简化按注册序）
        # P2.2: 触发入链，作为 Pending Chain Item（383.3）
        for obj, ab, entry in matched:
            _enqueue_trigger(state, obj, ab, entry)
    finally:
        state.processing_events.pop()


def _enqueue_trigger(state: GameState, obj, ab: dict, entry: dict) -> None:
    """把匹配的触发作为 Pending Chain Item 放入链（规则 383.3）。

    若触发是 Add 资源类（429.2）→ 立即 Resolve，不开放响应窗口。
    """
    from riftbench.engine.state import ChainItem
    item = ChainItem(
        runtime_id=obj.runtime_id, player=obj.controller,
        finalized=False, kind="ability", is_trigger=True,
        source_obj=obj.runtime_id, source_ability_idx=entry["ability_idx"],
    )
    state.chain.append(item)
    state.update_turn_state()
    # Add 类触发：Finalize 即 Resolve（429.2），不传优先权、先于其它项
    if _is_add_ability(ab):
        _finalize_trigger_item(state, item)
        _resolve_trigger_item(state, item)


def _is_add_ability(ab: dict) -> bool:
    instrs = ab.get("instructions", [])
    return any(i.get("op") == "gain" for i in instrs)


def finalize_trigger_item(state: GameState, item) -> None:
    """触发项 Finalize（fepr 调用）：无费用/无落点，直接标 finalized。"""
    if item.is_trigger and not item.finalized:
        item.finalized = True


def resolve_trigger_item(state: GameState, item) -> None:
    """触发项 Resolve：执行 source 能力的指令（fepr 调用）。"""
    obj = state.objects.get(item.source_obj)
    if obj is None:
        return
    abilities = state.ability_cache.get(item.source_obj, [])
    if item.source_ability_idx is None or item.source_ability_idx >= len(abilities):
        return
    ab = abilities[item.source_ability_idx]
    from riftbench.engine.effects.executor import execute_ability
    from riftbench.engine.effects.events import Event
    execute_ability(state, obj, ab, Event(kind="trigger", player=obj.controller))