"""FAQ 数据测试 — 验证 artifacts 的完整性与自洽性。

运行: python -m pytest tests/test_faq.py -v
或直接: python tests/test_faq.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import re

from riftbench.faq import FaqCollection, FaqSet

ROOT = Path(__file__).resolve().parents[1]
FAQ_JSON = ROOT / "data" / "faq" / "faq.json"
BY_SET_DIR = ROOT / "data" / "faq" / "by_set"

SYMBOL_RE = re.compile(r"\[(?:C|M|A|T|E|\d+)\]")


def _load() -> FaqCollection:
    return FaqCollection.load(FAQ_JSON)


def test_faq_loads():
    col = _load()
    assert len(col.entries) > 0


def test_every_entry_has_question_and_answer():
    col = _load()
    for e in col.entries:
        assert e.set in FaqSet, f"unknown set {e.set}"
        assert e.question.strip(), f"空问题: {e.model_dump()}"
        assert e.answer.strip(), f"空答案: {e.question!r}"


def test_origins_all_deprecated():
    """origins FAQ 全文已废弃 -> 所有 OGN 条目 deprecated=true。"""
    col = _load()
    ogn = col.by_set(FaqSet.OGN)
    assert len(ogn) > 0
    assert all(e.deprecated for e in ogn)


def test_other_sets_not_deprecated():
    col = _load()
    for s in (FaqSet.SFD, FaqSet.UNL, FaqSet.VEN):
        for e in col.by_set(s):
            assert not e.deprecated, f"{s.value} 不应 deprecated: {e.question!r}"


def test_each_set_has_entries():
    col = _load()
    assert len(col.by_set(FaqSet.OGN)) >= 80
    assert len(col.by_set(FaqSet.SFD)) >= 20
    assert len(col.by_set(FaqSet.UNL)) >= 5
    assert len(col.by_set(FaqSet.VEN)) >= 20


def test_rules_symbols_preserved():
    col = _load()
    with_sym = sum(
        1 for e in col.entries
        if SYMBOL_RE.search(e.question) or SYMBOL_RE.search(e.answer)
    )
    assert with_sym >= 30, f"FAQ 中规则符号条目过少: {with_sym}"


def test_origins_topic_nonempty():
    """origins 的 Q&A 来自 accordion，主题应为小节副标题。"""
    col = _load()
    ogn = col.by_set(FaqSet.OGN)
    known = {"Scoring", "Movement", "Combat", "Hidden", "Timing", "Miscellaneous"}
    topics = {e.topic for e in ogn}
    assert known <= topics, f"缺少预期主题: {known - topics}"
    assert all(e.topic.strip() for e in ogn)


def test_spiritforged_card_topics():
    """spiritforged FAQ 主题应包含卡片名，且主题-问题关联正确。"""
    col = _load()
    sfd = col.by_set(FaqSet.SFD)
    topics = {e.topic for e in sfd}
    for expect in ("Blood Rush", "Deathgrip", "Jax, Unmatched", "Tianna Crownguard"):
        assert expect in topics, f"SFD 缺少主题 {expect}"
    # 抽查特定 主题 -> 问题 关联
    pairs = [
        ("Blood Rush", "Should Blood Rush say"),
        ("Jax, Unmatched", "How does Jax, Unmatched work"),
        ("Tianna Crownguard", "Can I still conquer and hold battlefields"),
        ("Cards that Reduce Might", "Might"),
    ]
    for t, q_check in pairs:
        qs = [e.question for e in sfd if e.topic == t]
        assert any(q_check in q for q in qs), f"主题 {t!r} 下找不到问题片段 {q_check!r}"


def test_unleashed_topic_is_faq_section():
    """unleashed FAQ 的问答位于 'Frequently Asked Questions' 小节。"""
    col = _load()
    unl = col.by_set(FaqSet.UNL)
    assert all(e.topic == "Frequently Asked Questions" for e in unl)


def test_multi_paragraph_answer_joined():
    """跨段答案应合并，且保留换行分隔。"""
    col = _load()
    multi = next(e for e in col.entries if "\n" in e.answer)
    assert multi.answer.strip()


def test_origins_sample_content():
    col = _load()
    ogn = col.by_set(FaqSet.OGN)
    by_q = {e.question for e in ogn}
    assert "How do I score? How are conquer and hold different?" in by_q


def test_by_set_slices_match():
    col = _load()
    for s in FaqSet:
        slice_path = BY_SET_DIR / f"{s.value}.json"
        assert slice_path.exists(), f"缺少分片 {slice_path}"
        sub = FaqCollection.load(slice_path)
        assert len(sub.entries) == len(col.by_set(s))
        assert all(e.set == s for e in sub.entries)


def test_vendetta_flat_topic_empty():
    """vendetta FAQ 页面无主题标题，topic 留空属预期。"""
    col = _load()
    ven = col.by_set(FaqSet.VEN)
    assert all(e.topic == "" for e in ven)
    # 抽查 Abandon 相关问题
    abandons = [e for e in ven if "Abandon" in e.question]
    assert abandons, "vendetta FAQ 应含 Abandon 相关问题"
    assert all(e.answer.strip() for e in abandons)


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