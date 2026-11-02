"""效果引擎集成管理器 — 统一能力解析、触发注册、进场/离场钩子。

粘合 parser / events / executor / keywords 到引擎主流程:
  - ensure_parsed(state, obj): 懒解析卡面文本 → ability_cache + obj.keywords
  - on_board_enter(state, obj): 进场（Register 触发 + 关键字进场效果）
  - on_board_leave(state, obj): 离场（Unregister 触发）
  - fire(state, event): 转发到 events.fire_event

由 play.setup / turn 在物体移动进/出场地时调用。
"""
from __future__ import annotations

from riftbench.engine.effects.events import (
    Event,
    fire_event,
    register_object_triggers,
    unregister_object_triggers,
)
from riftbench.engine.effects.keywords import apply_enters_battlefield_cues
from riftbench.engine.effects.parser import parse_card_effects
from riftbench.engine.model import GameObject, PlayerId, ZoneType
from riftbench.engine.state import GameState


def ensure_parsed(state: GameState, obj: GameObject) -> None:
    """懒解析 obj 的卡面文本 → ability_cache + obj.keywords（若未缓存）。"""
    if obj.runtime_id in state.ability_cache:
        return
    parsed = parse_card_effects(obj.card_text, obj.card_internal_id)
    state.ability_cache[obj.runtime_id] = [a.model_dump(mode="json") for a in parsed.abilities]
    if parsed.keywords and not obj.keywords:
        obj.keywords = list(parsed.keywords)
    # P2.3: 注册连续效果与替换效果（自包含于 GameObject）
    from riftbench.engine.effects.continuous import register_continuous
    from riftbench.engine.effects.replacement import register_replacement
    register_continuous(state, obj)
    register_replacement(state, obj)
    state.trigger_registry.setdefault("_parsed", []).append({"obj_id": obj.runtime_id})


def on_board_enter(state: GameState, obj: GameObject) -> None:
    """物体进场（base/battlefield）: 解析能力、注册触发、应用关键字进场效果。"""
    if obj.zone not in (ZoneType.BASE, ZoneType.BATTLEFIELD):
        return
    ensure_parsed(state, obj)
    if obj.is_spell:
        return  # 法术不留场，不注册触发
    register_object_triggers(state, obj.runtime_id)
    apply_enters_battlefield_cues(state, obj)


def on_board_leave(state: GameState, obj: GameObject) -> None:
    """物体离场: 移除触发注册（触发仅在场有效）。"""
    unregister_object_triggers(state, obj.runtime_id)


def fire(state: GameState, kind: str, source_obj: int | None = None,
         player: PlayerId | None = None, target_obj: int | None = None,
         location: str | None = None, extra: dict | None = None) -> None:
    """便捷: 掷出事件。"""
    fire_event(state, Event(kind=kind, source_obj=source_obj, player=player,
                             target_obj=target_obj, location=location,
                             extra=extra or {}))