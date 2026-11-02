"""生成标准化禁卡表 data/banlist/banlist.json。

权威禁卡表来源：playriftbound.com /en-us/rules-hub/ 正文（2026-07-16 更新）。
该页明确列出 sanctioned Constructed 与 2v2 Constructed 的禁卡。

禁卡分两类:
  - 标准 Constructed 禁卡 (5 卡 + 5 战场)
  - 2v2 Constructed 额外禁 (1 传奇；2v2 含标准全部)

本脚本把官方禁卡名与卡牌数据库 (data/cards/cards.json) 做匹配，
匹配到的记 internal_id，未匹配的保留原文供人工核对。

用法: PYTHONPATH=src python scripts/ingest_banlist.py
"""
from __future__ import annotations

import json
from pathlib import Path

from riftbench.banlist import BanCategory, BanEntry, BanFormat, Banlist
from riftbench.cards import CardDatabase

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "banlist" / "banlist.json"

# 权威禁卡表（rules-hub，2026-07-16）
# 标准赛制禁卡
STANDARD_CARDS = [
    "Called Shot",
    "Draven, Vanquisher",
    "Fight or Flight",
    "Scrapheap",
    "Stealthy Pursuer",
]
STANDARD_BATTLEFIELDS = [
    "The Arena's Greatest",
    "Aspirant's Climb",
    "The Dreaming Tree",   # rules-hub 写 "Dreaming Tree"，实际卡名 "The Dreaming Tree"
    "Obelisk of Power",
    "Reaver's Row",
]
# 2v2 额外禁
TEAM_2V2_EXTRA_LEGENDS = [
    "Master Yi, Wuju Bladesman",   # 实际卡库为 "Wuju Master" 等，见 match_note
]

# 名称匹配的别名/修正（rules-hub 原文 -> 卡库实际卡名）
NAME_OVERRIDES = {
    "Dreaming Tree": "The Dreaming Tree",
    "Master Yi, Wuju Bladesman": "Wuju Master",  # 易的传奇在卡库的名称
}


def match_card(db: CardDatabase, name: str) -> tuple[str | None, str | None, str | None]:
    """返回 (internal_id, public_code, match_note)。"""
    lookup = NAME_OVERRIDES.get(name, name)
    # 精确匹配（大小写不敏感）
    for c in db.cards:
        if c.static.name.lower() == lookup.lower():
            return c.static.internal_id, c.static.public_code, None if lookup == name else f"官方名 '{name}' 映射到卡库 '{c.static.name}'"
    # 模糊：包含关系
    for c in db.cards:
        if not c.is_variant and lookup.lower() in c.static.name.lower():
            return c.static.internal_id, c.static.public_code, f"模糊匹配：'{name}' -> '{c.static.name}'"
    return None, None, f"未在卡库中匹配到 '{name}'（供人工核对）"


def build_banlist(db: CardDatabase) -> Banlist:
    entries: list[BanEntry] = []
    for name in STANDARD_CARDS:
        iid, pcode, note = match_card(db, name)
        entries.append(BanEntry(
            name=name, category=BanCategory.CARD,
            formats=[BanFormat.STANDARD, BanFormat.TEAM_2V2],
            card_internal_id=iid, card_public_code=pcode, match_note=note,
        ))
    for name in STANDARD_BATTLEFIELDS:
        iid, pcode, note = match_card(db, name)
        entries.append(BanEntry(
            name=name, category=BanCategory.BATTLEFIELD,
            formats=[BanFormat.STANDARD, BanFormat.TEAM_2V2],
            card_internal_id=iid, card_public_code=pcode, match_note=note,
        ))
    for name in TEAM_2V2_EXTRA_LEGENDS:
        iid, pcode, note = match_card(db, name)
        entries.append(BanEntry(
            name=name, category=BanCategory.LEGEND,
            formats=[BanFormat.TEAM_2V2],
            card_internal_id=iid, card_public_code=pcode, match_note=note,
        ))
    return Banlist(
        last_updated="2026-07-16",
        source_url="https://playriftbound.com/en-us/rules-hub/",
        entries=entries,
    )


def main() -> None:
    db = CardDatabase.load(ROOT / "data" / "cards" / "cards.json")
    bl = build_banlist(db)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(bl.model_dump_json(indent=2), encoding="utf-8")
    print(f"[banlist] {len(bl.entries)} 条禁卡记录 -> {OUT}")
    matched = sum(1 for e in bl.entries if e.card_internal_id)
    print(f"[banlist] 匹配到卡库: {matched}/{len(bl.entries)}")
    for e in bl.entries:
        flag = "OK" if e.card_internal_id else "MISS"
        print(f"  [{flag}] {e.category.value:11} {e.name!r:32} formats={[f.value for f in e.formats]} {e.match_note or ''}")
    print(f"\n[banlist] 标准赛制禁卡: {len(bl.by_format(BanFormat.STANDARD))} 张")
    print(f"[banlist] 2v2 赛制禁卡: {len(bl.by_format(BanFormat.TEAM_2V2))} 张")


if __name__ == "__main__":
    main()
