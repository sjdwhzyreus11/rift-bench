"""卡牌匹配增强（qa/card_match.py）— 英文（完整/部分/模糊）+ 中文（编号对照）。

中文匹配（P5.3）: 加载 card_name_map.json（中文卡库 ←→ 英文库，按编号对照）:
  - by_full     : 中文全名（如"安蓓萨 - 恶狼意志"）→ 英文名
  - by_hero     : 中文英雄简称（如"阿狸"）→ 英文名候选列表
  - by_subtitle : 中文别名（如"复仇天使"）→ 英文名
英文匹配（P5.1）: 完整名 / 部分名 / 模糊拼写。

输出: list[{name(英文), card_data, text, match_type}]
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Optional

from riftbench.qa.corpus import Corpus


class CardMatcher:
    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self.names = [c.get("static", {}).get("name", "")
                      for c in corpus.cards if c.get("static", {}).get("name")]
        self._by_name = {}
        for c in corpus.cards:
            nm = c.get("static", {}).get("name", "")
            if nm:
                self._by_name.setdefault(nm, c)
        self._names_lower = {n.lower(): n for n in self.names}
        self.zh = self._load_zh_map(corpus.root)
        # 英文名 -> 中文类别（补全英文源缺失的多类型，如 VEN·058 散装机械魄罗=[单位,装备]）
        self._en_to_cat: dict[str, list] = {}
        if self.zh:
            by_code = self.zh.get('by_code', {})
            by_cat = self.zh.get('by_code_cat', {})
            for card_no, en in by_code.items():
                if card_no in by_cat:
                    self._en_to_cat.setdefault(en, by_cat[card_no])

    def _load_zh_map(self, root: Path) -> Optional[dict]:
        p = Path(root) / "data" / "qa" / "card_name_map.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def match_all(self, question: str, max_cards: int = 5) -> list[dict]:
        found: dict[str, dict] = {}
        # ① 中文路径（优先）
        if self.zh:
            self._match_chinese(question, found)
        # ② 英文完整名
        ql = question.lower()
        for name in sorted(self.names, key=len, reverse=True):
            if name.lower() in ql and name not in found:
                found[name] = self._entry(name, "exact")
        # ③ 英文部分名/前缀
        for tok in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", question):
            tl = tok.lower()
            cands = [n for n in self.names if tl in n.lower()]
            if cands and len(tok) >= 4:
                best = min(cands, key=len)
                found.setdefault(best, self._entry(best, "partial"))
        # ④ 英文模糊拼写
        for tok in re.findall(r"[A-Za-z][A-Za-z'\-]{3,}", question):
            if any(tok.lower() in n.lower() for n in self.names):
                continue
            close = difflib.get_close_matches(tok.lower(), list(self._names_lower.keys()),
                                              n=1, cutoff=0.82)
            if close:
                real = self._names_lower[close[0]]
                found.setdefault(real, self._entry(real, "fuzzy"))
        return list(found.values())[:max_cards]

    def _match_chinese(self, question: str, found: dict) -> None:
        zh = self.zh
        # 全名（最长优先，避免子串吞并）
        for zh_full in sorted(zh.get("by_full", {}), key=len, reverse=True):
            if zh_full and zh_full in question:
                self._add(found, zh["by_full"][zh_full], "zh_full")
        # 英雄简称
        for hero, en_list in zh.get("by_hero", {}).items():
            if hero and hero in question:
                for en in en_list:
                    self._add(found, en, "zh_hero")
        # 别名
        for sub, en in zh.get("by_subtitle", {}).items():
            if sub and len(sub) >= 2 and sub in question:
                self._add(found, en, "zh_subtitle")

    def _add(self, found: dict, en_name: str, match_type: str) -> None:
        if en_name in self._by_name and en_name not in found:
            found[en_name] = self._entry(en_name, match_type)

    _CAT_TO_TYPE = {'单位': 'unit', '装备': 'gear', '法术': 'spell', '传奇': 'legend', '战场': 'battlefield', '符文': 'rune'}

    def _entry(self, name: str, match_type: str) -> dict:
        c = self._by_name.get(name, {})
        en_types = list(c.get("static", {}).get("types", []) or [])
        zh_cats = self._en_to_cat.get(name, [])
        zh_types = [self._CAT_TO_TYPE[x] for x in zh_cats if x in self._CAT_TO_TYPE]
        types = list(dict.fromkeys(en_types + zh_types))
        return {
            "name": name,
            "card_data": c,
            "text": (c.get("effects", {}) or {}).get("text", ""),
            "types": types,
            "zh_categories": zh_cats,
            "match_type": match_type,
        }
