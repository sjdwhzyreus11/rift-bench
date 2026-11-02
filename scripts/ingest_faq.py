"""解析官方 FAQ 公告页，生成标准化 FAQ JSON。

来源：raw/faq/*.html（playriftbound.com 官方 FAQ 页）。

各页结构差异较大，统一按“文档序遍历 + 问句识别”方式解析:
  - origins: 正文 richText 块仅含绪论/废弃声明/附录；真正的 Q&A 在
    articleRichTextAccordion blade 中（每组 = label 问题 + content.body 答案）。
    页面开头声明文档已废弃 -> origins 全部条目 deprecated=true。
  - spiritforged: 单个 richText 块；问题段落以 "Q:" 开头；
    主题 = 前面最近的标题 (h1/h4) 或短段落 (卡片名等)。
  - unleashed/vendetta: 问题段落被 <strong> 整体包住（整段加粗）；
    主题 = 前面最近的标题 (h1/h2)；vendetta 无标题 -> 主题留空。

答案可能跨多个 <p>/<ul>/<ol>，合并为多段文本；规则符号 [C]/[M] 等原样保留。
表格（卡面修订文本等）不作为答案内容。

产出:
  data/faq/faq.json                — 全集 (JSON 数组)
  data/faq/by_set/{OGN,SFD,UNL,VEN}.json — 按 set 分片

用法: PYTHONPATH=src python scripts/ingest_faq.py
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Doctype, NavigableString, Tag

from riftbench.faq import FaqEntry, FaqSet

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "raw" / "faq"
OUT_DIR = ROOT / "data" / "faq"

# 输入文件 -> 页面 set
PAGE_SET = {
    "origins.html": FaqSet.OGN,
    "spiritforged.html": FaqSet.SFD,
    "unleashed.html": FaqSet.UNL,
    "vendetta.html": FaqSet.VEN,
}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

_SKIP_BLOCK_TAGS = {"table", "img", "script", "style", "meta", "hr", "br"}


def load_page_data(path: Path) -> dict:
    html = path.read_text(encoding="utf-8")
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError(f"未找到 __NEXT_DATA__: {path}")
    return json.loads(m.group(1))


def load_rich_text_bodies(path: Path) -> list[str]:
    data = load_page_data(path)
    blades = data["props"]["pageProps"]["page"].get("blades", [])
    return [
        b["richText"]["body"]
        for b in blades
        if b.get("type") == "articleRichText"
    ]


def load_accordions(path: Path) -> list[dict]:
    data = load_page_data(path)
    blades = data["props"]["pageProps"]["page"].get("blades", [])
    return [b for b in blades if b.get("type") == "articleRichTextAccordion"]


# ---------- 文本抽取 ----------

def _fragments(node) -> list[str]:
    """收集节点下所有非空文本片段（跳过表格/图片/脚本等子树与注释）。"""
    parts: list[str] = []

    def rec(n) -> None:
        for ch in n.children:
            if isinstance(ch, Tag):
                if ch.name in _SKIP_BLOCK_TAGS:
                    continue
                rec(ch)
            elif isinstance(ch, NavigableString) and not isinstance(ch, (Comment, Doctype)):
                s = str(ch).strip()
                if s:
                    parts.append(s)

    rec(node)
    return parts


def block_text(el) -> str:
    """单个嵌套元素展开为空格分隔的文本。"""
    return " ".join(_fragments(el))


def html_to_text(html_str: str) -> str:
    """HTML 字符串按块折叠为多行纯文本。"""
    soup = BeautifulSoup(html_str, "html.parser")
    lines: list[str] = []
    for child in soup.children:
        if isinstance(child, Tag):
            if child.name in _SKIP_BLOCK_TAGS:
                continue
            t = block_text(child)
        elif isinstance(child, NavigableString) and not isinstance(child, (Comment, Doctype)):
            t = str(child).strip()
        else:
            t = ""
        if t:
            lines.append(t)
    return "\n".join(lines)


def strip_q_prefix(q: str) -> str:
    """去掉问题文本开头的 'Q:' 前缀。"""
    q = q.strip()
    for prefix in ("Q:", "Q："):
        if q.startswith(prefix):
            return q[len(prefix):].strip()
    return q


def ends_sentence(text: str) -> bool:
    return text[-1] in ".。:：!！?？"


# ---------- richText 块解析（spiritforged/unleashed/vendetta 风格） ----------

# 容器标签：自身不携带语义文本，仅作结构分组，需递归进入其子块处理
_CONTAINER_TAGS = {"div", "section", "figure", "article", "main", "header", "footer", "center"}
# 块级语义标签（作为独立内容块处理，不递归展开）
_STRUCTURE_PROBE = [
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "blockquote", "table", "div", "section", "figure",
]


def parse_rich_text_walker(
    bodies: list[str],
    set_value: FaqSet,
    deprecated: bool,
) -> list[FaqEntry]:
    """遍历多个 richText 块，识别 Q&A 并对 pending 跨块延续状态。

    Q&A 可能以顶层块（spiritforged/vendetta）或包在 <div> 容器内（unleashed）
    出现，故先递归把文档展开为扁平的块序列 (Phase A)，
    再按块序做状态机 (Phase B)。主题判定用“前瞻”：短段落其后紧接问句则为主题。
    """
    # ---- Phase A: 块序列 ----
    blocks: list[tuple[str, str, Tag]] = []  # (name, text, element)

    def collect(node: Tag) -> None:
        for el in node.children:
            if not isinstance(el, Tag):
                continue
            name = el.name.lower()
            if name in _SKIP_BLOCK_TAGS or name == "table":
                continue  # 图片/表格等整体跳过
            if name in _CONTAINER_TAGS:
                if el.find(_STRUCTURE_PROBE) is not None:
                    collect(el)  # 结构容器：递归展开子块
                else:
                    text = block_text(el)  # 内容容器：整块作一块
                    if text:
                        blocks.append((name, text, el))
                continue
            text = block_text(el)
            if text:
                blocks.append((name, text, el))

    for body in bodies:
        collect(BeautifulSoup(body, "html.parser"))

    # ---- Phase B: 状态机 ----
    entries: list[FaqEntry] = []
    topic = ""
    current_q: str | None = None
    answer_parts: list[str] = []

    def finalize() -> None:
        nonlocal current_q, answer_parts
        if current_q is not None:
            answer = "\n".join(p for p in answer_parts if p).strip()
            entries.append(
                FaqEntry(
                    set=set_value,
                    deprecated=deprecated,
                    topic=topic.strip(),
                    question=current_q,
                    answer=answer,
                )
            )
        current_q = None
        answer_parts = []

    def is_question(name: str, text: str, el: Tag) -> bool:
        if text.startswith("Q:") or text.startswith("Q："):
            return True
        if name == "p":
            strong = el.find("strong")
            strong_text = block_text(strong) if strong else ""
            return bool(
                strong_text
                and strong_text == text
                and "?" in strong_text
                and not strong_text.startswith("Note:")
            )
        return False

    for i, (name, text, el) in enumerate(blocks):
        if not text or text == "▲" or "(revised text)" in text:
            continue
        # 标题 -> 新主题
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            finalize()
            topic = text
            continue
        # 问句
        if is_question(name, text, el):
            finalize()
            current_q = strip_q_prefix(text) if text.startswith(("Q:", "Q：")) else text
            answer_parts = []
            continue
        # 主题候选（短标题式段落）：其后紧接问句则为主题
        is_topic_candidate = name == "p" and len(text) <= 60 and not ends_sentence(text)
        next_is_question = (
            i + 1 < len(blocks) and is_question(blocks[i + 1][0], blocks[i + 1][1], blocks[i + 1][2])
        )
        if is_topic_candidate and next_is_question:
            finalize()  # 先收尾前一条（用旧主题），再切换主题
            topic = text
            continue
        # 答案累积
        if current_q is not None:
            answer_parts.append(text)
        elif is_topic_candidate:
            topic = text  # 孤立主题（其后无问句），保守保留为当前主题
    finalize()
    return entries


# ---------- origins accordion 解析 ----------

def parse_origins_accordions(accordions: list[dict]) -> list[FaqEntry]:
    entries: list[FaqEntry] = []
    for acc in accordions:
        header = acc.get("header", {}) or {}
        subtitle = (header.get("subtitle") or "").strip()
        title = (header.get("title") or "").strip()
        topic = subtitle or title
        for group in acc.get("groups", []):
            label = (group.get("label") or "").strip()
            if not label:
                continue
            content = group.get("content") or {}
            body_html = content.get("body", "") if isinstance(content, dict) else ""
            q = strip_q_prefix(label)
            answer = html_to_text(body_html).strip()
            entries.append(
                FaqEntry(
                    set=FaqSet.OGN,
                    deprecated=True,  # origins FAQ 全文已废弃
                    topic=topic,
                    question=q,
                    answer=answer,
                )
            )
    return entries


def is_deprecated_doc(bodies: list[str]) -> bool:
    """origins FAQ 页在首个 richText 块含废弃声明。"""
    return any("may no longer reflect" in b for b in bodies)


def emit(entries: list[FaqEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([e.model_dump(mode="json") for e in entries],
                   ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    all_entries: list[FaqEntry] = []
    for fname in ("origins.html", "spiritforged.html", "unleashed.html", "vendetta.html"):
        path = RAW_DIR / fname
        set_value = PAGE_SET[fname]

        if set_value == FaqSet.OGN:
            # origins: Q&A 在 accordion blades
            accordions = load_accordions(path)
            entries = parse_origins_accordions(accordions)
            bodies = load_rich_text_bodies(path)
            dep = is_deprecated_doc(bodies)
            if dep and not entries:
                print(f"[faq] {fname} 已标记废弃，但 accordion 中未解析出任何 Q&A!")
        else:
            bodies = load_rich_text_bodies(path)
            dep = is_deprecated_doc(bodies)
            entries = parse_rich_text_walker(bodies, set_value, deprecated=dep)
            if dep:
                print(f"[faq] {fname} 检测到废弃声明，已标记 deprecated")

        all_entries.extend(entries)
        print(f"[faq] {fname:18} -> {len(entries)} 条")

    emit(all_entries, OUT_DIR / "faq.json")
    by_set: dict[FaqSet, list[FaqEntry]] = defaultdict(list)
    for e in all_entries:
        by_set[e.set].append(e)
    for s in FaqSet:
        emit(by_set[s], OUT_DIR / "by_set" / f"{s.value}.json")

    print(f"\n[faq] 总计 {len(all_entries)} 条 -> {OUT_DIR / 'faq.json'}")
    for s in FaqSet:
        print(f"  {s.value}: {len(by_set[s])} 条 (deprecated={sum(1 for e in by_set[s] if e.deprecated)})")

    empty_q = [e.question for e in all_entries if not e.question.strip()]
    empty_a = [e.question for e in all_entries if not e.answer.strip()]
    print(f"\n[faq] 空问题: {len(empty_q)}, 空答案: {len(empty_a)}")
    if empty_q or empty_a:
        print(f"  空问题样本: {empty_q[:10]}")
        print(f"  空答案对应问题样本: {empty_a[:10]}")

    # 记录同主题多问的分布（供人工核对主题切分的合理性）
    topic_counts = defaultdict(int)
    for e in all_entries:
        topic_counts[(e.set.value, e.topic)] += 1
    multi = {k: v for k, v in topic_counts.items() if v > 1}
    print(f"[faq] 同主题多问的组数: {len(multi)} (共 {sum(multi.values())} 条)")


if __name__ == "__main__":
    main()