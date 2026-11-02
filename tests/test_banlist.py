"""禁卡表测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import json
from riftbench.banlist import BanCategory, BanFormat, Banlist
from riftbench.cards import CardDatabase

BANLIST_JSON = Path(__file__).resolve().parents[1] / "data" / "banlist" / "banlist.json"


def _load() -> Banlist:
    return Banlist.model_validate_json(BANLIST_JSON.read_text(encoding="utf-8"))


def test_banlist_loads():
    bl = _load()
    assert len(bl.entries) > 0


def test_standard_has_10_entries():
    """标准赛制: 5 卡 + 5 战场 = 10。"""
    bl = _load()
    std = bl.by_format(BanFormat.STANDARD)
    assert len(std) == 10, f"标准赛制禁卡应为 10，实得 {len(std)}"


def test_2v2_has_11_entries():
    """2v2 含标准全部 + 1 传奇 = 11。"""
    bl = _load()
    t = bl.by_format(BanFormat.TEAM_2V2)
    assert len(t) == 11


def test_all_entries_match_card_db():
    """所有禁卡应匹配到卡牌库 internal_id（v1.0 范围内 100% 匹配）。"""
    bl = _load()
    misses = [e.name for e in bl.entries if not e.card_internal_id]
    assert misses == [], f"未匹配禁卡: {misses}"


def test_matched_ids_exist_in_card_db():
    """禁卡 internal_id 必须在卡牌库中真实存在。"""
    bl = _load()
    db = CardDatabase.load(Path(__file__).resolve().parents[1] / "data" / "cards" / "cards.json")
    for e in bl.entries:
        if e.card_internal_id:
            assert db.get(e.card_internal_id) is not None, f"{e.name} 的 internal_id {e.card_internal_id} 不在卡库"


def test_category_distribution():
    bl = _load()
    cats = {e.category for e in bl.entries}
    assert BanCategory.CARD in cats
    assert BanCategory.BATTLEFIELD in cats
    assert BanCategory.LEGEND in cats


def test_known_banned_cards_present():
    bl = _load()
    names = {e.name for e in bl.entries}
    assert "Called Shot" in names
    assert "Draven, Vanquisher" in names
    assert "Scrapheap" in names


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}"); failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
