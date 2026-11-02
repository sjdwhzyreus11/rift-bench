"""解析官方勘误公告页，生成标准化勘误 JSON。

来源：raw/errata/*.html（playriftbound.com 官方勘误页）。

结构（各页略有差异，统一按文档序走 DOM）:
  - 前言叙述在首个卡名之前，跳过。
  - vendetta/spiritforged/unleashed 页含跨 set 小节:
      <h1>Origins Cards</h1> / <h1>Spiritforged Cards</h1> / ...
    按小节把条目归属到对应 set；单 set 页 (origins.html) 全部归属本页 set。
  - 每个条目:
      <h2|h1>卡名</h2|h1>
      <h5|p>[NEW TEXT]</h5|p>
      <p>新文本</p>
      <h4|p>▲</h4|p>
      <h5|p>[OLD TEXT]</h5|p>
      <p>旧文本</p>
      <hr>
  - 规则符号 [C]/[M]/[1]/[A]/[T] 原样保留；语言备注 "Note: ..." 段落剔除。

产出:
  data/errata/errata.json          — 全集 (JSON 数组)
  data/errata/by_set/{OGN,SFD,UNL,VEN}.json — 按 set 分片

用法: PYTHONPATH=src python scripts/ingest_errata.py
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from riftbench.cards import CardDatabase
from riftbench.errata import ErrataEntry, ErrataSet

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "raw" / "errata"
OUT_DIR = ROOT / "data" / "errata"

# 页面小节标题 -> set（vendetta/spiritforged/unleashed 跨 set 勘误）
SECTION_LABELS = {
    "origins cards": ErrataSet.OGN,
    "spiritforged cards": ErrataSet.SFD,
    "unleashed cards": ErrataSet.UNL,
    "vendetta cards": ErrataSet.VEN,
}

# 输入文件 -> 页面默认 set（无小节标题时的归属）
PAGE_DEFAULT_SET = {
    "origins.html": ErrataSet.OGN,
    "spiritforged.html": ErrataSet.SFD,
    "unleashed.html": ErrataSet.UNL,
    "vendetta.html": ErrataSet.VEN,
}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def load_rich_text_bodies(path: Path) -> list[str]:
    """从 Next.js 页面抽取 articleRichText blade 中的 richText.body (HTML 字符串)。"""
    html = path.read_text(encoding="utf-8")
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError(f"未找到 __NEXT_DATA__: {path}")
    data = json.loads(m.group(1))
    blades = data["props"]["pageProps"]["page"].get("blades", [])
    return [
        b["richText"]["body"]
        for b in blades
        if b.get("type") == "articleRichText"
    ]


def parse_errata_body(body_html: str, default_set: ErrataSet) -> list[ErrataEntry]:
    """解析单个 richText body，返回勘误条目列表。"""
    soup = BeautifulSoup(body_html, "html.parser")
    entries: list[ErrataEntry] = []
    section = default_set
    entry: dict | None = None
    part: str | None = None  # 'new' | 'old'

    def finalize() -> None:
        nonlocal entry, part
        if entry is not None:
            new_text = "\n".join(x for x in entry["new"] if x).strip()
            old_text = "\n".join(x for x in entry["old"] if x).strip()
            entries.append(
                ErrataEntry(
                    set=entry["set"],
                    card_name=entry["name"],
                    new_text=new_text,
                    old_text=old_text,
                )
            )
        entry = None
        part = None

    for el in soup.children:
        if not isinstance(el, Tag):
            continue
        name = el.name.lower()
        if name in ("img", "hr", "meta", "script", "br"):
            continue
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if text == "▲":
            continue  # ▲ 新旧文本分隔符
        if text.startswith("Note:") or text.startswith("Note :"):
            continue  # "Note: Text only differs..." 语言备注，非卡面文本
        if name == "h1":
            key = text.lower()
            if key in SECTION_LABELS:
                finalize()
                section = SECTION_LABELS[key]
                continue
            # spiritforged 页用 <h1> 作卡名；空 <h1> 装饰已在上方 text 空直接跳过
            finalize()
            entry = {"set": section, "name": text, "new": [], "old": []}
            part = None
            continue
        if name == "h2":
            finalize()
            entry = {"set": section, "name": text, "new": [], "old": []}
            part = None
            continue
        # [NEW TEXT] / [OLD TEXT] 标记
        if text in ("[NEW TEXT]", "[OLD TEXT]"):
            part = "new" if text == "[NEW TEXT]" else "old"
            continue
        # 卡面正文
        if entry is not None and part is not None and name in (
            "p", "div", "ul", "ol", "li", "blockquote",
        ):
            entry[part].append(text)
    finalize()
    return entries


def build_pipeline() -> list[ErrataEntry]:
    entries: list[ErrataEntry] = []
    for fname in (
        "origins.html",
        "spiritforged.html",
        "unleashed.html",
        "vendetta.html",
    ):
        path = RAW_DIR / fname
        default_set = PAGE_DEFAULT_SET[fname]
        total = 0
        for body in load_rich_text_bodies(path):
            parsed = parse_errata_body(body, default_set)
            entries.extend(parsed)
            total += len(parsed)
        print(f"[errata] {fname:18} -> {total} 条")
    return entries


def write_json_list(entries: list[ErrataEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [e.model_dump(mode="json") for e in entries],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def normalize_name(n: str) -> str:
    """归一化卡名用于模糊匹配（统一撇号、去标点空格）。"""
    return re.sub(r"[^a-z0-9]", "", n.lower().replace("’", "'"))


def report_unmatched(
    entries: list[ErrataEntry], db: CardDatabase
) -> list[tuple[str, list[str]]]:
    """把勘误卡名与卡牌库匹配，返回 (卡名, 建议候选) 列表（仅未匹配项）。"""
    known_names = {c.static.name for c in db.cards}
    norm_known = {normalize_name(n): n for n in known_names}
    known_by_text = {}
    for c in db.cards:
        txt = c.effects.text.strip()
        if txt:
            known_by_text.setdefault(txt, []).append(c.static.name)

    unmatched: list[tuple[str, list[str]]] = []
    for e in entries:
        norm = normalize_name(e.card_name)
        if norm in norm_known:
            continue
        if e.card_name.lower() in {n.lower() for n in known_names}:
            continue
        candidates: list[str] = []
        # 1) 文本完全一致: 勘误新文本 == 卡库卡面文本
        for t in (e.new_text, e.old_text):
            hit = known_by_text.get(t.strip())
            if hit:
                candidates.extend(hit)
        # 2) 名称归一化后前缀/包含匹配
        for nk, nv in norm_known.items():
            if norm and (nk.startswith(norm) or norm.startswith(nk)) and len(norm) > 3:
                candidates.append(nv)
        unmatched.append((e.card_name, sorted(set(candidates))))
    return unmatched


def main() -> None:
    entries = build_pipeline()
    collection = ErrataEntry
    write_json_list(entries, OUT_DIR / "errata.json")

    # 按 set 分片
    by_set: dict[ErrataSet, list[ErrataEntry]] = defaultdict(list)
    for e in entries:
        by_set[e.set].append(e)
    for s in ErrataSet:
        write_json_list(by_set[s], OUT_DIR / "by_set" / f"{s.value}.json")

    # 统计
    print(f"\n[errata] 总计 {len(entries)} 条 -> {OUT_DIR / 'errata.json'}")
    for s in ErrataSet:
        print(f"  {s.value}: {len(by_set[s])} 条")

    dups = [k for k, v in Counter(e.card_name for e in entries).items() if v > 1]
    if dups:
        print(f"\n[errata] 同名卡出现多次（供人工核对）: {sorted(dups)}")

    # 与卡牌库核对
    db = CardDatabase.load(ROOT / "data" / "cards" / "cards.json")
    unmatched = report_unmatched(entries, db)
    if unmatched:
        print("[errata] 卡库中未按卡名匹配到的卡（供人工核对）:")
        for name, cands in unmatched:
            hint = f"  -> 疑似卡库中的: {cands}" if cands else "  -> 无候选，需人工确认"
            print(f"  - {name}{hint}")
    else:
        print("[errata] 全部勘误卡名均在卡牌库中匹配到")

    # 规则符号保留校验
    token_re = re.compile(r"\[(?:C|M|A|T|E|\d+)\]")
    non_token = [
        e.card_name for e in entries
        if not (token_re.search(e.new_text) or token_re.search(e.old_text))
    ]
    if non_token:
        print(
            f"[errata] {len(non_token)} 条勘误文本不含规则符号（正常，如纯文字勘误）: "
            f"{non_token[:20]}"
        )


if __name__ == "__main__":
    main()