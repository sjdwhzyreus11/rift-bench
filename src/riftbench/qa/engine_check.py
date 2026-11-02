"""引擎核验路由（qa/engine_check.py）— 可计算问题的权威判定。

复用 P0 数据层 + P3 引擎能力:
  - 卡牌详情: 卡名 → 静态属性 + 效果文本（双层模型）
  - 禁卡查询: 卡名 → 是否禁卡（standard/2v2）
  - 构筑校验: 牌表 → 同名上限(103.2.b)/特性匹配(103.1)/专属(103.2.d)/禁卡/符文12

路由判定由 agent.py 根据问题关键词选择。
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from riftbench.banlist import BanFormat, Banlist
from riftbench.cards import CardDatabase


class EngineCheck:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or Path(__file__).resolve().parents[3]
        self.db = CardDatabase.load(self.root / "data" / "cards" / "cards.json")
        bl_path = self.root / "data" / "banlist" / "banlist.json"
        self.banlist = Banlist.model_validate_json(bl_path.read_text(encoding="utf-8")) \
            if bl_path.exists() else None

    # ---------- 卡牌详情 ----------

    def card_detail(self, name: str) -> Optional[dict]:
        hits = [c for c in self.db.cards if not c.is_variant
                and c.static.name.lower() == name.lower()]
        if not hits:
            hits = [c for c in self.db.cards if not c.is_variant
                    and name.lower() in c.static.name.lower()][:3]
        if not hits:
            return None
        c = hits[0]
        return {
            "name": c.static.name,
            "public_code": c.static.public_code,
            "types": [t.value for t in c.static.types],
            "domains": [d.value for d in c.static.domains],
            "energy": c.static.energy,
            "might": c.static.might,
            "rarity": c.static.rarity.value,
            "text": c.effects.text,
        }

    # ---------- 禁卡查询 ----------

    def banned(self, name: str) -> Optional[dict]:
        if self.banlist is None:
            return None
        nm = name.lower()
        for e in self.banlist.entries:
            if e.name.lower() == nm:
                return {"banned": True, "formats": [f.value for f in e.formats],
                        "category": e.category.value}
        return {"banned": False}

    # ---------- 构筑校验 ----------

    def validate_deck(self, decklist: list[tuple[str, int]]) -> dict:
        """校验牌表。decklist: [(卡名, 数量), ...]。

        校验项:
          - 主牌堆 ≥40
          - 同名 ≤3（103.2.b）
          - 禁卡（banlist）
          - 符文牌堆 12 张（若提供）
          - 有传奇（若提供）
        """
        issues: list[str] = []
        name_count = Counter(n for n, q in decklist for _ in range(q))
        total_main = 0
        rune_count = 0
        has_legend = False
        for name, q in name_count.items():
            # 同名上限
            if q > 3:
                issues.append(f"同名超过 3 张: {name} x{q}（规则 103.2.b）")
            # 禁卡
            b = self.banned(name)
            if b and b["banned"]:
                issues.append(f"禁卡: {name}（{'/'.join(b['formats'])}）")
            # 分类
            detail = self.card_detail(name)
            if detail:
                if "rune" in detail["types"]:
                    rune_count += q
                elif "legend" in detail["types"]:
                    has_legend = True
                else:
                    total_main += q
            else:
                issues.append(f"未找到卡牌: {name}")
        # 主牌堆大小
        if total_main < 40:
            issues.append(f"主牌堆 {total_main} 张，需 ≥40")
        if rune_count > 0 and rune_count != 12:
            issues.append(f"符文牌堆 {rune_count} 张，应为 12")
        if not has_legend:
            issues.append("缺少传奇卡牌")
        return {"valid": not issues, "issues": issues,
                "main_size": total_main, "rune_count": rune_count}

    # ---------- 路由 ----------

    def route(self, question: str, decklist: Optional[list[tuple[str, int]]] = None) -> Optional[dict]:
        """按问题关键词路由。"""
        q = question.lower()
        card = self._extract_card_name(question)
        # 禁卡查询
        if "禁" in question and ("禁卡" in question or "ban" in q):
            if card:
                return {"kind": "banlist", **self.banned(card)}
        # 卡牌详情（问题含卡名且是查询型）
        if card and any(kw in question for kw in ("效果", "是什么", "怎么", "卡")):
            detail = self.card_detail(card)
            if detail:
                return {"kind": "card", **detail}
        if decklist is not None:
            return {"kind": "deck", **self.validate_deck(decklist)}
        return None

    def _extract_card_name(self, question: str) -> Optional[str]:
        """从问题提取英文卡名（含空格/逗号）。启发式：找最长连续英文字母段。"""
        import re
        # 优先匹配卡库卡名（最大包含）
        q = question
        best = None
        for c in self.db.cards:
            if not c.is_variant and c.static.name.lower() in q.lower():
                if best is None or len(c.static.name) > len(best):
                    best = c.static.name
        if best:
            return best
        m = re.search(r"[A-Za-z][A-Za-z'\- ]{2,}", question)
        return m.group(0).strip() if m else None