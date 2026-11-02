"""中文卡库入库 + 中英卡名对照（scripts/ingest_cards_zh.py）。

来源: playloltcg.com 中文官方牌库 API。
  POST https://lol-api.playloltcg.com/xcx/card/searchCardCraftWeb
流程:
  1. 读 raw/cards_zh/p*.json（已爬）或调 API 重爬
  2. 过滤 RAD（第五弹未发售，用户要求）
  3. 按编号对照英文库（中文 cardNo 'OGN·001/298' ↔ 英文 publicCode 'OGN-001/298'）
  4. 构建 by_full(中文全名→英文名) / by_hero(中文英雄→英文名列表) / by_subtitle
  5. 落库 data/qa/card_name_map.json

用法: PYTHONPATH=src python scripts/ingest_cards_zh.py
"""
from __future__ import annotations

import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXCLUDE_PREFIXES = {"RAD"}  # 第五弹未发售，用户要求不导入


def load_zh_raw() -> list[dict]:
    """读已爬的 raw/cards_zh/p*.json。"""
    cards = []
    for f in sorted(glob.glob(str(ROOT / "raw" / "cards_zh" / "p*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        cards.extend(d["result"]["list"])
    return cards


def build_en_index() -> dict[tuple[str, str], str]:
    """英文库：(前缀, 序号) -> 英文名。"""
    from riftbench.cards import CardDatabase
    db = CardDatabase.load(ROOT / "data" / "cards" / "cards.json")
    idx: dict[tuple[str, str], str] = {}
    for c in db.cards:
        if c.is_variant:
            continue
        m = re.match(r"([A-Z]+)-(\d+)", c.static.public_code)
        if m:
            idx.setdefault((m.group(1), m.group(2)), c.static.name)
    return idx


def zh_full_name(c: dict) -> str:
    """中文全名 = cardName + (' - ' + subTitle if subTitle)。"""
    name = (c.get("cardName") or "").strip()
    sub = (c.get("subTitle") or "").strip()
    return f"{name} - {sub}" if sub else name


def main() -> None:
    zh = load_zh_raw()
    print(f"[zh] 中文原始卡: {len(zh)}")
    en_idx = build_en_index()
    print(f"[zh] 英文库编号索引: {len(en_idx)}")

    by_full: dict[str, str] = {}
    by_hero: dict[str, list[str]] = defaultdict(list)
    by_subtitle: dict[str, str] = {}
    by_code: dict[str, str] = {}
    by_code_cat: dict[str, list] = {}   # 编号 -> 中文类别（补全英文源缺失的多类型）
    matched = skipped_prefix = no_match = 0

    for c in zh:
        card_no = c.get("cardNo") or ""
        prefix = re.split(r"[·\-]", card_no)[0] if card_no else ""
        if prefix in EXCLUDE_PREFIXES:
            skipped_prefix += 1
            continue
        m = re.match(r"([A-Z0-9]+)[·\-](\d+)", card_no)
        if not m:
            no_match += 1
            continue
        key = (m.group(1), m.group(2))
        en_name = en_idx.get(key)
        if not en_name:
            no_match += 1
            continue
        matched += 1
        full = zh_full_name(c)
        by_full.setdefault(full, en_name)
        by_code.setdefault(card_no, en_name)
        cats = c.get("cardCategoryNameList") or []
        if cats:
            by_code_cat.setdefault(card_no, cats)
        hero = (c.get("hero") or "").strip()
        if hero:
            en_hero = en_name.split(",")[0].strip()
            if en_name not in by_hero[hero]:
                by_hero[hero].append(en_name)
        sub = (c.get("subTitle") or "").strip()
        if sub:
            by_subtitle.setdefault(sub, en_name)

    out = {
        "by_full": by_full,
        "by_hero": dict(by_hero),
        "by_subtitle": by_subtitle,
        "by_code": by_code,
        "by_code_cat": by_code_cat,   # 编号 -> 中文类别（如 ['单位','装备']）
        "meta": {
            "total": matched,
            "filtered_rad": skipped_prefix,
            "no_en_match": no_match,
            "source": "playloltcg.com",
        },
    }
    out_path = ROOT / "data" / "qa" / "card_name_map.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[zh] 编号对照成功: {matched} / 过滤RAD: {skipped_prefix} / 无英文对应: {no_match}")
    print(f"[zh] by_full={len(by_full)} by_hero={len(by_hero)} by_subtitle={len(by_subtitle)}")
    print(f"[zh] 落库 -> {out_path}")
    # 抽样
    for k in list(by_full)[:3]:
        print(f"    {k} -> {by_full[k]}")
    for k in list(by_hero)[:3]:
        print(f"    [英雄] {k} -> {by_hero[k][:2]}")


if __name__ == "__main__":
    main()
