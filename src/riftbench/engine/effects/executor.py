"""指令执行器 — 把 Instruction AST 转换为引擎状态操作（规则 055 容错执行）。

对每条指令:
  - 解析目标（TargetFilter → 状态查询）。
  - 无合法目标 → 不影响（055: 忽略无法实现的指示）。
  - you may（optional）: 由决策回调决定是否执行；P2.1 默认执行（触发内获益多选做）。
  - 执行失败单个忽略，不整体回滚（不同于 P1 打出流程的原子回滚）。

能力激活入口:
  - execute_ability(state, source_obj, ab, event)  — 触发结算（events 调用）
  - activate_ability(state, pid, obj_id, ability_idx, targets) — 主动技能（actions 调用）
"""
from __future__ import annotations

import random
from typing import Optional

from riftbench.engine.model import PlayerId, ZoneType, readiness
from riftbench.engine.state import GameState


class Decision:
    """you may 决策策略。P2.1 默认执行；可注入 agent 策略。"""
    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random(0)

    def may(self, state: GameState, pid: PlayerId, ab: dict, instr: dict) -> bool:
        """'you may' 是否执行。P2.1 简化: 一律执行（多数为获益）。"""
        return True


_ACTIVE_ZONES = (ZoneType.BASE, ZoneType.BATTLEFIELD)


def _resolve_targets(state: GameState, instr: dict, source_obj,
                     pid: PlayerId) -> list[int]:
    """按 TargetFilter 查询合法目标 runtime_id 列表。"""
    target = instr.get("target") or {}
    relation = target.get("relation", "a")
    kind = target.get("card_kind")
    location = target.get("location")
    up_to = target.get("up_to")
    pool: list[int] = []

    # 基础候选池
    if kind == "player":
        pool = list(state.players.keys())
        return _apply_relation_to_players(state, pool, relation, pid, up_to)
    candidates = []
    for oid, o in state.objects.items():
        if o.zone not in _ACTIVE_ZONES:
            continue
        if kind and not _match_kind(o, kind):
            continue
        if location == "here":
            # 'here' = 与 source 同位
            if source_obj is not None and o.location_id != source_obj.location_id:
                continue
        candidates.append(oid)
    pool = candidates
    return _apply_relation(state, pool, relation, kind, pid, up_to)


def _match_kind(o, kind: str) -> bool:
    kinds = o.types
    if kind == "unit":  return o.is_unit
    if kind == "gear":  return o.is_gear
    if kind == "spell": return o.is_spell
    if kind == "rune":  return o.is_rune
    if kind == "card":  return True
    return True


def _apply_relation(state: GameState, pool: list[int], relation: str,
                    kind, pid: PlayerId, up_to):
    """relation 过滤敌我。friendly=controller==pid; enemy=!=pid。"""
    if relation in ("friendly", "your"):
        pool = [o for o in pool if state.objects[o].controller == pid]
    elif relation == "enemy":
        pool = [o for o in pool if state.objects[o].controller != pid]
    if up_to:
        pool = pool[:up_to]
    return pool


def _apply_relation_to_players(state, pool: list[PlayerId], relation, pid, up_to):
    if relation == "enemy":
        pool = [p for p in pool if p != pid]
    elif relation in ("friendly", "your"):
        pool = [pid] if pid in pool else []
    return pool


def execute_ability(state: GameState, source_obj, ab: dict, event=None,
                    decision: Optional[Decision] = None) -> None:
    """执行一个能力的全部指令。source_obj 是拥有该能力的 GameObject。
    P2.3: 检查依赖关键字条件门（726-727）——不满足则跳过。"""
    # 条件门（Empowered/Level N/Legion）
    cond = ab.get("condition_keyword")
    if cond and source_obj is not None and not _condition_met(state, source_obj, cond):
        return
    decision = decision or Decision(state.rng)
    controller = source_obj.controller if source_obj is not None else (event.player if event else None)
    if controller is None:
        return
    for instr in ab.get("instructions", []):
        _execute_instruction(state, instr, source_obj, controller, decision)


def can_activate(state: GameState, obj, ab: dict) -> bool:
    """主动技能可激活判定：仅控制者回合主阶段开环（规则 381），费用可付（P2.1 简化 [T]）。"""
    from riftbench.engine.model import Phase
    if state.phase != Phase.MAIN:
        return False
    if state.turn_player != obj.controller:
        return False
    if state.is_closed():
        return False
    cost = ab.get("cost") or ""
    # P2.1 仅支持横置 [T] 类费用；其他（[1][C]/弃牌）由 P2.2 扩展
    has_only_exhaust = bool("T" in cost)
    if "T" in cost and obj.readiness != readiness.READY:
        return False  # 已横置
    if has_only_exhaust or not cost:
        return True
    return False


