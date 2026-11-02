"""卡面文本解析器 — 把 CardEffects.text 解析为能力 AST。

解析策略（务实分层，覆盖 L1+L2 高频模式）:
  1. 文本按段切分（\n 及括号解释剥离）。
  2. 每段判定能力类型（前缀分类）:
     - 'When/Whenever/At|As|After ...' → TRIGGERED
     - '[T]:' 或 '费用表达式: ...' → ACTIVATED
     - 其余 → PASSIVE / INSTRUCTION
  3. 从能力段提取指令（动词拆分）+ 目标过滤器 + 修饰符(you may/if/this turn)。
  4. 失败回退：解析不了的能力记为 unparsed（卡当白板），记录 warning。

覆盖率目标：L1+L2 约 94% 卡牌。由 scripts/effects_coverage.py 量化驱动迭代。
"""
from __future__ import annotations

import re
from typing import Optional

from riftbench.engine.effects.model import (
    Ability,
    AbilityKind,
    Condition,
    Instruction,
    InstructionOp,
    ParsedCardEffects,
    SubjectKind,
    TargetFilter,
    TargetRelation,
    Trigger,
    TriggerEventType,
)

# ---------- 正则 ----------

# 段内的 [关键字] 与括号解释：先提取关键字，剥掉括号
_KEYWORD_RE = re.compile(r"\[([A-Za-z0-9 ]+?)\]")
# 依赖关键字分隔符 [>]
_GT_RE = re.compile(r"\[>\]")

# 触发前缀
_TRIGGER_RE = re.compile(
    r"^(When|Whenever|At|As|After|If)\s+"
    r"(?P<body>.*?):?\s*(?=\.|$)", re.IGNORECASE
)

# 主动技能: [T]: 或 [费用]: 或 Discard...: 后接效果
_ACTIVATED_RE = re.compile(
    r"""^(?P<cost>
        (?:\[[^\]]+\]\s*)+   # [T] [1][C] 等
        |
        (?:Discard\s+\w+|Pay\s+[^:]+)
    )\s*:\s*(?P<effect>.+)$""", re.IGNORECASE | re.VERBOSE
)

# 指令拆分：以动词/命名动词短语为界
_INSTR_SPLIT_RE = re.compile(
    r"(?=^|\s|\.\s)(?:"
    r"You may |If you do, |Then |and |,? then |then "  # 连接/分支
    r")", re.IGNORECASE
)

# 目标过滤器
_TARGET_RE = re.compile(
    r"(a|an|any|each|your|friendly|enemy|up to|all)\s+"
    r"(friendly\s+|enemy\s+)?"
    r"(unit|units|gear|gears|spell|spells|rune|runes|card|cards|player|battlefield|hand)",
    re.IGNORECASE
)

