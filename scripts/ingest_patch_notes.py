"""提取核心规则补丁说明页(patch notes)为纯文本存档。

补丁页是叙述性文章（非结构化规则），记录每次核心规则更新的变更说明与意图。
价值: QA 智能体的规则解释语料 + 引擎开发时理解规则演变。
非规则本身（规则本身在 rules/en/core_rules.raw.txt，已是最新 2026-07-16 版）。

用法: PYTHONPATH=src python scripts/ingest_patch_notes.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "raw" / "patches"
OUT_DIR = ROOT / "data" / "rules" / "patch_notes"

# 文件名 -> (set 归属, 标题)
PATCHES = {
    "riftbound-core-rules-patch-notes.html": ("ORIGINS", "Core Rules Patch Notes (Origins)"),
    "riftbound-core-rules-spiritforged-patch-notes.html": ("SPIRITFORGED", "Core Rules Patch Notes (Spiritforged)"),
    "riftbound-core-rules-unleashed-patch-notes.html": ("UNLEASHED", "Core Rules Patch Notes (Unleashed)"),
    "core-rules-vendetta-patch-notes.html": ("VENDETTA", "Core Rules Patch Notes (Vendetta)"),
}


def _strip_html(body: str) -> str:
    body = body.replace("</p>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    body = body.replace("</li>", "\n").replace("</h2>", "\n").replace("</h3>", "\n")
    body = re.sub(r"<[^>]+>", "", body)
    import html as H
    body = H.unescape(body).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in body.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def extract_one(path: Path) -> dict:
    html = path.read_text(encoding="utf-8")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    d = json.loads(m.group(1))
    page = d["props"]["pageProps"]["page"]
    title = page.get("title", "")
    blocks = []
    for b in page.get("blades", []):
        if b.get("type") == "articleRichText":
            body = b.get("richText", {}).get("body", "")
            blocks.append(_strip_html(body))
    return {"title": title, "blocks": blocks, "text": "\n\n".join(blocks)}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for fname, (set_tag, label) in PATCHES.items():
        p = SRC_DIR / fname
        if not p.exists():
            print(f"[patch] 缺失: {fname}")
            continue
        rec = extract_one(p)
        rec["set"] = set_tag
        rec["source_file"] = fname
        out = OUT_DIR / f"{set_tag.lower()}.json"
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        # 同时存纯文本
        (OUT_DIR / f"{set_tag.lower()}.txt").write_text(
            f"# {rec['title']}\n\n{rec['text']}", encoding="utf-8"
        )
        index.append({"set": set_tag, "label": label, "title": rec["title"],
                       "chars": len(rec["text"]), "file": f"patch_notes/{set_tag.lower()}.json"})
        print(f"[patch] {set_tag}: {rec['title']!r} ({len(rec['text'])} chars)")
    (OUT_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[patch] 索引 -> {OUT_DIR / 'index.json'}")


if __name__ == "__main__":
    main()
