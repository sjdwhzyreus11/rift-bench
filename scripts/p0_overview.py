"""P0 数据基座完整性总览 — 汇总所有入库产物的状态。

用法: PYTHONPATH=src python scripts/p0_overview.py
用于 P0 收尾验收，确认所有数据层就绪。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from riftbench.cards import CardDatabase
from riftbench.banlist import Banlist, BanFormat


def section(title: str) -> None:
    print(f"\n{'='*60}\n{title}\n{'='*60}")


def cards_status() -> dict:
    db = CardDatabase.load(ROOT / "data" / "cards" / "cards.json")
    main = [c for c in db.cards if not c.is_variant]
    by_set = {}
    for c in main:
        by_set[c.static.set_id.value] = by_set.get(c.static.set_id.value, 0) + 1
    return {
        "total": len(db.cards),
        "main_versions": len(main),
        "variants": len(db.cards) - len(main),
        "by_set": by_set,
        "path": "data/cards/cards.json",
    }


def rules_status() -> dict:
    idx = json.loads((ROOT / "data" / "rules" / "core_rules_index.json").read_text(encoding="utf-8"))
    chapters = json.loads((ROOT / "data" / "rules" / "chapters.json").read_text(encoding="utf-8"))
    empty = sum(1 for v in idx.values() if not v.strip())
    return {"total_rules": len(idx), "empty_rules": empty, "chapters": len(chapters),
            "path": "data/rules/core_rules_index.json"}


def banlist_status() -> dict:
    bl = Banlist.model_validate_json((ROOT / "data" / "banlist" / "banlist.json").read_text(encoding="utf-8"))
    matched = sum(1 for e in bl.entries if e.card_internal_id)
    return {"total_entries": len(bl.entries),
            "standard": len(bl.by_format(BanFormat.STANDARD)),
            "team_2v2": len(bl.by_format(BanFormat.TEAM_2V2)),
            "matched_to_card_db": matched,
            "last_updated": bl.last_updated}


def patch_notes_status() -> dict:
    idx_path = ROOT / "data" / "rules" / "patch_notes" / "index.json"
    if not idx_path.exists():
        return {"available": False}
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    return {"available": True, "sets": len(idx), "total_chars": sum(p["chars"] for p in idx)}


def optional_status(name: str, path: str) -> dict:
    p = ROOT / path
    if not p.exists():
        return {"available": False}
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"available": True, "count": len(data), "path": path}
    return {"available": True, "path": path}


def main() -> None:
    print("rift-bench P0 数据基座完整性总览")
    print(f"根目录: {ROOT}")

    section("1. 卡牌数据库")
    c = cards_status()
    print(json.dumps(c, indent=2, ensure_ascii=False))

    section("2. 规则语料索引")
    r = rules_status()
    print(json.dumps(r, indent=2, ensure_ascii=False))

    section("3. 禁卡表")
    b = banlist_status()
    print(json.dumps(b, indent=2, ensure_ascii=False))

    section("4. 核心规则补丁说明")
    p = patch_notes_status()
    print(json.dumps(p, indent=2, ensure_ascii=False))

    section("5. 勘误 (errata)")
    print(json.dumps(optional_status("errata", "data/errata/errata.json"), indent=2, ensure_ascii=False))

    section("6. FAQ")
    print(json.dumps(optional_status("faq", "data/faq/faq.json"), indent=2, ensure_ascii=False))

    section("P0 状态汇总")
    print(f"  卡牌: {c['main_versions']} 主版本 + {c['variants']} 变体 (set1-4 全量+OGS)")
    print(f"  规则: {r['total_rules']} 条 ({r['empty_rules']} 空正文), {r['chapters']} 章节")
    print(f"  禁卡: {b['total_entries']} 条 (标准 {b['standard']} / 2v2 {b['team_2v2']}), {b['matched_to_card_db']}/{b['total_entries']} 匹配卡库")
    print(f"  补丁说明: {'[OK]' if p.get('available') else '[X]'} {p.get('sets',0)} set, {p.get('total_chars',0)} chars")
    e = optional_status("errata", "data/errata/errata.json")
    f = optional_status("faq", "data/faq/faq.json")
    print(f"  勘误: {'[OK]' if e.get('available') else '[X] (agent处理中)'} {e.get('count','?')} 条")
    print(f"  FAQ:  {'[OK]' if f.get('available') else '[X] (agent处理中)'} {f.get('count','?')} 条")


if __name__ == "__main__":
    main()
