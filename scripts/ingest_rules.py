"""从核心规则 PDF 提取的纯文本，解析为 {规则编号: 正文} 索引。

输入文件 rules/en/core_rules.raw.txt 由 pdftotext -raw 从英文核心规则 PDF
(raw/en_pdf_B.pdf) 提取，规则编号与其正文**交错排列**:

    001. Golden Rule
    002. Card text supersedes rules text. Whenever a card fundamentally contradicts
    what is true.
    053.1. * Units and legends say "I," "me," etc.
    ...

规律:
  - 每行若以规则编号开头（如 ``465.2.c.6. ``），则表示一条新规则；同一行编号之后
    的文本是该规则正文的首段。
  - 后续"不以编号开头"的非空行是该规则正文的续行（PDF 折行），按顺序并入正文。
  - 规则编号格式: 点分层级，如 103.2.a / 465.2.c.6；顶层之下还可接数字/字母成分。
  - 章节标题（如 "Game Concepts"、"Combat"、"The Stack"）本身就是其顶层规则的正文
    （如 "100. Game Concepts"），不会被当作文本吞并；跨段互相引用（"See rule 197.
    Locations ..."）因不在行首而不会被误判为新规则。

兼容旧版提取格式（编号全部集中到"编号索引行"、正文随后集中出现）作为 fallback:
  - 编号索引行: 一行内含多个规则编号，每个以 `.` 结尾，如 "465.2.c.6. 465.2.c.7."
  - 正文段落: 紧随编号索引行之后的若干行，直到下一个编号索引行。
  - 以"相邻编号索引行 + 其后的正文块"为一组，组内按出现顺序配对。

产出:
  data/rules/core_rules.json  — [{rule, text}, ...]
  data/rules/core_rules_index.json — {rule: text}
  data/rules/chapters.json — 顶层编号 -> 章节标题

用法: python scripts/ingest_rules.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "rules" / "en" / "core_rules.raw.txt"
OUT_DIR = ROOT / "data" / "rules"

# 规则编号 token: 顶层必须是三位数字 (000-999)，其后可接若干个 `.数字` / `.字母` /
# `.字母数字` 成分，末尾统一带句点。例如 103 / 103.1 / 103.2.a / 465.2.c.6。
# 顶层限制为三位数字可避免把正文列表项 "1." "2."、或年份 "2000." 误当规则编号。
_RULE_TOKEN = r"\d{3}(?:\.(?:\d{1,3}|[a-z]\d*))*\."

# 行首带规则编号的完整正则: 允许行首空白与分页符 (\f)。
# 编译时启用 MULTILINE，使 ^/$ 在逐行 (.match) 与全文 (.search) 下语义一致。
_RULE_LINE = re.compile(r"^\s*\f?(" + _RULE_TOKEN + r")\s+(.*)$", re.MULTILINE)
_RULE_LINE_EMPTY = re.compile(r"^\s*\f?(" + _RULE_TOKEN + r")\s*$", re.MULTILINE)
# 在任意文本中抓取规则编号（用于索引行 / 交叉引用识别）。
_RULE_NUM = re.compile(r"\b" + _RULE_TOKEN)


def _is_index_line(line: str) -> bool:
    """旧格式的"编号索引行": 该行去掉空白后主要由规则编号组成。"""
    s = line.strip().lstrip("\f")
    if not s:
        return False
    nums = list(_RULE_NUM.finditer(s))
    if not nums:
        return False
    covered = sum(m.end() - m.start() for m in nums)
    non_ws = len(s.replace(" ", ""))
    return covered >= 0.6 * non_ws


def _is_heading_body(body: str) -> bool:
    """判断顶层规则正文是否像"章节/小节标题"（用于 chapters.json）。

    标题特征: 短 (1-6 词, <=60 字符)、首字母大写、不含句子标点
    （. : ; ! ?）。因此 "Game Concepts" 入选，而
    "Card text supersedes rules text. Whenever ..." 这类句子被排除。
    """
    s = body.strip()
    if not s or len(s) > 60:
        return False
    if any(ch in s for ch in ".:;!?"):
        return False
    if not s[0].isupper():
        return False
    wc = len(s.split())
    return 1 <= wc <= 6


def _parse_interleaved(text: str) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """主格式: 编号与正文交错（pdftotext -raw）。"""
    rules_list: list[dict] = []
    cur_rule: dict | None = None

    for ln in text.splitlines():
        m = _RULE_LINE.match(ln)
        if m:
            rule = m.group(1).rstrip(".")
            body = m.group(2).strip()
            cur_rule = {"rule": rule, "text": body}
            rules_list.append(cur_rule)
            continue
        me = _RULE_LINE_EMPTY.match(ln)
        if me:
            # 编号行但该行无正文（极罕见）; 若展开旧文件可能遇到。
            cur_rule = {"rule": me.group(1).rstrip("."), "text": ""}
            rules_list.append(cur_rule)
            continue
        s = ln.strip().lstrip("\f").strip()
        if s and cur_rule is not None:
            # 续行: 并入当前规则正文，与上一段以空格相接。
            cur_rule["text"] = (cur_rule["text"] + " " + s).strip()
        # 前导标题行（"Riftbound Core Rules" / "Last Updated: ..."）没有编号，
        # 在 cur_rule 为 None 时被忽略。

    index_dict = {r["rule"]: r["text"] for r in rules_list}
    chapter_map = _extract_chapters([r for r in rules_list if "." not in r["rule"]])
    return rules_list, index_dict, chapter_map


def _parse_grouped(text: str) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """旧格式 fallback: 编号索引行 + 随后集中的正文块。"""
    lines = text.splitlines()

    # 把文本流切成"组": 组头是连续出现的编号索引行（声明若干编号），
    # 组体是其后直到下一个编号索引行之间的正文行。
    blocks: list[tuple[list[str], list[str]]] = []  # (numbers, body_lines)
    cur_nums: list[str] = []
    cur_bodies: list[str] = []
    for ln in lines:
        if _is_index_line(ln):
            if cur_bodies:
                blocks.append((cur_nums, cur_bodies))
                cur_nums, cur_bodies = [], []
            cur_nums.extend(m.group(0).rstrip(".") for m in _RULE_NUM.finditer(ln))
        else:
            s = ln.strip().lstrip("\f").strip()
            if s:
                cur_bodies.append(s)
    if cur_nums or cur_bodies:
        blocks.append((cur_nums, cur_bodies))

    rules_list: list[dict] = []
    seen: set[str] = set()
    for nums, bodies in blocks:
        for i, num in enumerate(nums):
            body = bodies[i] if i < len(bodies) else ""
            if num in seen:
                continue
            seen.add(num)
            rules_list.append({"rule": num, "text": body})

    index_dict = {r["rule"]: r["text"] for r in rules_list}
    chapter_map = _extract_chapters([r for r in rules_list if "." not in r["rule"]])
    return rules_list, index_dict, chapter_map


def _extract_chapters(top_rules: list[dict]) -> dict[str, str]:
    """顶层规则里正文是章节/小节标题的, 登记为 顶层编号 -> 标题。"""
    chapter_map: dict[str, str] = {}
    for r in top_rules:
        if _is_heading_body(r["text"]):
            chapter_map[r["rule"]] = r["text"]
    return chapter_map


def parse_core_rules(text: str) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """返回 (rules_list, index_dict, chapter_map)。自动识别输入格式。"""
    # 格式判定: 统计"真交错行"（行首一个编号 + 同行正文）的数量。
    # 新格式几乎所有编号行都带同行正文；旧格式的编号索引行会被误判为一条
    # "053. 053.1. 053.2. ..."，其"正文"部分仍以编号开头，不算真交错行。
    interleaved = 0
    for ln in text.splitlines():
        m = _RULE_LINE.match(ln)
        if m and not _RULE_NUM.match(m.group(2)):
            interleaved += 1
    if interleaved >= 100:  # 新格式约 2380 行，旧格式仅十余行章节头
        return _parse_interleaved(text)
    return _parse_grouped(text)


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    rules_list, index_dict, chapter_map = parse_core_rules(text)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "core_rules.json").write_text(
        json.dumps(rules_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "core_rules_index.json").write_text(
        json.dumps(index_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "chapters.json").write_text(
        json.dumps(chapter_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    non_empty = sum(1 for r in rules_list if r["text"].strip())
    print(f"[rules] 解析 {len(rules_list)} 条规则编号")
    print(f"[rules] 非空正文: {non_empty} / 空正文: {len(rules_list) - non_empty}")
    print(f"[rules] 章节映射 {len(chapter_map)} 项:")
    for k, v in sorted(chapter_map.items(), key=lambda x: int(x[0])):
        print(f"  {k}. {v}")
    # 抽样关键规则验证
    print("\n[关键规则验证]")
    for r in ["053.1", "053.3", "054.2", "103.2.a", "307", "465.2.c.6", "805", "813", "815"]:
        if r in index_dict:
            print(f"\n[{r}] {index_dict[r][:200]}")
        else:
            print(f"\n[{r}] <未找到>")
    # 补充: 文档中"黄金法则"相关短语的实际所在编号 (供核对)
    print("\n[黄金法则/战斗伤害分配短语的实际编号位置]")
    for r in ["002", "054", "055", "465.2.c.5"]:
        if r in index_dict:
            print(f"[{r}] {index_dict[r][:120]}")


if __name__ == "__main__":
    main()