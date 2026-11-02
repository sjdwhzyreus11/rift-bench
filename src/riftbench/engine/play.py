"""打出卡牌流程（规则 349-359, P2.2 链式拆分）。

P2.2 把 P1 的原子六步拆分为链式三阶段（由 FEPR 驱动）:
  - begin_play(state, pid, hand_id, loc)  — Step 1 移到链 + 成为 Pending + 状态 Closed（354）
  - finalize_pending(state, item)         — FEPR Step 1 完成 选择/费用/支付/合法性/确认（337.1）
  - resolve_immediately(state, item)      — Unit/Gear/Add 立即 Resolve（337.2），不进 Execute 窗口
  - 法术: finalize 后留在链上成为 Finalized，进入 Execute 窗口（338）→ Resolve（340）

合法时机 can_play_at(state, pid, obj)（规则 308-310/806/813）:
  - Neutral Open: 任意卡（仅回合玩家持 Priority）
  - Neutral Closed: 仅 [Reaction]（309.1.a）；触发/Add 不受限（383.3.c/429.4）
  - Showdown Open: 仅 [Action]/[Reaction]（308.1.a）
  - Showdown Closed: 仅 [Reaction]
"""
from __future__ import annotations

from typing import Optional

from riftbench.engine.costs import can_pay_with_pool, determine_total_cost, pay_cost
from riftbench.engine.errors import IllegalActionError
from riftbench.engine.model import GameObject, Phase, PlayerId, ZoneType, readiness
from riftbench.engine.state import ChainItem, GameState


# ---------- 合法时机 ----------

def _obj_keywords(state: GameState, obj: GameObject) -> list[str]:
    """确保解析后返回关键字列表。"""
    from riftbench.engine.effects.manager import ensure_parsed
    ensure_parsed(state, obj)
    return obj.keywords


def can_play_at(state: GameState, pid: PlayerId, obj: GameObject) -> bool:
    """判定 pid 在状态 state 下能否打出 obj（规则 308-310/806/813）。"""
    # 优先权检查：有优先权者才可行动（312）
    if state.priority_player is not None and state.priority_player != pid:
        return False
    kws = _obj_keywords(state, obj)
    has_reaction = "Reaction" in kws
    has_action = "Action" in kws

    sd = state.is_showdown()
    closed = state.is_closed()
    if sd:
        if closed:
            return has_reaction  # Showdown Closed：仅 Reaction
        return has_action or has_reaction  # Showdown Open：Action/Reaction
    # Neutral
    if closed:
        return has_reaction  # Neutral Closed：仅 Reaction
    # Neutral Open
    return state.turn_player == pid


def _check_can_play(state: GameState, pid: PlayerId, obj: GameObject) -> None:
    if not can_play_at(state, pid, obj):
        st = state.derive_turn_state().value
        raise IllegalActionError(f"玩家 {pid} 无法在状态 {st} 打出 {obj.name}")


# ---------- 打出流程三阶段 ----------

def begin_play(state: GameState, pid: PlayerId, hand_runtime_id: int,
               target_location_id: Optional[str] = None) -> ChainItem:
    """Step 1 移到结算链 + 成为 Pending + 状态 Closed（规则 354）。

    返回 ChainItem（随后由 FEPR finalize）。不做费用/合法性——那是 finalize_pending。
    """
    obj = state.objects.get(hand_runtime_id)
    if obj is None or obj.zone != ZoneType.HAND or obj.controller != pid:
        raise IllegalActionError(f"卡牌 {hand_runtime_id} 不在玩家 {pid} 手牌")
    _check_can_play(state, pid, obj)

    # 移到链（Pending），状态 Closed
    state.move_object(hand_runtime_id, ZoneType.CHAIN, pid, None)
    item = ChainItem(runtime_id=hand_runtime_id, player=pid, finalized=False)
    state.chain.append(item)
    state.update_turn_state()
    return item


def finalize_pending(state: GameState, item: ChainItem) -> None:
    """FEPR Step 1：完成 Pending 项（337.1）——选择落点/定费用/支付/合法性/确认。

    完成后分类（337.2）:
      - Unit/Gear → 立即 resolve_immediately
      - Add 技能 → 立即 resolve
      - 法术 → 留在链上成为 Finalized（进入 Execute 窗口）
    失败 → 原子回滚并移出链（358.5）。
    """
    pid = item.player
    obj = state.objects.get(item.runtime_id)
    if obj is None:
        state.chain.remove(item)
        return
    snap = state.snapshot()
    try:
        # 选择落点（337.1 内，begin_play 已存 target_location_id）
        location_id = item.location_id
        if obj.is_spell:
            location_id = None
        elif location_id is None:
            location_id = f"base:{pid.value}"

        # 定总费用 + 支付（356/357）
        cost = determine_total_cost(obj)
        if cost > 0:
            if not can_pay_with_pool(state, pid, cost):
                raise IllegalActionError(f"费用不足: 需要 {cost} 法力")
            if not pay_cost(state, pid, cost):
                raise IllegalActionError(f"支付失败: 需要 {cost} 法力")

        # 合法性检查（358）
        _check_landing_legal(state, pid, obj, location_id)

        # 完成 Finalize
        item.finalized = True
        item.location_id = location_id
        item.kind = "spell" if obj.is_spell else ("unit" if obj.is_unit else ("gear" if obj.is_gear else "permanent"))

        # 分类处理（337.2）
        if item.kind != "spell":
            resolve_immediately(state, item)
        # 法术留在链上（Finalized），进入 Execute 窗口
    except IllegalActionError:
        state.restore(snap)
        if item in state.chain:
            state.chain.remove(item)
        # 物体回手牌
        if obj is not None and obj.zone == ZoneType.CHAIN:
            state.move_object(obj.runtime_id, ZoneType.HAND, pid, None)
        state.update_turn_state()
        raise


