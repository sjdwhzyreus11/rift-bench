"""费用计算与支付（规则 131/201-206/356/444/164.2.a）。

MVP 范围:
  - 仅基础费用（CardStatic.energy = 法力数）。符能 [C]/[A] 留 P2。
  - 基础符文能量来源 164.2.a: 基础符文横置执行 [E]: Add 1 产出1法力入池。
    规则 357.1.a 允许支付费用时随时激活 Add 技能（MVP 无响应窗口，视为零成本即时动作）。
  - 356.6: 费用不小于0。
  - 358.5: 支付失败→原子回滚（由 play.py 处理）。
"""
from __future__ import annotations

from riftbench.engine.model import GameObject, PlayerId, ZoneType, readiness
from riftbench.engine.state import GameState


def determine_total_cost(obj: GameObject) -> int:
    """定总费用（规则 356）。基础费用 − 连续效果费用修正（costs N less，477.3 算术层）。
    356.6: 费用不小于0。"""
    base = obj.energy if obj.energy is not None else 0
    reduced = base - getattr(obj, "continuous_cost_mod", 0)
    return max(0, reduced)


def can_pay_with_pool(state: GameState, pid: PlayerId, cost: int) -> bool:
    """检查符文池+可用符文横置产出是否够支付 cost。

    MVP 能量来源: 未横置基础符文可横置产出1法力（164.2.a）。
    玩家可先激活符文产出法力入池，再从池支付。此处检查"池内+可产出"总量。
    """
    pool = state.players[pid].rune_pool.mana
    # 可横置产出的基础符文数
    producible = count_producible_mana(state, pid)
    return pool + producible >= cost


def count_producible_mana(state: GameState, pid: PlayerId) -> int:
    """未横置的基础符文数量（每个可横置产1法力，规则 164.2.a）。"""
    n = 0
    for obj in state.objects_in(pid, ZoneType.BASE):
        if obj.is_basic_rune and obj.readiness == readiness.READY:
            n += 1
    return n


def produce_mana_from_runes(state: GameState, pid: PlayerId, amount: int) -> int:
    """横置至多 amount 个未横置基础符文，产出法力入池（规则 164.2.a / 357.1.a）。
    返回实际产出量。"""
    produced = 0
    for obj in state.objects_in(pid, ZoneType.BASE):
        if produced >= amount:
            break
        if obj.is_basic_rune and obj.readiness == readiness.READY:
            obj.readiness = readiness.EXHAUSTED
            state.players[pid].rune_pool.mana += 1
            produced += 1
    return produced


def pay_cost(state: GameState, pid: PlayerId, cost: int) -> bool:
    """支付费用（规则 357/444）。从符文池扣法力；不足则先横置符文产出补足。
    返回是否成功。失败不扣（调用方负责回滚）。
    """
    pool = state.players[pid].rune_pool
    if pool.mana >= cost:
        pool.mana -= cost
        return True
    # 不足：先横置符文产出
    needed = cost - pool.mana
    producible = count_producible_mana(state, pid)
    if needed > producible:
        return False  # 总量不够
    produce_mana_from_runes(state, pid, needed)
    # 再支付
    if pool.mana >= cost:
        pool.mana -= cost
        return True
    return False
