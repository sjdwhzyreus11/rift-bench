"""效果引擎覆盖率报告 — 统计 DSL 成功解析并可执行的卡牌比例。

判定"可解析"（P2.1 目标 ≥90%）:
  - 白板卡（无文本/仅关键字，L0）
  - 有触发式能力且指令可执行
  - 有主动技能
  - 有被动/指令段
不可解析的标记为 unsupported。

用法: PYTHONPATH=src python scripts/effects_coverage.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from riftbench.engine.effects.parser import parse_card_effects
from riftbench.engine.effects.model import InstructionOp

ROOT = Path(__file__).resolve().parents[1]
CARDS = json.loads((ROOT / "data" / "cards" / "cards.json").read_text(encoding="utf-8"))["cards"]


def text_of(c: dict) -> str:
    return (c["effects"]["text"] or "").strip()


def main() -> None:
    mains = [c for c in CARDS if not c["is_variant"]]
    stats = Counter()
    no_text = 0
    with_instr = 0
    with_trigger = 0
    with_activated = 0
    instr_ops = Counter()
    unsupported: list[str] = []
    total_abilities = 0

    for c in mains:
        t = text_of(c)
        if not t or t == "[NO TEXT]":
            no_text += 1
            stats["可解析(L0白板)"] += 1
            continue
        parsed = parse_card_effects(t, c["static"]["internal_id"])
        if not parsed.abilities:
            unsupported.append(c["static"]["name"])
            stats["不可解析"] += 1
            continue
        stats["可解析"] += 1
        total_abilities += len(parsed.abilities)
        for a in parsed.abilities:
            if a.kind.value == "triggered":
                with_trigger += 1
            if a.kind.value == "activated":
                with_activated += 1
            for i in a.instructions:
                with_instr += 1
                instr_ops[i.op.value] += 1

    total = len(mains)
    parseable = stats["可解析(L0白板)"] + stats["可解析"]
    print(f"主版本: {total}")
    print(f"可解析(含白板): {parseable}/{total} = {parseable/total*100:.1f}%")
    print(f"  白板(L0): {no_text}")
    print(f"  有可执行能力: {stats['可解析']}")
    print(f"  不可解析: {len(unsupported)}")
    if unsupported:
        print(f"  不可解析样例: {unsupported[:12]}")
    print(f"能力总段数: {total_abilities}")
    print(f"触发式能力: {with_trigger}, 主动技能: {with_activated}")
    print(f"指令总数(instruction实例): {with_instr}")
    print("\n指令操作分布 (op -> 次数):")
    for op, n in instr_ops.most_common(20):
        print(f"  {op}: {n}")

    # 结论
    print(f"\n结论: 可执行卡牌 {parseable/total*100:.1f}%（目标 ≥90%）")


if __name__ == "__main__":
    main()