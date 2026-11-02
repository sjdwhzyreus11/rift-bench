"""语料加载（qa/corpus.py）— 加载所有可检索语料源。

语料源（均英文，结构干净）:
  - 规则索引 data/rules/core_rules_index.json（2381 条，{rule: text}）
  - 章节 data/rules/chapters.json（顶级编号→章节名）
  - 卡牌库 data/cards/cards.json（name + 效果文本）
  - FAQ data/faq/faq.json（171 条）
  - 勘误 data/errata/errata.json（63 条）
  - 术语表 data/qa/terms.json（中英映射，桥接中文问题↔英文语料）

每个语料源 → list[Doc(id, text, meta)]，供 retriever 检索。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Doc:
    """一条可检索文档。"""
    id: str
    text: str
    source: str          # 'rules'/'cards'/'faq'/'errata'/'chapters'
    meta: dict = field(default_factory=dict)


class Corpus:
    """全部语料源。"""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or Path(__file__).resolve().parents[3]
        self.rules_index: dict[str, str] = {}
        self.chapters: dict[str, str] = {}
        self.terms: dict[str, str] = {}
        self.cards: list[dict] = []
        self.faq: list[dict] = []
        self.errata: list[dict] = []
        self.docs: list[Doc] = []

    # ---------- 加载 ----------

    def load(self) -> "Corpus":
        self._load_rules()
        self._load_chapters()
        self._load_cards()
        self._load_faq()
        self._load_errata()
        self._load_terms()
        self._build_docs()
        return self

    def _read_json(self, rel: str):
        p = self.root / rel
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def _load_rules(self) -> None:
        data = self._read_json("data/rules/core_rules_index.json")
        if data:
            self.rules_index = {str(k): str(v) for k, v in data.items()}

    def _load_chapters(self) -> None:
        data = self._read_json("data/rules/chapters.json")
        if data:
            self.chapters = {str(k): str(v) for k, v in data.items()}

    def _load_cards(self) -> None:
        data = self._read_json("data/cards/cards.json")
        if data and isinstance(data, dict) and "cards" in data:
            self.cards = [c for c in data["cards"] if not c.get("is_variant")]
        elif isinstance(data, list):
            self.cards = [c for c in data if not c.get("is_variant")]

    def _load_faq(self) -> None:
        data = self._read_json("data/faq/faq.json")
        if data:
            self.faq = data if isinstance(data, list) else data.get("entries", [])

    def _load_errata(self) -> None:
        data = self._read_json("data/errata/errata.json")
        if data:
            self.errata = data if isinstance(data, list) else data.get("entries", [])

    def _load_terms(self) -> None:
        data = self._read_json("data/qa/terms.json")
        if data:
            self.terms = {str(k): str(v) for k, v in data.items()}

    # ---------- 文档构建 ----------

    def _build_docs(self) -> None:
        docs: list[Doc] = []
        # 规则
        for rule, text in self.rules_index.items():
            if not text:
                continue
            chap = self.chapters.get(rule.split(".")[0], "")
            docs.append(Doc(id=f"rule:{rule}", text=text, source="rules",
                            meta={"rule_id": rule, "chapter": chap}))
        # 卡牌
        for c in self.cards:
            name = c.get("static", {}).get("name", "")
            txt = (c.get("effects", {}) or {}).get("text", "")
            if name:
                docs.append(Doc(id=f"card:{name}", text=f"{name}: {txt}", source="cards",
                                meta={"card_name": name, "card_data": c}))
        # FAQ
        for i, f in enumerate(self.faq):
            q = f.get("question", "")
            a = f.get("answer", "")
            if q:
                docs.append(Doc(id=f"faq:{i}", text=f"{q} {a}", source="faq",
                                meta={"faq": f}))
        # 勘误
        for i, e in enumerate(self.errata):
            nm = e.get("card_name", "")
            new = e.get("new_text", "")
            if new:
                docs.append(Doc(id=f"errata:{i}", text=f"{nm}: {new}", source="errata",
                                meta={"errata": e}))
        self.docs = docs

    # ---------- 查询辅助 ----------

    def get_rule(self, rule_id: str) -> Optional[str]:
        return self.rules_index.get(rule_id)

    def find_cards(self, name: str) -> list[dict]:
        """按卡名精确/包含匹配（大小写不敏感）。"""
        n = name.lower()
        hits = [c for c in self.cards if n == c.get("static", {}).get("name", "").lower()]
        if hits:
            return hits
        return [c for c in self.cards if n in c.get("static", {}).get("name", "").lower()][:5]