# 修饰符
_MAY_RE = re.compile(r"\byou may\b", re.IGNORECASE)
_IF_RE = re.compile(r"\bif (you do|you paid|.*)\b", re.IGNORECASE)
_THIS_TURN_RE = re.compile(r"\bthis turn\b", re.IGNORECASE)
_TO_MIN_RE = re.compile(r"\bto a minimum of (\d+)\b", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(\d+)", re.IGNORECASE)

# 指令动词 → op + 目标提示 映射
_VERB_OPS: list[tuple[re.Pattern, InstructionOp]] = [
    (re.compile(r"\bplay\s+(?:a|an|up to)\s+", re.I), InstructionOp.PLAY),   # play a ... (非 play a card from)
    (re.compile(r"\bdeal\b", re.I), InstructionOp.DEAL),
    (re.compile(r"\bkill\b", re.I), InstructionOp.KILL),
    (re.compile(r"\bdestroy\b", re.I), InstructionOp.KILL),
    (re.compile(r"\bready\b", re.I), InstructionOp.READY),
    (re.compile(r"\bexhaust\b", re.I), InstructionOp.EXHAUST),
    (re.compile(r"\bmove\b", re.I), InstructionOp.MOVE),
    (re.compile(r"\brecall\b", re.I), InstructionOp.RECALL),
    (re.compile(r"\breturn\b", re.I), InstructionOp.RETURN),
    (re.compile(r"\bscore\b|\bgain\s+1 point\b|\bscore 1\b", re.I), InstructionOp.SCORE),
    (re.compile(r"\badd\b|\[Add\]", re.I), InstructionOp.GAIN),
    (re.compile(r"\bgive\b", re.I), InstructionOp.GIVE_MIGHT),
    (re.compile(r"\bbuff\b", re.I), InstructionOp.BUFF),
    (re.compile(r"\bdraw\b", re.I), InstructionOp.DRAW),
    (re.compile(r"\bbanish\b", re.I), InstructionOp.BANISH),
    (re.compile(r"\brecycle\b", re.I), InstructionOp.RECYCLE),
    (re.compile(r"\bdiscard\b", re.I), InstructionOp.DISCARD),
    (re.compile(r"\block at\b", re.I), InstructionOp.LOOK_AT),
    (re.compile(r"\breveal\b", re.I), InstructionOp.REVEAL),
    (re.compile(r"\bstun\b", re.I), InstructionOp.STUN),
    (re.compile(r"\bcounter\b", re.I), InstructionOp.COUNTER),
    (re.compile(r"\bheal\b", re.I), InstructionOp.HEAL),
    (re.compile(r"\bsummon\b|\bChannel\b|\bplay a .* token\b", re.I), InstructionOp.PLAY),
]

# 目标关系与种类词
_RELATION_MAP = {
    "a": TargetRelation.A, "an": TargetRelation.AN, "any": TargetRelation.ANY,
    "each": TargetRelation.EACH, "your": TargetRelation.YOUR,
    "friendly": TargetRelation.FRIENDLY, "enemy": TargetRelation.ENEMY,
    "up": TargetRelation.ANY,
}
_KIND_MAP = {
    "unit": "unit", "units": "unit", "gear": "gear", "gears": "gear",
    "spell": "spell", "spells": "spell", "rune": "rune", "runes": "rune",
    "card": "card", "cards": "card", "player": "player", "battlefield": "battlefield",
}

# 触发事件词
_EVENT_MAP = {
    "play": TriggerEventType.PLAY,
    "enter": TriggerEventType.ENTER,
    "conquer": TriggerEventType.CONQUER,
    "hold": TriggerEventType.HOLD,
    "attack": TriggerEventType.ATTACK,
    "defend": TriggerEventType.DEFEND,
    "die": TriggerEventType.DIE,
    "killed": TriggerEventType.DIE,
    "death": TriggerEventType.DIE,
    "draw": TriggerEventType.DRAW,
}


def _split_segments(text: str) -> list[str]:
    """把卡面文本切成能力段。保留括号解释（供关键字），按 \n 切大段。"""
    segs = [s.strip() for s in re.split(r"\n+", text) if s.strip()]
    return segs


def _extract_keywords(segment: str) -> list[str]:
    """提取 [关键字]，剥掉括号解释与 [>]。"""
    kws = []
    for m in _KEYWORD_RE.finditer(segment):
        k = m.group(1).strip()
        if k in ("M", "T", "A", "C", "E") or re.fullmatch(r"\d+", k):
            continue  # 资源符号/数字
        kws.append(k)
    # 特殊: [1][C] 形式里的数字段已排除；[Add] 保留作为资源关键字
    return [k for k in kws if k not in ("Add", "Predict")] if kws else []


def _strip_reminder(segment: str) -> str:
    """去掉 (Reminder) 括号解释。"""
    return re.sub(r"\([^)]*\)", "", segment).strip()


def _parse_trigger_prefix(segment: str) -> tuple[Optional[Trigger], str]:
    """识别触发前缀，返回 (Trigger|None, 剩余文本)。"""
    m = re.match(r"^\s*(When|Whenever|At|As|After)\s+(I|you|a|an|any|each|friendly|enemy)\b(.*)$",
                 segment, re.IGNORECASE)
    if not m:
        return None, segment
    intro, subj, rest = m.group(1), m.group(2).lower(), m.group(3)
    # 确定主体
    # 特例: "you play me/this" —— me/this 是卡自己 → subject=self（尽管主语是 you）
    if subj == "you" and re.search(r"\bplay (me|this)\b", rest, re.I):
        subject = SubjectKind.SELF
    elif subj == "i":
        subject = SubjectKind.SELF
    elif subj == "you":
        subject = SubjectKind.CONTROLLER
    elif subj in ("a", "an", "any", "each"):
        subject = SubjectKind.ANY_UNIT if _KIND_MAP.get(_key_of_subject(rest), None) == "unit" else SubjectKind.ANY
    else:
        subject = SubjectKind.FRIENDLY_UNIT if subj == "friendly" else SubjectKind.ENEMY_UNIT

    # 事件词
    event = None
    for word in ("conquer", "hold", "attack", "defend", "die", "kill", "draw", "play", "enter"):
        if re.search(r"\b" + word + r"\b", rest, re.I):
            event = _EVENT_MAP.get(word)
            break
    if event is None:
        # 其他: 回合开始时/结束时
        if re.search(r"\bstart of\b|\bbeginning of\b", rest, re.I):
            event = TriggerEventType.START_OF_PHASE
        else:
            event = TriggerEventType.OTHER
    trigger = Trigger(event=event, subject=subject)
    return trigger, rest


def _key_of_subject(rest: str) -> str:
    m = _TARGET_RE.search(rest)
    return m.group(3).lower() if m else ""


def _parse_target(segment: str) -> tuple[Optional[TargetFilter], str]:
    """从文本解析目标过滤器。返回 (TargetFilter|None, 剩余文本)。"""
    m = _TARGET_RE.search(segment)
    if not m:
        return None, segment
    relation = _RELATION_MAP.get(m.group(1).lower(), TargetRelation.A)
    kind = _KIND_MAP.get(m.group(3).lower(), None)
    plus = " ".join(g for g in m.groups() if g and g.lower() not in _KIND_MAP)
    # location
    loc = None
    if re.search(r"\bhere\b", segment, re.I): loc = "here"
    elif re.search(r"\bin your trash\b", segment, re.I): loc = "trash"
    elif re.search(r"\bin your hand\b", segment, re.I): loc = "hand"
    elif re.search(r"\bin your Main Deck\b|\bon top of your Main Deck\b", segment, re.I): loc = "main_deck"
    # up to N
    up_to = None
    mu = re.search(r"\bup to (\d+)\b", segment, re.I)
    if mu: up_to = int(mu.group(1))
    return TargetFilter(relation=relation, card_kind=kind, location=loc, up_to=up_to), segment


def _parse_instructions(text: str) -> list[Instruction]:
    """从能力效果文本提取指令（按动词拆分）。"""
    instructions: list[Instruction] = []
    # 去掉提示/权限词，保留效果主体
    body = _strip_reminder(text)
    # 按 "you may ... if ... , then" 拆成子句（简化：一次拆一个主指令 + 修饰）
    main_may = bool(_MAY_RE.search(body))
    optional = main_may

    # 找第一个指令动词
    for pat, op in _VERB_OPS:
        m = pat.search(body)
        if m:
            start = m.start()
            clause = body[start:]
            # 截到下一个句点/分号
            end = re.search(r"\.\s|;\s", clause)
            if end:
                clause = clause[: end.start()]
            target, _rem = _parse_target(clause)
            amount = _amount_of(clause, op)
            quals = _quals_of(clause)
            # 修正: play a unit -> PLAY；draw 1 -> DRAW
            instr = Instruction(
                op=op, target=target or TargetFilter(),
                amount=amount, optional=optional, quals=quals,
                raw=clause.strip()[:120],
            )
            instructions.append(instr)
            break  # P2.1 简化：只取主指令
    return instructions


def _amount_of(clause: str, op: InstructionOp) -> Optional[int]:
    """从子句提取数量（伤害/张数/战力值）。"""
    if op in (InstructionOp.DEAL, InstructionOp.DRAW, InstructionOp.GIVE_MIGHT,
              InstructionOp.GAIN, InstructionOp.PLAY):
        # 找数字（括号里可能也有）
        nums = [int(g) for g in _AMOUNT_RE.findall(clause) if g.isdigit()]
        if nums:
            # deal N damage / draw N / give +N
            return nums[0]
    return None


def _quals_of(clause: str) -> dict:
    q = {}
    if _THIS_TURN_RE.search(clause): q["this_turn"] = True
    tm = _TO_MIN_RE.search(clause)
    if tm:
        q["to_minimum"] = int(tm.group(1))
    return q


def parse_card_effects(text: str, card_internal_id: str = "") -> ParsedCardEffects:
    """主入口：卡面文本 → 能力 AST。解析失败回退为不可解析（不抛异常）。"""
    result = ParsedCardEffects(card_internal_id=card_internal_id)
    if not text or text.strip() == "[NO TEXT]":
        result.parseable = False
        return result

    segments = _split_segments(text)
    for seg in segments:
        kws = _extract_keywords(seg)
        # P2.3: 依赖关键字条件门（726-727）：段首 [Empowered][>] / [Level N][>] / [Legion][>]
        cond = _parse_condition_keyword(seg)
        # 触发?
        trig, rest = _parse_trigger_prefix(seg)
        if trig is not None:
            instrs = _parse_instructions(rest)
            ab = Ability(kind=AbilityKind.TRIGGERED, source=seg[:300], trigger=trig,
                         instructions=instrs, keywords=kws, condition_keyword=cond,
                         optional=bool(_MAY_RE.search(seg)))
            result.abilities.append(ab)
            result.keywords.extend(kws)
            continue
        # 主动?
        mact = _ACTIVATED_RE.match(seg)
        if mact:
            cost = mact.group("cost").strip()
            effect = mact.group("effect").strip()
            instrs = _parse_instructions(effect)
            ab = Ability(kind=AbilityKind.ACTIVATED, source=seg[:300], cost=cost,
                         instructions=instrs, keywords=kws, condition_keyword=cond,
                         optional=bool(_MAY_RE.search(effect)))
            result.abilities.append(ab)
            result.keywords.extend(kws)
            continue
        # 被动/指令
        instrs = _parse_instructions(seg)
        kind = AbilityKind.INSTRUCTION if instrs else AbilityKind.PASSIVE
        ab = Ability(kind=kind, source=seg[:300], instructions=instrs, keywords=kws,
                     condition_keyword=cond, optional=bool(_MAY_RE.search(seg)))
        result.abilities.append(ab)
        result.keywords.extend(kws)

    result.keywords = list(dict.fromkeys(result.keywords))
    if not result.abilities:
        result.parseable = False
    return result


# 依赖关键字条件门正则：段首 [KW][>] 或 [Level N][>] 或 [Legion]
_COND_RE = re.compile(
    r"^\s*(?:\[Empowered\]|\[Level (\d+)\]|\[Legion\])(?:\[&gt;\]|\[>>\]|\[&gt;&gt;\])*",
    re.IGNORECASE,
)


def _parse_condition_keyword(segment: str) -> Optional[str]:
    """识别依赖关键字条件门，返回 'Empowered'/'Level N'/'Legion' 或 None。"""
    m = _COND_RE.match(segment)
    if not m:
        return None
    if m.group(1):
        return f"Level {m.group(1)}"
    if segment.lstrip().startswith("[Empowered]"):
        return "Empowered"
    if segment.lstrip().startswith("[Legion]"):
        return "Legion"
    return None