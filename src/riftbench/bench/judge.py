"""打分器（bench/judge.py）— 对比模型输出与引擎正答。

每任务打分:
  T2: 二值（legal 一致）
  T3: precision/recall/F1（行动集）
  T5/T6: 字段匹配（引擎正答字段 vs 模型输出）
"""
from __future__ import annotations


def _norm_action(a) -> str:
    """行动规范化（dict → 可比较字符串）。"""
    if not isinstance(a, dict):
        return str(a)
    parts = [str(a.get("type"))]
    for k in ("hand_runtime_id", "target_location_id", "unit_runtime_id",
              "to_location_id", "rune_runtime_id", "obj_id", "ability_idx"):
        v = a.get(k)
        if v is not None:
            parts.append(f"{k}={v}")
    return "|".join(parts)


def judge(task: str, engine_answer: dict, model_answer: dict) -> dict:
    """返回 {score: float, detail: dict}。"""
    if task == "T2":
        eng = bool(engine_answer.get("legal"))
        mod = bool(model_answer.get("legal")) if model_answer else None
        correct = (mod == eng) if mod is not None else False
        return {"score": 1.0 if correct else 0.0, "detail": {"correct": correct}}
    if task == "T3":
        eng_set = {_norm_action(a) for a in engine_answer.get("actions", [])}
        mod_set = {_norm_action(a) for a in model_answer.get("actions", [])}
        return _f1(eng_set, mod_set)
    if task in ("T5", "T6"):
        return _field_match(engine_answer, model_answer)
    return {"score": 0.0, "detail": {}}


def _f1(eng_set, mod_set):
    tp = len(eng_set & mod_set)
    fp = len(mod_set - eng_set)
    fn = len(eng_set - mod_set)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"score": f1,
            "detail": {"precision": precision, "recall": recall, "f1": f1,
                       "tp": tp, "fp": fp, "fn": fn}}


def _field_match(engine_answer: dict, model_answer: dict) -> dict:
    """关键字段精确匹配率。模型未答（None）→ 0 分。"""
    eng = engine_answer or {}
    mod = model_answer or {}
    if not mod.get("result") and mod.get("result") is None and "result" in mod:
        return {"score": 0.0, "detail": {"matched": 0, "total": 0, "skipped": True}}
    # 模型输出可能是 {result: {...}} 或直接字段
    mod_fields = mod.get("result") if isinstance(mod.get("result"), dict) else mod
    if not isinstance(mod_fields, dict):
        return {"score": 0.0, "detail": {"matched": 0, "total": 0}}
    keys = [k for k in eng if not isinstance(eng[k], dict)]
    matched = sum(1 for k in keys if mod_fields.get(k) == eng[k])
    total = len(keys)
    score = matched / total if total else 0.0
    return {"score": score, "detail": {"matched": matched, "total": total}}