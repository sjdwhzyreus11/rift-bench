"""从 raw/cards/page_*.json 解析全量卡牌，落库为标准化 JSON。

流程:
  1. 合并 6 页 (共 1197 张)。
  2. 抽取双层模型：静态属性层 + 效果脚本层 (text 去 HTML)。
  3. 按 (set, collector_number) 主版本去重：portrait 普通版为主版本，
     showcase/landscape/其余同名同号卡为变体，挂主版本下。
  4. 输出 data/cards/cards.json + 按系列的分片 JSON + 摘要。

用法: python scripts/ingest_cards.py
"""
from __future__ import annotations

import glob
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from riftbench.cards.model import (
    Card,
    CardAssets,
    CardEffects,
    CardStatic,
    CardType,
    Domain,
    Orientation,
    Rarity,
    SetId,
    SuperType,
)
from riftbench.cards import CardDatabase

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "raw" / "cards"
OUT_DIR = ROOT / "data" / "cards"

# playriftbound id -> riftbench enum; 容错：未知值保留原字符串
_TYPE_MAP = {e.value: e for e in CardType}
_DOMAIN_MAP = {e.value: e for e in Domain}
_RARITY_MAP = {e.value: e for e in Rarity}
_SET_MAP = {e.value: e for e in SetId}
_SUPER_MAP = {e.value: e for e in SuperType}

