"""评测运行器（bench/harness.py）。

流程:
  1. 生成样本（黄金 + 随机，从任务模块）
  2. 逐个调模型 answer(question)
  3. judge 打分（引擎正答 vs 模型输出）
  4. 聚合（按任务/难度）→ 报告

含 self_check（引擎一致性检查：同场景重跑正答一致）。
"""
from __future__ import annotations

import random
from typing import Optional

from riftbench.bench import scenarios
from riftbench.bench.judge import judge


# 任务注册表：task_name -> (generate, answer)
def _task_generator(task: str):
    if task == "T2":
        from riftbench.bench.tasks import legality
        return legality.generate
    if task == "T3":
        from riftbench.bench.tasks import action_enum
        return action_enum.generate
    if task == "T5":
        from riftbench.bench.tasks import stack_resolve
        return stack_resolve.generate
    if task == "T6":
        from riftbench.bench.tasks import combat_predict
        return combat_predict.generate
    raise ValueError(f"未知任务 {task}")


def generate_samples(task: str, n: int, seed: int = 0) -> list[dict]:
    """生成 n 个样本。返回 [sample]（可能少于 n，因为部分场景生成失败跳过）。"""
    gen = _task_generator(task)
    rng = random.Random(seed)
    samples = []
    for i in range(n * 3):  # 3x 余量（跳过失败）
        if len(samples) >= n:
            break
        state, viewpoint = scenarios.make_random_scenario_state(seed=seed * 31 + i)
        s = gen(state, viewpoint, rng, meta={"seed": seed * 31 + i})
        if s is None:
            continue
        s["id"] = f"{task}-{seed}-{len(samples)}"
        samples.append(s)
    return samples


def self_check(task: str, n: int = 5, seed: int = 0) -> dict:
    """引擎一致性检查：同场景重跑 N 次，断言引擎正答一致。"""
    gen = _task_generator(task)
    consistent = 0
    total = 0
    for i in range(n):
        state, viewpoint = scenarios.make_random_scenario_state(seed=seed * 13 + i)
        rng1 = random.Random(seed)
        s1 = gen(state, viewpoint, rng1)
        if s1 is None:
            continue
        # 重跑（同 seed 应一致）
        rng2 = random.Random(seed)
        state2, _ = scenarios.make_random_scenario_state(seed=seed * 13 + i)
        s2 = gen(state2, viewpoint, rng2)
        if s2 is None:
            continue
        total += 1
        if s1["engine_answer"] == s2["engine_answer"]:
            consistent += 1
    return {"consistent": consistent, "total": total,
            "ok": consistent == total and total > 0}


def run(task: str, model, n: int = 20, seed: int = 0) -> dict:
    """跑评测：生成样本 → 模型回答 → judge 打分 → 聚合。"""
    samples = generate_samples(task, n, seed)
    results = []
    for s in samples:
        q = s["question"]
        q["task"] = task  # 保证 task 字段
        try:
            model_answer = model.answer(q)
        except Exception as e:
            model_answer = {"result": None, "error": str(e)}
        r = judge(task, s["engine_answer"], model_answer)
        results.append({
            "id": s["id"],
            "score": r["score"],
            "detail": r["detail"],
            "model_answer": model_answer,
            "engine_answer": s["engine_answer"],
        })
    agg = _aggregate(results)
    return {"task": task, "model": model.name, "samples": len(results),
            "aggregate": agg, "results": results}


def _aggregate(results: list[dict]) -> dict:
    if not results:
        return {"mean": 0.0, "pass": 0, "total": 0}
    scores = [r["score"] for r in results]
    mean = sum(scores) / len(scores)
    # pass = score >= 0.9（T2/T3 单样本满分；T5/T6 字段匹配>=0.9）
    passed = sum(1 for s in scores if s >= 0.9)
    return {"mean": round(mean, 4), "pass": passed, "total": len(results)}