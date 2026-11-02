"""勘误数据测试 — 验证 artifacts 的完整性与自洽性。

运行: python -m pytest tests/test_errata.py -v
或直接: python tests/test_errata.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import re

from riftbench.errata import ErrataCollection, ErrataSet
from riftbench.errata.model import ErrataEntry

ROOT = Path(__file__).resolve().parents[1]
ERRATA_JSON = ROOT / "data" / "errata" / "errata.json"
BY_SET_DIR = ROOT / "data" / "errata" / "by_set"

SYMBOL_RE = re.compile(r"\[(?:C|M|A|T|E|\d+)\]")


def _load() -> ErrataCollection:
    return ErrataCollection.load(ERRATA_JSON)


def test_errata_loads():
    col = _load()
    assert len(col.entries) > 0


def test_every_entry_has_nonempty_fields():
    col = _load()
    for e in col.entries:
        assert e.set in ErrataSet, f"unknown set {e.set}"
        assert e.card_name.strip(), f"empty card_name: {e.model_dump()}"
        assert e.new_text.strip(), f"empty new_text: {e.card_name}"
        assert e.old_text.strip(), f"empty old_text: {e.card_name}"


def test_all_four_sets_present():
    col = _load()
    sets = {e.set for e in col.entries}
    assert ErrataSet.OGN in sets
    assert ErrataSet.SFD in sets
    assert ErrataSet.UNL in sets
    assert ErrataSet.VEN in sets


def test_origins_has_dozens_of_entries():
    """Origins 是首个系列，勘误应较多（几十条）。"""
    col = _load()
    ogn = col.by_set(ErrataSet.OGN)
    assert len(ogn) >= 30, f"OGN 勘误应为几十条，实得 {len(ogn)}"


def test_each_set_reasonable_count():
    col = _load()
    assert len(col.by_set(ErrataSet.SFD)) >= 10
    assert len(col.by_set(ErrataSet.UNL)) >= 5
    assert len(col.by_set(ErrataSet.VEN)) >= 1


def test_rules_symbols_preserved():
    """规则符号 [C]/[M]/[1]/[A]/[T] 应原样保留。"""
    col = _load()
    # Ava Achiever 新文本含 [C] 与 [Hidden]
    ava = next(e for e in col.entries if e.card_name == "Ava Achiever")
    assert "[C]" in ava.new_text and "[C]" in ava.old_text
    assert "[Hidden]" in ava.new_text
    # 整体统计：相当比例条目应含规则符号
    with_sym = sum(1 for e in col.entries if SYMBOL_RE.search(e.new_text) or SYMBOL_RE.search(e.old_text))
    assert with_sym >= len(col.entries) * 0.5, f"规则符号保留比例过低: {with_sym}/{len(col.entries)}"


def test_no_raw_cms_tokens_leak():
    """不应残留 :rb_ CMS token 占位符。"""
    col = _load()
    bad = [e.card_name for e in col.entries if re.search(r":rb_", e.new_text + e.old_text)]
    assert bad == [], f"残留 :rb_ token: {bad}"


def test_no_editorial_note_leak():
    """'Note: Text only differs...' 是语言备注，不应混入卡面文本。"""
    col = _load()
    bad = [e.card_name for e in col.entries if "Note:" in e.new_text or "Note:" in e.old_text]
    assert bad == [], f"备注混入卡面文本: {bad}"


def test_multi_paragraph_text_join_preserved():
    """多段勘误文本应合并且保留换行分隔。"""
    col = _load()
    blind = next(e for e in col.entries if e.card_name == "Blind Fury")
    assert "\n" in blind.new_text
    assert "banish" in blind.new_text  # 新文本关键改动词保留
    assert "banish" not in blind.old_text  # 旧文本无 banish


def test_preamble_paragraphs_excluded():
    """前言叙述不应被误当勘误条目。"""
    col = _load()
    names = {e.card_name for e in col.entries}
    assert "Ava Achiever" in names
    assert "Hey Riftbounders" not in names
    assert len(names) == len(col.entries), "存在重复卡名条目"


def test_vendetta_page_cross_set_attribution():
    """vendetta 页的跨 set 勘误应按小节归属到 SFD/UNL/VEN。"""
    col = _load()
    def card_set(name):
        return [e.set for e in col.entries if e.card_name == name]
    # Spiritforged 小节
    assert card_set("Draven, Vanquisher") == [ErrataSet.SFD]
    assert card_set("Emperor’s Dais") == [ErrataSet.SFD]
    assert card_set("Fizz, Trickster") == [ErrataSet.SFD]
    # Unleashed 小节
    assert card_set("Diana, Lunari") == [ErrataSet.UNL]
    assert card_set("Stalking Wolf") == [ErrataSet.UNL]
    # Vendetta 小节
    assert card_set("Astral Heron") == [ErrataSet.VEN]
    assert card_set("Gangplank, Naval") == [ErrataSet.VEN]
    assert card_set("Resonating Strike") == [ErrataSet.VEN]


def test_spiritforged_and_unleashed_page_cross_set():
    """spiritforged/unleashed 页同样含跨 set 小节。"""
    col = _load()
    def card_set(name):
        return [e.set for e in col.entries if e.card_name == name]
    # spiritforged.html 的 Origins 小节
    assert card_set("Falling Star") == [ErrataSet.OGN]
    assert card_set("Icathian Rain") == [ErrataSet.OGN]
    assert card_set("Reinforce") == [ErrataSet.OGN]
    # unleashed.html 的 Spiritforged 小节
    assert card_set("Guards!") == [ErrataSet.SFD]
    assert card_set("Relentless Pursuit") == [ErrataSet.SFD]


def test_by_set_slices_match():
    """by_set 分片文件应与全集一致。"""
    col = _load()
    for s in ErrataSet:
        slice_path = BY_SET_DIR / f"{s.value}.json"
        assert slice_path.exists(), f"缺少分片 {slice_path}"
        sub = ErrataCollection.load(slice_path)
        assert len(sub.entries) == len(col.by_set(s))
        assert all(e.set == s for e in sub.entries)


def test_known_specific_entries():
    col = _load()
    entries = {e.card_name: e for e in col.entries}
    # Dune Drake: 添加 "this turn"
    d = entries["Dune Drake"]
    assert "this turn" in d.new_text
    assert "this turn" not in d.old_text
    # The Syren: base 归属修正
    sy = entries["The Syren"]
    assert "to its base" in sy.new_text
    assert "to your base" in sy.old_text


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
        else:
            passed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)