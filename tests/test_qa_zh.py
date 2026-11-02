"""P5.3 中英卡名对照测试（tests/test_qa_zh.py）。

覆盖:
  - 映射产物完整性（by_full/by_hero/by_subtitle，RAD 已过滤）
  - 编号对照正确性（中文编号 → 英文名）
  - CardMatcher 中文匹配（全名/英雄简称/别名）
  - 端到端中文提问
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.qa.card_match import CardMatcher
from riftbench.qa.corpus import Corpus

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "data" / "qa" / "card_name_map.json"


def _map():
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def _matcher():
    return CardMatcher(Corpus(ROOT).load())


# ---------- 映射产物 ----------

def test_map_exists_and_nonempty():
    assert MAP_PATH.exists(), "card_name_map.json 不存在（先运行 ingest_cards_zh.py）"
    m = _map()
    assert len(m["by_full"]) > 500, f"by_full 过少: {len(m['by_full'])}"
    assert len(m["by_hero"]) > 50, f"by_hero 过少: {len(m['by_hero'])}"


def test_rad_filtered():
    """RAD（第五弹）应被过滤。meta 记录 filtered_rad>0，且 by_code 无 RAD 前缀。"""
    m = _map()
    assert m["meta"]["filtered_rad"] > 0, "应过滤 RAD"
    rad = [k for k in m["by_code"] if k.startswith("RAD")]
    assert not rad, f"by_code 不应含 RAD: {rad[:3]}"


def test_number_alignment_samples():
    """编号对照抽样：中文全名 → 英文名 正确。"""
    m = _map()
    by_full = m["by_full"]
    # 已知对照（编号 OGN·001/298 等）
    assert by_full.get("灼焰飞龙") == "Blazing Scorcher"
    assert by_full.get("海兽钓钩") == "Baited Hook"
    assert by_full.get("安蓓萨 - 恶狼意志") == "Ambessa, The Wolf"


def test_hero_mapping():
    """中文英雄简称 → 英文名候选列表。"""
    m = _map()
    hero = m["by_hero"]
    for zh in ["阿狸", "亚索", "德莱文"]:
        assert zh in hero, f"缺英雄 {zh}"
        assert any("Ahri" in x for x in hero["阿狸"]) if zh == "阿狸" else True


# ---------- CardMatcher 中文匹配 ----------

def test_match_zh_hero():
    mm = _matcher()
    res = mm.match_all("阿狸的效果")
    names = [r["name"] for r in res]
    assert any("Ahri" in n for n in names), f"应匹配 Ahri: {names}"


def test_match_zh_full():
    mm = _matcher()
    res = mm.match_all("灼焰飞龙的效果")
    names = [r["name"] for r in res]
    assert "Blazing Scorcher" in names, f"应匹配 Blazing Scorcher: {names}"
    assert any(r["match_type"] == "zh_full" for r in res)


def test_match_zh_hero_type():
    mm = _matcher()
    res = mm.match_all("亚索怎么结算")
    assert any(r["match_type"] == "zh_hero" for r in res), "应由英雄简称匹配"


def test_match_zh_subtitle():
    mm = _matcher()
    res = mm.match_all("复仇天使这张卡")
    assert res, "别名应能匹配"


def test_match_english_still_works():
    """英文匹配不受中文路径影响。"""
    mm = _matcher()
    res = mm.match_all("Adaptatron 的效果")
    assert any(r["name"] == "Adaptatron" for r in res)


# ---------- 端到端 ----------

def test_agent_zh_hero():
    from riftbench.qa.agent import RiftboundQA
    qa = RiftboundQA(ROOT)
    r = qa.answer("阿狸的效果是什么")
    assert any("Ahri" in c for c in r["cards"]), f"cards: {r['cards']}"


def test_agent_zh_full_card():
    from riftbench.qa.agent import RiftboundQA
    qa = RiftboundQA(ROOT)
    r = qa.answer("灼焰飞龙的效果")
    assert "Blazing Scorcher" in r["cards"], f"cards: {r['cards']}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {type(e).__name__} {e}"); failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


# ---------- 多类型卡案例（用户报告的真实漏洞） ----------

def test_multi_type_card_case():
    """散装机械魄罗 = Patched Porobot，既是单位又是装备（中文库类别 [单位,装备]）。
    英文源只标 unit，须由中文类别补全为 unit+gear。"""
    mm = _matcher()
    r = mm.match_all("慧移动时弃置一张散装机械魄罗")
    assert r, "应匹配到散装机械魄罗"
    c = r[0]
    assert c["name"] == "Patched Porobot", c["name"]
    assert "unit" in c["types"] and "gear" in c["types"], f"应为多类型: {c['types']}"


def test_multi_type_rule_attached():
    """多类型卡的证据应附带规则 178.3。"""
    from riftbench.qa.evidence import EvidenceCollector
    ev = EvidenceCollector(Corpus(ROOT).load()).collect("散装机械魄罗弃置时触发什么")
    rule_ids = [ch["anchor_rule"] for ch in ev["rules"]]
    assert any(r in ("178.3", "178", "177") for r in rule_ids), f"应附带多类型规则: {rule_ids}"


def test_multi_type_shown_in_facts():
    """材料块应显示卡牌类型 unit/gear。"""
    from riftbench.qa.evidence import EvidenceCollector
    col = EvidenceCollector(Corpus(ROOT).load())
    ev = col.collect("散装机械魄罗")
    facts = col.to_facts("散装机械魄罗", ev)
    assert "unit/gear" in facts, "材料应显示多类型"
