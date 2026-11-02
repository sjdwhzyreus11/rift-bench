"""卡牌数据库冒烟测试 — 验证入库产物的完整性与自洽性。

运行: PYTHONPATH=src python -m pytest tests/test_cards_ingest.py -v
或直接: PYTHONPATH=src python tests/test_cards_ingest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.cards import CardDatabase
from riftbench.cards.model import CardType, Domain, Orientation, Rarity, SetId, SuperType

CARDS_JSON = Path(__file__).resolve().parents[1] / "data" / "cards" / "cards.json"


def _load() -> CardDatabase:
    return CardDatabase.load(CARDS_JSON)


def test_database_loads():
    db = _load()
    assert len(db.cards) > 0, "卡牌库为空"


def test_total_count_matches_scraped():
    """全集应为 1189 张 (主版本 1020 + 变体 169)。"""
    db = _load()
    assert len(db.cards) == 1189, f"期望 1189 张，实得 {len(db.cards)}"


def test_all_four_sets_present():
    """set1-4 全量入库 (OGN/SFD/UNL/VEN)，OGS 新手系列也在。"""
    db = _load()
    main_sets = {c.static.set_id for c in db.cards if not c.is_variant}
    assert SetId.OGN in main_sets
    assert SetId.SFD in main_sets
    assert SetId.UNL in main_sets
    assert SetId.VEN in main_sets
    assert SetId.OGS in main_sets


def test_every_card_has_required_static_fields():
    db = _load()
    for c in db.cards:
        s = c.static
        assert s.internal_id, f"missing id: {c}"
        assert s.name, f"missing name: {c}"
        assert s.collector_number >= 1
        assert s.set_id in SetId
        assert s.rarity in Rarity
        assert s.orientation in Orientation
        # 普通卡至少一个 type；Token 卡允许空 type 但必有 super_type=token
        if not s.types:
            assert s.is_token, f"既无 type 又非 token: {s.internal_id}"


def test_units_have_might():
    """单位卡必须有战力 might。"""
    db = _load()
    units = [c for c in db.cards if CardType.UNIT in c.static.types and not c.is_variant]
    assert len(units) > 0
    for c in units:
        assert c.static.might is not None, f"unit missing might: {c.static.internal_id}"


def test_effects_text_has_no_raw_tokens():
    """效果文本不应残留 :rb_ token 占位符。"""
    import re
    db = _load()
    offenders = [c.static.internal_id for c in db.cards if re.search(r":rb_", c.effects.text)]
    assert offenders == [], f"残留 :rb_ token 的卡: {offenders[:10]}"


def test_runes_have_fixed_text_or_notext():
    """符文 text 应为空或 '[NO TEXT]'（基础符文能力由规则固定）。"""
    db = _load()
    runes = [c for c in db.cards if CardType.RUNE in c.static.types]
    assert len(runes) > 0
    for c in runes:
        t = c.effects.text.strip()
        assert t == "" or t == "[NO TEXT]", f"rune 异常文本 {c.static.internal_id}: {t!r}"


def test_domains_subset_of_known():
    db = _load()
    known = {Domain.ORDER, Domain.MIND, Domain.BODY, Domain.FURY, Domain.CALM, Domain.CHAOS, Domain.COLORLESS}
    for c in db.cards:
        for d in c.static.domains:
            assert d in known, f"未知 domain {d} on {c.static.internal_id}"


def test_variant_pointer_integrity():
    """主版本的 variants id 必须指向实际存在的卡。"""
    db = _load()
    for c in db.cards:
        if c.is_variant:
            continue
        for vid in c.variants:
            assert db.get(vid) is not None, f"{c.static.internal_id} 指向不存在的变体 {vid}"


def test_key_by_id_index_complete():
    db = _load()
    assert len(db._by_id) == len(db.cards)


def test_sample_known_cards():
    """抽样验证几张已知卡的属性。"""
    db = _load()
    # Abandon: UNL 法术, chaos, 2 费
    c = db.get_main("UNL", 131)
    assert c is not None
    assert c.static.name == "Abandon"
    assert CardType.SPELL in c.static.types
    assert Domain.CHAOS in c.static.domains
    assert c.static.energy == 2
    assert "Reaction" in c.effects.text


def test_tokens_have_token_supertype():
    """Token 卡 (如 Buff/XP Tracker) 应有 super_type=token。"""
    db = _load()
    tokens = [c for c in db.cards if c.static.is_token]
    assert len(tokens) > 0, "未找到任何 token 卡"
    for c in tokens:
        assert SuperType.TOKEN in c.static.super_types


def test_alias_mapping_for_deceiver():
    """卡库简称 'Deceiver' 应带官方全名别名 'Leblanc, Deceiver' (勘误用全名)。"""
    db = _load()
    deceiver = [c for c in db.cards if c.static.name == "Deceiver" and c.static.set_id.value == "UNL"]
    assert deceiver, "未找到 UNL 的 Deceiver"
    for c in deceiver:
        assert "Leblanc, Deceiver" in c.static.aliases


if __name__ == "__main__":
    # 直接运行模式：逐个跑并打印
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