def resolve_immediately(state: GameState, item: ChainItem) -> "PlayResult":
    """立即 Resolve（337.2）：Unit/Gear 离链进场；Add 技能即时结算。

    Unit/Gear 不进 Execute 窗口；但进场产生的 Play 触发作为新 Pending 入链（383.4.a.2）。
    """
    pid = item.player
    obj = state.objects.get(item.runtime_id)
    location_id = item.location_id
    # 从链移除
    if item in state.chain:
        state.chain.remove(item)

    if item.is_add or (obj is not None and obj.is_rune):
        # Add 资源技能/符文：即时结算
        from riftbench.engine.effects.executor import _op_gain
        if obj is not None:
            _op_gain(state, pid, {}, obj)
        state.update_turn_state()
        return PlayResult("add", obj.runtime_id if obj else None)

    if obj is None:
        state.update_turn_state()
        return PlayResult("permanent", None)

    # 常驻牌进场（359.2）
    if obj.is_unit:
        obj.readiness = readiness.EXHAUSTED
    elif obj.is_gear:
        obj.readiness = readiness.READY
    else:
        obj.readiness = readiness.READY
    if location_id in state.battlefields:
        from riftbench.engine.combat import mark_battlefield_contested
        state.move_object(obj.runtime_id, ZoneType.BATTLEFIELD, pid, location_id)
        mark_battlefield_contested(state, location_id, pid)
    else:
        state.move_object(obj.runtime_id, ZoneType.BASE, pid, location_id)

    state.update_turn_state()
    return PlayResult(item.kind or "permanent", obj.runtime_id)


def resolve_spell(state: GameState, item: ChainItem) -> "PlayResult":
    """FEPR Step 4：结算 Finalized 法术（340.1）——执行效果进废牌堆。

    若被 [Reaction] Counter（425）无效化 → 直接进废牌堆不执行效果。
    """
    pid = item.player
    obj = state.objects.get(item.runtime_id)
    if item in state.chain:
        state.chain.remove(item)
    if obj is None:
        state.update_turn_state()
        return PlayResult("spell", None)
    # 无效化检查：若链上（或状态）标记被 counter → 不执行
    if getattr(item, "countered", False):
        state.move_object(obj.runtime_id, ZoneType.TRASH, pid, None)
        state.update_turn_state()
        return PlayResult("spell", obj.runtime_id)
    _execute_spell_instructions(state, pid, obj)
    state.move_object(obj.runtime_id, ZoneType.TRASH, pid, None)
    state.update_turn_state()
    return PlayResult("spell", obj.runtime_id)


class PlayResult:
    """打出结算结果。"""
    def __init__(self, kind: str, runtime_id: Optional[int] = None) -> None:
        self.kind = kind          # 'unit' | 'gear' | 'spell' | 'add' | 'permanent'
        self.runtime_id = runtime_id


# ---------- 落点 / 合法性 ----------

def _check_landing_legal(state: GameState, pid: PlayerId, obj: GameObject,
                         location_id: Optional[str]) -> None:
    """落点合法性。MVP：单位/装备落点是基地或某战场；法术无落点。"""
    if obj.is_spell:
        if location_id is not None:
            raise IllegalActionError("法术不能有落点")
        return
    if location_id is None:
        raise IllegalActionError("单位/装备必须指定落点")
    if location_id.startswith("base:"):
        owner_pid = location_id.split(":", 1)[1]
        if owner_pid != pid.value:
            raise IllegalActionError(f"单位/装备只能落在自己基地（不能 {location_id}）")
    elif location_id in state.battlefields:
        pass  # 合法战场
    else:
        raise IllegalActionError(f"非法落点 {location_id}")


# ---------- 兼容接口（P2.1 用） ----------

def play_card(state: GameState, pid: PlayerId, hand_runtime_id: int,
              target_location_id: Optional[str] = None) -> "PlayResult":
    """兼容入口：begin_play + 立即 finalize（旧行为，供测试/简单场景）。
    正常对局应走 FEPR 链式。"""
    item = begin_play(state, pid, hand_runtime_id, target_location_id)
    finalize_pending(state, item)
    if item.finalized and item.kind == "spell":
        return resolve_spell(state, item)
    return PlayResult(item.kind or "permanent", item.runtime_id)


def _execute_spell_instructions(state: GameState, pid: PlayerId, obj: GameObject) -> None:
    """法术结算：执行其指令（Parser 标记为 INSTRUCTION/PASSIVE 段）。"""
    from riftbench.engine.effects.manager import ensure_parsed
    from riftbench.engine.effects.executor import execute_ability
    ensure_parsed(state, obj)
    abilities = state.ability_cache.get(obj.runtime_id, [])
    for ab in abilities:
        if ab.get("kind") in ("instruction", "passive"):
            execute_ability(state, obj, ab)