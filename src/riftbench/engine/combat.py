"""简化战斗（规则 190.3/450/459-466）。

战斗产生（MVP 先实现，否则战斗永不发生）:
  - 190.3: 有 Unit 由"不控制该战场"的玩家进入战场 → 战场打 Contested 标记。
  - 450: 标准移动使目的地为"未被控的 Uncontested 战场" → 变 Contested。
  - 323.8/323.9: 清理步骤在每个 Contested 战场 Stage Showdown；敌我双方各有 Unit → Stage Combat。
  - 323.13: Neutral Open + Staged Combat → Turn Player 选战场开始 Combat。
  - 460-462: Combat 触发条件 + 严格双方。

战斗流程（跳过 464.2.b/d/e/f/g 法术对决窗口，保留 464.2.c 攻防确立）:
  - Step 2 伤害步骤（465）: 双方总战力互分配 → 同时造成。
  - Step 3 结算步骤（466）: 战斗清理(heal+召回攻击方) → 判定结果 → 确立控制/征服得分 → 移除标记。

伤害分配硬约束（465.2.c.3/.c.4）: 先凑致命、不超额、余数继续。确定性算法。
"""
from __future__ import annotations

from riftbench.engine.model import GameObject, PlayerId, ZoneType, readiness, ControlStatus
from riftbench.engine.state import GameState


# ---------- 战斗产生 ----------

def mark_battlefield_contested(state: GameState, bf_loc: str, by: PlayerId) -> None:
    """规则 190.3/450: 战场进入争夺状态。由移入单位的玩家触发。

    Contested = 有"非控制者"的敌方单位进入战场；若战场 OPEN，首个进入者确立控制？
    MVP 简化: 直接标 Contested，contested_by 记录进攻方候选。
    """
    bf = state.battlefields.get(bf_loc)
    if bf is None:
        return
    # 若战场未被控制（OPEN），进入单位的玩家自动控制它（规则 190.3.a.1）
    if bf.status == ControlStatus.OPEN:
        bf.controller = by
        bf.status = ControlStatus.CONTROLLED
        return
    # 若战场被另一玩家控制 → 变 Contested，记录进攻方
    if bf.controller != by and bf.status == ControlStatus.CONTROLLED:
        bf.status = ControlStatus.CONTESTED
        bf.contested_by = by


def stage_combats(state: GameState) -> None:
    """清理步骤 323.9: 在每个 Contested 战场检查敌我双方是否有 Unit → Stage Combat。
    返回 Staged Combat 的战场列表。"""
    for bf_loc, bf in state.battlefields.items():
        controllers = state.controllers_at_battlefield(bf_loc)
        if len(controllers) >= 2:
            bf.staged_combat = True
        else:
            bf.staged_combat = False


def pick_staged_combat(state: GameState) -> list[str]:
    """323.13: Neutral Open + Staged Combat → Turn Player 选战场开始。MVP: 返回全部 staged。"""
    return [loc for loc, bf in state.battlefields.items() if bf.staged_combat]


def begin_combat(state: GameState, bf_loc: str) -> None:
    """开始一场战斗（323.13 入口）。P2.2: 进入战斗 Showdown（464），伤害步骤在 Showdown 关闭后。

    464.2: 确立攻防 → Attacker 获 Focus → 进入 Showdown 态（由 fepr/driver 驱动响应窗口）。
    """
    bf = state.battlefields[bf_loc]
    attacker = bf.contested_by
    bf.staged_combat = False  # 战斗开始，清除 staged
    defenders: list[PlayerId] = [p for p in state.turn_order if p != attacker]
    if attacker is None or not defenders:
        return  # 无进攻方（不应发生）
    defender = defenders[0]

    # 464.2.c.3: 双方在场 Unit 打上攻/防标记
    for o in state.units_at_battlefield(bf_loc):
        if o.controller == attacker:
            o.attacker = True
        elif o.controller == defender:
            o.defender = True

    # 464.2.d: 进入 Showdown，Attacker 获 Focus（附带 Priority）
    state.enter_showdown(bf_loc)
    state.give_focus(attacker)


def proceed_after_showdown(state: GameState, bf_loc: str) -> None:
    """Showdown 关闭后继续战斗（465.1 'When the Showdown closes'）:
    伤害步骤（465）→ 结算步骤（466）→ 移除攻防标记（466.7）。"""
    # 确立攻防（从标记读）
    attack_objs = [o for o in state.units_at_battlefield(bf_loc) if o.attacker]
    defend_objs = [o for o in state.units_at_battlefield(bf_loc) if o.defender]
    attackers = {o.controller for o in attack_objs}
    defenders = {o.controller for o in defend_objs}
    if not attackers or not defenders:
        return
    attacker = attackers.pop()
    defender = defenders.pop()

    # —— 伤害步骤（465）——
    _combat_damage_step(state, bf_loc, attacker, defender)

    # —— 结算步骤（466）——
    _combat_resolution_step(state, bf_loc, attacker, defender)

    # 466.7: 移除攻防标记（战斗结束）
    for o in state.units_at_battlefield(bf_loc):
        o.attacker = False
        o.defender = False


