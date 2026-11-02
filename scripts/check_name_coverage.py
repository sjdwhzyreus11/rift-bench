"""校验勘误/FAQ 卡名能否匹配到卡牌数据库（name + aliases + 引号归一化）。

勘误页和 FAQ 页使用的卡名有时与卡牌库存在差异:
  - 引号字符: 卡库用直引号 ' (U+0027)，勘误/FAQ 用弯引号 ’ (U+2019)
  - 全名/简称: 卡库 "Deceiver"，勘误 "Leblanc, Deceiver" (经 aliases 映射)
  - 卡名分隔: "Dark Child - Starter" (卡库) vs "Dark Child, Starter" (勘误)
  - 归属差异: 个别卡被勘误页归到某 set，但卡库同名卡在另一 set

本脚本输出匹配率与未匹配清单，供人工核对。
不修改数据，只做诊断。

用法: PYTHONPATH=src python scripts/check_name_coverage.py
"""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.cards import CardDatabase

ROOT = Path(__file__).resolve().parents[1]


def normalize(s: str) -> str:
    """归一化卡名用于匹配: 去空格大小写、统一引号、NFKC。"""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'")  # 弯引号 -> 直引号
    s = s.replace("“", '"').replace("”", '"')
    s = s.lower().strip()
    # 统一分隔符: 逗号/横线/空格的混合差异，用容错比较
    return s


def normalize_loose(s: str) -> str:
    """更宽松的归一化: 把逗号/横线/下划线都当作分隔符归一为空格。"""
    s = normalize(s)
    for ch in ",-_":
        s = s.replace(ch, " ")
    return " ".join(s.split())


def build_index(db: CardDatabase):
    """返回 (strict_idx, loose_idx)，键为归一化名，值为 Card 列表。"""
    strict: dict[str, list] = {}
    loose: dict[str, list] = {}
    for c in db.cards:
        for n in [c.static.name, *c.static.aliases]:
            strict.setdefault(normalize(n), []).append(c)
            loose.setdefault(normalize_loose(n), []).append(c)
    return strict, loose


def check(errata_path: Path, db: CardDatabase) -> None:
    strict, loose = build_index(db)

    def check_file(path: Path, name_field: str, label: str) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data if isinstance(data, list) else data.get("entries", [])
        strict_hits = loose_hits = 0
        loose_miss = []
        for e in entries:
            nm = e[name_field]
            if normalize(nm) in strict:
                strict_hits += 1
            else:
                if normalize_loose(nm) in loose:
                    loose_hits += 1
                else:
                    loose_miss.append((e.get("set"), nm))
        print(f"\n=== {label} ({len(entries)} 条) ===")
        print(f"  精确匹配 (name+aliases+引号归一): {strict_hits}/{len(entries)}")
        print(f"  宽松匹配 (再兼容逗号/横线差异): +{loose_hits}")
        print(f"  未匹配: {len(loose_miss)}")
        for s, nm in loose_miss:
            safe = nm.encode("ascii", "replace").decode()
            print(f"    MISS set={s} name={safe!r}")

    check_file(errata_path, "card_name", "勘误 errata (按 card_name 匹配卡库)")


def main() -> None:
    db = CardDatabase.load(ROOT / "data" / "cards" / "cards.json")
    errata = ROOT / "data" / "errata" / "errata.json"
    if not errata.exists():
        print("勘误产物不存在，先运行 ingest_errata.py")
        return
    check(errata, db)


if __name__ == "__main__":
    main()