def activate_ability(state: GameState, pid: PlayerId, obj_id: int,
                     ability_idx: int, decision: Optional[Decision] = None) -> bool:
    """主动技能激活（actions 调用）。返回是否成功执行。"""
    obj = state.objects.get(obj_id)
    if obj is None:
        return False
    abilities = state.ability_cache.get(obj_id, [])
    if ability_idx >= len(abilities):
        return False
    ab = abilities[ability_idx]
    if ab.get("kind") != "activated":
        return False
    # 费用：P2.1 仅处理 [T]（横置）简化；费用解析完整在 P2.2
    cost = ab.get("cost") or ""
    if "T" in cost:
        if obj.readiness != readiness.READY:
            return False  # 已横置不能再用
        obj.readiness = readiness.EXHAUSTED
    decision = decision or Decision(state.rng)
    for instr in ab.get("instructions", []):
        _execute_instruction(state, instr, obj, pid, decision)
    return True


def _execute_instruction(state: GameState, instr: dict, source_obj, pid: PlayerId,
                         decision: Decision) -> None:
    """执行单条指令（容错 055）。"""
    if instr.get("optional") and not decision.may(state, pid, {}, instr):
        return
    op = instr.get("op")
    target_ids = _resolve_targets(state, instr, source_obj, pid)
    try:
        if op == "score":
            _op_score(state, pid)
        elif op == "gain":
            _op_gain(state, pid, instr, source_obj)
        elif op == "draw":
            _op_draw(state, pid, instr.get("amount") or 1)
        elif op == "kill":
            _op_kill_deal(state, pid, source_obj, instr, target_ids, lethal=True)
        elif op == "deal":
            _op_kill_deal(state, pid, source_obj, instr, target_ids, lethal=False)
        elif op == "ready":
            _op_ready(state, target_ids)
        elif op == "exhaust":
            _op_exhaust(state, target_ids)
        elif op == "give_might":
            _op_give_might(state, target_ids, instr)
        elif op == "buff":
            _op_buff(state, target_ids)
        elif op == "move":
            _op_move(state, source_obj, target_ids)
        elif op == "recycle":
            _op_recycle(state, pid, source_obj, target_ids)
        elif op == "play":
            _op_play(state, pid, source_obj, instr, target_ids)
        elif op == "stun":
            _op_stun(state, target_ids)
        elif op == "counter":
            _op_counter(state, pid)
        elif op in ("return", "recall"):
            _op_return(state, target_ids)
        # 其余（banish/discard/look_at/reveal 等）P2.3 收尾；MVP 忽略不影响
    except Exception:
        # 055: 单个指令失败不影响其余
        pass


def _op_score(state: GameState, pid: PlayerId) -> None:
    from riftbench.engine.scoring import check_victory
    from riftbench.engine.errors import GameOver
    state.players[pid].add_score(1)
    # 立即检查胜利（效果得分也可致胜，规则 431.3.c 类似；简洁处理）
    try:
        check_victory(state)
    except GameOver:
        raise


def _op_gain(state: GameState, pid: PlayerId, instr: dict, source_obj) -> None:
    """Add [1]/[A]/[C]：注入符文池。MVP: 默认加1法力。"""
    state.players[pid].rune_pool.mana += 1


def _op_draw(state: GameState, pid: PlayerId, n: int) -> None:
    for _ in range(n):
        main_zone = state.zones[pid][ZoneType.MAIN_DECK]
        if main_zone.objects:
            rid = main_zone.objects[-1]
            state.move_object(rid, ZoneType.HAND, pid, None)

def _op_kill_deal(state: GameState, pid, source_obj, instr, target_ids, lethal: bool) -> None:
    from riftbench.engine.effects.replacement import apply_damage
    amount = instr.get("amount") or 0
    for oid in target_ids:
        o = state.objects.get(oid)
        if o is None:
            continue
        if lethal:
            o.damage = o.effective_might  # 摧毁（忽略免伤？kill 是摧毁非伤害——保留）
        else:
            # P2.3: 应用替换效果（prevent/double/immune）
            o.damage += apply_damage(state, o, amount)
        # 伤害>=战力 → 死亡进废牌堆（简化：立即进 trash）
        if o.damage >= o.effective_might and o.zone in _ACTIVE_ZONES:
            state.move_object(oid, ZoneType.TRASH, o.owner, None)


