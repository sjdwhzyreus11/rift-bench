"""规则语料索引测试 — 验证英文核心规则解析产物的完整性与关键规则配对。

运行: python -m pytest tests/test_rules_ingest.py -v
或直接: PYTHONPATH=src python tests/test_rules_ingest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

RULES_INDEX = Path(__file__).resolve().parents[1] / "data" / "rules" / "core_rules_index.json"
CHAPTERS = Path(__file__).resolve().parents[1] / "data" / "rules" / "chapters.json"


def _load_index() -> dict[str, str]:
    import json
    return json.loads(RULES_INDEX.read_text(encoding="utf-8"))


def test_index_loads_and_nonempty():
    idx = _load_index()
    assert len(idx) > 1000, f"规则数过少: {len(idx)}"


def test_no_empty_text():
    """所有规则正文必须非空（交错提取模式下应无空正文）。"""
    idx = _load_index()
    empty = [k for k, v in idx.items() if not v.strip()]
    assert empty == [], f"空正文规则: {empty[:10]}"


def test_no_duplicate_keys():
    """JSON dict 天然去重；此测试防御未来改为 list 时的重复。"""
    import json
    raw = RULES_INDEX.read_text(encoding="utf-8")
    assert raw.count('"rule"') == 0  # index 是 dict 形式，无 "rule" 字段


def test_golden_rule():
    """002 = 黄金法则 (Card text supersedes rules text)。"""
    idx = _load_index()
    assert "002" in idx
    assert "card text supersedes" in idx["002"].lower()


def test_cant_beats_can():
    """054 = Can't beats Can。"""
    idx = _load_index()
    assert "054" in idx
    assert "can't beats can" in idx["054"].lower()


def test_do_as_much_as_you_can():
    """055 = 容错执行 (do as much as you can)。"""
    idx = _load_index()
    assert "055" in idx
    assert "do as much as you can" in idx["055"].lower()


def test_chosen_champion():
    """103.2.a = Chosen Champion (选定英雄)。"""
    idx = _load_index()
    assert "103.2.a" in idx
    assert "champion" in idx["103.2.a"].lower()


def test_states_of_turn():
    """307 = 回合状态机章节。"""
    idx = _load_index()
    assert "307" in idx
    assert "state" in idx["307"].lower()


def test_combat_damage_assignment():
    """465.2.c = 战斗伤害分配; 465.2.c.5 = 决定性替换分配期生效 (边界 case 3)。"""
    idx = _load_index()
    assert "465.2.c" in idx
    assert "assigns" in idx["465.2.c"].lower() or "assign" in idx["465.2.c"].lower()
    assert "465.2.c.5" in idx
    assert "replacement" in idx["465.2.c.5"].lower()


def test_target_leaves_and_returns():
    """359.3.e.2 = 目标离场再回场非法 (边界 case 1)。"""
    idx = _load_index()
    assert "359.3.e.2" in idx
    assert "illegal" in idx["359.3.e.2"].lower()


def test_replacement_simultaneous():
    """370.4 = 替换效果对同时离开事件的应用 (边界 case 2 母规则)。"""
    idx = _load_index()
    assert "370.4" in idx
    assert "replacement" in idx["370.4"].lower()


def test_keywords_present():
    """关键字 805(Accelerate)/813(Reaction)/815(Tank) 存在。"""
    idx = _load_index()
    assert "805" in idx
    assert "813" in idx and "reaction" in idx["813"].lower()
    assert "815" in idx and "tank" in idx["815"].lower()


def test_chapters_built():
    """章节映射已生成。"""
    import json
    ch = json.loads(CHAPTERS.read_text(encoding="utf-8"))
    assert len(ch) > 50
    # 几个已知章节
    assert ch.get("100") == "Game Concepts"
    assert ch.get("800") == "Keywords"


if __name__ == "__main__":
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