def _combat_damage_step(state: GameState, bf_loc: str, attacker: PlayerId, defender: PlayerId) -> None:
    """465: 若双方仍有单位→按总战力分配伤害→同时造成。"""
    attack_units = [o for o in state.units_at_battlefield(bf_loc) if o.controller == attacker]
    defend_units = [o for o in state.units_at_battlefield(bf_loc) if o.controller == defender]
    if not attack_units or not defend_units:
        return  # 465.1 前提不满足

    attack_sum = sum(o.effective_might for o in attack_units)
    defend_sum = sum(o.effective_might for o in defend_units)

    # 465.2.c: 进攻方先分配（把 attack_sum 伤害分给防守方单位），防守方再分
    _assign_damage(defend_units, attack_sum)
    _assign_damage(attack_units, defend_sum)
    # 465.2.d: 分配完成后伤害已累加到各单位 damage（视为同时造成）


def _assign_damage(targets: list[GameObject], total: int) -> None:
    """把 total 伤害确定性分配给 targets（满足 465.2.c.3/.c.4）。

    分配法: 逐个目标分配致命所需（其 might），直到余数不足以凑满下一个致命；
    把余数继续分配给任意未达致命的目标（465.2.c.4 允许超额当无其他目标）。
    伤害直接累加到 o.damage。
    """
    if total <= 0:
        return
    alive = [o for o in targets if o.damage < o.effective_might]
    alive.sort(key=lambda o: o.runtime_id)  # 确定性顺序
    if not alive:
        # 所有目标都已致命伤害满 → 全部超额前死；无存活可分配给（465.2.c.4）
        if targets:
            targets[0].damage += total
        return
    remaining = total
    # 先给每个目标凑致命（465.2.c.3）
    for o in alive:
        if remaining <= 0:
            break
        lethal_need = max(0, o.effective_might - o.damage)
        assign = min(remaining, lethal_need)
        o.damage += assign
        remaining -= assign
    # 余数：继续分给仍在场的未致命目标
    if remaining > 0:
        still_alive = [o for o in alive if o.damage < o.effective_might]
        if still_alive:
            still_alive[0].damage += remaining  # 余数给第一个仍存活目标
        else:
            # 全部致命后仍有余数 → 给第一个目标
            if targets:
                targets[0].damage += remaining


def _combat_resolution_step(state: GameState, bf_loc: str, attacker: PlayerId, defender: PlayerId) -> None:
    """466: 判定结果（基于伤害）→ 战斗清理 heal → 确立控制/征服得分。"""
    # 先记录死亡（damage>=might）——在 heal 之前判定（466.1 清理先判死再 heal）
    attacker_alive = [o for o in state.units_at_battlefield(bf_loc)
                      if o.controller == attacker and o.damage < o.effective_might]
    defender_alive = [o for o in state.units_at_battlefield(bf_loc)
                      if o.controller == defender and o.damage < o.effective_might]

    # 移除死亡单位（先掷死亡事件，须在移除前）
    from riftbench.engine.effects.manager import fire
    for o in list(state.units_at_battlefield(bf_loc)):
        if o.damage >= o.effective_might:
            fire(state, "die", source_obj=o.runtime_id, player=o.owner, location=o.location_id)
            state.move_object(o.runtime_id, ZoneType.TRASH, o.owner, None)

    # 466.3 判定战斗结果
    if not attacker_alive and not defender_alive:
        # 双方全灭 → 无结果（466.3.d）。战场 OPEN。
        bf = state.battlefields[bf_loc]
        bf.status = ControlStatus.OPEN
        bf.controller = None
        bf.contested_by = None
        return

    if not defender_alive:
        _attacker_wins(state, bf_loc, attacker)
        return

    if not attacker_alive:
        _defender_wins(state, bf_loc, defender)
        return

    # 双方都有存活 → 466.1.a.2 召回所有攻击方（Defenders 在场）
    _recall_attackers(state, bf_loc, attacker)


def _attacker_wins(state: GameState, bf_loc: str, attacker: PlayerId) -> None:
    from riftbench.engine.scoring import conquer_score
    bf = state.battlefields[bf_loc]
    if any(o.controller == attacker for o in state.units_at_battlefield(bf_loc)):
        bf.status = ControlStatus.CONTROLLED
        bf.controller = attacker
        bf.contested_by = None
        # 466.5.d: 本回合未得分 → 征服
        conquer_score(state, attacker, bf_loc)


def _defender_wins(state: GameState, bf_loc: str, defender: PlayerId) -> None:
    bf = state.battlefields[bf_loc]
    if any(o.controller == defender for o in state.units_at_battlefield(bf_loc)):
        bf.status = ControlStatus.CONTROLLED
        bf.controller = defender
        bf.contested_by = None


def _recall_attackers(state: GameState, bf_loc: str, attacker: PlayerId) -> None:
    """466.1.a.2: Defender 在场则召回所有攻击方到其基地（规则 454）。"""
    base_loc = f"base:{attacker.value}"
    for o in list(state.units_at_battlefield(bf_loc)):
        if o.controller == attacker and o.zone == ZoneType.BATTLEFIELD:
            state.move_object(o.runtime_id, ZoneType.BASE, attacker, base_loc)