# 卡库卡名 -> 官方别名/全名（勘误/FAQ 用全名而卡库用简称时）。
# 键为 (set_id, name) 精确定位，避免误伤同名卡。来源：勘误页人工核对。
_CARD_ALIASES: dict[tuple[str, str], list[str]] = {
    # 卡库简称 "Deceiver" 实为乐芙兰传奇，勘误用全名 "Leblanc, Deceiver"
    ("UNL", "Deceiver"): ["Leblanc, Deceiver"],
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_TOKEN_RE = re.compile(r":rb_[a-z0-9_]+:")

# token -> 规则符号映射（与英文核心规则术语对齐）
# :rb_might: -> [M] (Might，规则用 Might；accessibilityText 用 [S]=Strength，二者同义，统一取规则术语 [M])
# :rb_rune_<domain>: 统一映射为 [C]（此牌自身特性符能）；
#   注：domain 具体值由卡牌自身的 domains 字段决定语义，文本层只需符号 [C]。
# :rb_rune_rainbow: -> [A]（任意特性符能）
_TOKEN_MAP = {
    "rb_exhaust": "[T]",
    "rb_might": "[M]",
    "rb_rune_rainbow": "[A]",
    "rb_rune_fury": "[C]",
    "rb_rune_order": "[C]",
    "rb_rune_body": "[C]",
    "rb_rune_chaos": "[C]",
    "rb_rune_mind": "[C]",
    "rb_rune_calm": "[C]",
}


def _token_to_symbol(tok: str) -> str:
    """把 :rb_xxx: 映射为规则符号。:rb_energy_N: -> [N]，其余查表。"""
    inner = tok.strip().lstrip(":").rstrip(":")  # rb_energy_1
    if inner.startswith("rb_energy_"):
        n = inner[len("rb_energy_"):]
        return f"[{n}]"
    return _TOKEN_MAP.get(inner, tok)  # 未知 token 原样保留


def _strip_html(body: str) -> str:
    """text.richText.body (HTML, 含 :rb_ token) -> 纯文本（token 替换为规则符号）。"""
    if not body:
        return ""
    # 块级标签转换行
    body = body.replace("</p>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    body = _TOKEN_RE.sub(lambda m: _token_to_symbol(m.group(0)), body)
    body = _TAG_RE.sub("", body)
    body = html.unescape(body)
    lines = [_WS_RE.sub(" ", ln).strip() for ln in body.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _enum_or_raise(value: str, mapping: dict, kind: str, ctx: str):
    if value in mapping:
        return mapping[value]
    raise ValueError(f"未知 {kind} 值 {value!r} (卡: {ctx})")


def parse_one(raw: dict) -> Card:
    ctx = raw.get("id") or raw.get("name") or "?"
    types = [
        _enum_or_raise(t["id"], _TYPE_MAP, "cardType", ctx)
        for t in raw.get("cardType", {}).get("type", [])
    ]
    super_types = [
        _enum_or_raise(st["id"], _SUPER_MAP, "superType", ctx)
        for st in raw.get("cardType", {}).get("superType", [])
    ]
    domains = [
        _enum_or_raise(d["id"], _DOMAIN_MAP, "domain", ctx)
        for d in raw.get("domain", {}).get("values", [])
    ]
    set_id = _enum_or_raise(raw["set"]["value"]["id"], _SET_MAP, "set", ctx)
    rarity = _enum_or_raise(raw["rarity"]["value"]["id"], _RARITY_MAP, "rarity", ctx)
    orientation = Orientation(raw.get("orientation", "portrait"))

    # energy
    energy = raw.get("energy")
    energy_val = energy["value"]["id"] if energy and energy.get("value") else None

    # might (仅单位)
    might = raw.get("might")
    might_val = might["value"]["id"] if might and might.get("value") else None

    # tags (结构: {"label":"Tags","tags":["Jayce", ...]} — 字符串列表)
    tags: list[str] = []
    tags_obj = raw.get("tags")
    if isinstance(tags_obj, dict):
        raw_tags = tags_obj.get("tags", [])
        if isinstance(raw_tags, list):
            tags = [t for t in raw_tags if isinstance(t, str)]
    elif isinstance(tags_obj, list):
        tags = [t for t in tags_obj if isinstance(t, str)]

    # illustrator
    ill = raw.get("illustrator", {})
    ill_vals = ill.get("values", []) if isinstance(ill, dict) else []
    illustrator = None
    if ill_vals and isinstance(ill_vals[0], dict):
        illustrator = ill_vals[0].get("label")

    # 效果文本
    text_obj = raw.get("text", {}) if isinstance(raw.get("text"), dict) else {}
    rich = text_obj.get("richText", {}) if isinstance(text_obj, dict) else {}
    text_body = rich.get("body", "") if isinstance(rich, dict) else ""
    text_raw = text_body  # 保留原始 HTML (含 :rb_ token)
    text = _strip_html(text_body)

    card_img = raw.get("cardImage", {}) if isinstance(raw.get("cardImage"), dict) else {}
    assets = CardAssets(
        card_image_url=card_img.get("url"),
        image_width=card_img.get("dimensions", {}).get("width") if isinstance(card_img.get("dimensions"), dict) else None,
        image_height=card_img.get("dimensions", {}).get("height") if isinstance(card_img.get("dimensions"), dict) else None,
    )
    access = card_img.get("accessibilityText", "") or ""

    static = CardStatic(
        internal_id=raw["id"],
        collector_number=raw["collectorNumber"],
        name=raw["name"],
        public_code=raw.get("publicCode", ""),
        set_id=set_id,
        types=types,
        super_types=super_types,
        domains=domains,
        rarity=rarity,
        orientation=orientation,
        energy=energy_val,
        might=might_val,
        tags=tags,
        illustrator=illustrator,
        aliases=_CARD_ALIASES.get((set_id.value, raw["name"]), []),
    )
    effects = CardEffects(text=text, text_raw=text_raw, accessibility_text=access)
    return Card(static=static, effects=effects, assets=assets)


def _is_variant(c: Card) -> bool:
    """判定变体：showcase 稀有度 或 landscape 方向。"""
    return c.static.rarity == Rarity.SHOWCASE or c.static.orientation == Orientation.LANDSCAPE


def build_database() -> CardDatabase:
    pages = sorted(RAW_DIR.glob("page_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    all_raw: list[dict] = []
    for p in pages:
        d = json.loads(p.read_text(encoding="utf-8"))
        all_raw.extend(d["data"])
    print(f"[ingest] 合并 {len(pages)} 页，共 {len(all_raw)} 张原始卡")

    parsed = [parse_one(r) for r in all_raw]

    # 按 key 分组
    groups: dict[tuple, list[Card]] = defaultdict(list)
    for c in parsed:
        groups[c.static.key].append(c)

    cards: list[Card] = []
    n_variants = 0
    for key, members in groups.items():
        # 主版本优先：非 variant、portrait、rarity 非 showcase
        mains = [m for m in members if not _is_variant(m)]
        main = mains[0] if mains else members[0]
        variants = [m for m in members if m is not main]
        for v in variants:
            v.is_variant = True
        main.variants = [v.static.internal_id for v in variants]
        n_variants += len(variants)
        cards.append(main)
        # 变体也单独入库（保留完整数据，挂主版本 id）
        cards.extend(variants)

    print(f"[ingest] 主版本 {sum(1 for c in cards if not c.is_variant)} 张，变体 {n_variants} 张")
    db = CardDatabase(cards=cards)
    db.build_indexes()
    return db


def write_outputs(db: CardDatabase) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db.save(OUT_DIR / "cards.json")

    # 按系列分片（仅主版本）
    by_set: dict[str, list[Card]] = defaultdict(list)
    for c in db.cards:
        if not c.is_variant:
            by_set[c.static.set_id.value].append(c)
    set_dir = OUT_DIR / "by_set"
    set_dir.mkdir(exist_ok=True)
    for sid, cards in by_set.items():
        (set_dir / f"{sid}.json").write_text(
            json.dumps([c.model_dump(mode="json") for c in cards], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 摘要
    sets = Counter(c.static.set_id.value for c in db.cards if not c.is_variant)
    types = Counter(t.value for c in db.cards if not c.is_variant for t in c.static.types)
    domains = Counter(d.value for c in db.cards if not c.is_variant for d in c.static.domains)
    rarities = Counter(c.static.rarity.value for c in db.cards if not c.is_variant)
    summary = {
        "total_main": sum(1 for c in db.cards if not c.is_variant),
        "total_variants": sum(1 for c in db.cards if c.is_variant),
        "by_set": dict(sets),
        "by_type": dict(types),
        "by_domain": dict(domains),
        "by_rarity": dict(rarities),
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[ingest] 摘要:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    db = build_database()
    write_outputs(db)
    print(f"[ingest] 完成，输出目录: {OUT_DIR}")


if __name__ == "__main__":
    main()