def _op_ready(state: GameState, target_ids: list[int]) -> None:
    for oid in target_ids:
        o = state.objects.get(oid)
        if o is not None:
            o.readiness = readiness.READY
            o.stunned = False


def _op_exhaust(state: GameState, target_ids: list[int]) -> None:
    for oid in target_ids:
        o = state.objects.get(oid)
        if o is not None:
            o.readiness = readiness.EXHAUSTED


def _op_give_might(state: GameState, target_ids: list[int], instr: dict) -> None:
    amount = instr.get("amount") or 0
    this_turn = instr.get("quals", {}).get("this_turn", True)
    for oid in target_ids:
        o = state.objects.get(oid)
        if o is not None and o.is_unit:
            o.temporary_might_mods.append(amount)


def _op_buff(state: GameState, target_ids: list[int]) -> None:
    """放置 buff 计数标（+1[M]，规则 702-703）。"""
    for oid in target_ids:
        o = state.objects.get(oid)
        if o is not None and o.is_unit:
            o.buffs.append({"source": "buff"})


def _op_move(state: GameState, source_obj, target_ids: list[int]) -> None:
    """移动目标到 source 所在位置（'move ... here' 类）。MVP 简化。"""
    if source_obj is None:
        return
    dest_zone = source_obj.zone
    dest_loc = source_obj.location_id
    for oid in target_ids:
        o = state.objects.get(oid)
        if o is None:
            continue
        if dest_zone in _ACTIVE_ZONES:
            state.move_object(oid, dest_zone, o.controller, dest_loc)


def _op_recycle(state: GameState, pid: PlayerId, source_obj, target_ids: list[int]) -> None:
    """回收进主牌堆底（规则 416）。MVP: 移回主牌堆顶即可（简化）。"""
    for oid in target_ids:
        o = state.objects.get(oid)
        if o is None:
            continue
        if o.zone in (ZoneType.TRASH, ZoneType.HAND, ZoneType.BATTLEFIELD, ZoneType.BASE):
            state.move_object(oid, ZoneType.MAIN_DECK, pid, None)


def _op_play(state: GameState, pid, source_obj, instr, target_ids) -> None:
    """'Play a ... token' / 'play a card from trash'：MVP 简化——若目标是场上物体则跳过；
    真正'打出牌'由 play.py 的扩展路径处理（P2.2 完整）。MVP 对 token 创建仅记录。"""
    pass  # P2.2: 创建 token / 从 trash 打出


def _op_stun(state: GameState, target_ids: list[int]) -> None:
    for oid in target_ids:
        o = state.objects.get(oid)
        if o is not None:
            o.stunned = True
            o.readiness = readiness.EXHAUSTED


def _op_return(state: GameState, target_ids: list[int]) -> None:
    """Return 到所属者手牌。"""
    for oid in target_ids:
        o = state.objects.get(oid)
        if o is not None:
            state.move_object(oid, ZoneType.HAND, o.owner, None)


def _op_counter(state: GameState, pid: PlayerId) -> None:
    """Counter 无效化（规则 425）：标记链上最近的 Finalized 法术/能力为 countered。

    目标 = 链上最新 Finalized 且非 Reaction 的项（对方刚打的牌）。
    防反修饰（uncounterable，如 Decree of Rage/Mel）→ 无效化不生效。
    """
    if not state.chain:
        return
    # 从最新往前找第一个 Finalized 且非 is_trigger 的项（可被反制的法术/能力）
    target = None
    for item in reversed(state.chain):
        if not item.finalized:
            continue
        if item.is_trigger or item.is_add:
            continue  # 触发/Add 不可被常规反制
        if item.player == pid:
            continue  # 自己打的不能反自己
        target = item
        break
    if target is None:
        return
    if target.uncounterable:
        return  # 防反卡：反制无效
    target.countered = True


def _condition_met(state: GameState, obj, cond: str) -> bool:
    """依赖关键字条件求值（规则 726-727）：
      Empowered  — obj.empowered（[C][C]: Empower me 激活后）
      Level N    — 控制者 xp >= N
      Legion     — 本回合已打出另一张牌（MVP: 简化 true，视为已打）
    """
    if cond == "Empowered":
        return bool(getattr(obj, "empowered", False))
    if cond.startswith("Level"):
        n = int(cond.split()[1]) if len(cond.split()) > 1 else 0
        xp = state.players[obj.controller].xp if obj.controller else 0
        return xp >= n
    if cond == "Legion":
        # MVP 简化：视为满足（完整需追踪本回合已打出牌数）
        return True
    return True