"""报告（bench/report.py）— 榜单 + 错误分析。"""
from __future__ import annotations

import json
from pathlib import Path


def build_leaderboard(runs: list[dict]) -> dict:
    """聚合多次 run 结果 → 榜单（按任务 × 模型）。"""
    leaderboard = {}
    for run in runs:
        task = run["task"]
        model = run["model"]
        leaderboard.setdefault(task, {})[model] = {
            "mean": run["aggregate"]["mean"],
            "pass": run["aggregate"]["pass"],
            "total": run["aggregate"]["total"],
        }
    return {"leaderboard": leaderboard}


def error_analysis(run: dict, top_k: int = 5) -> list[dict]:
    """从一次 run 抽取答错样本（供人工核查）。"""
    wrong = [r for r in run["results"] if r["score"] < 0.5]
    wrong.sort(key=lambda r: r["score"])
    return [
        {"id": r["id"], "score": r["score"], "model_answer": r["model_answer"],
         "engine_answer": r["engine_answer"]}
        for r in wrong[:top_k]
    ]


def save_report(runs: list[dict], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lb = build_leaderboard(runs)
    errors = {f"{r['task']}/{r['model']}": error_analysis(r) for r in runs}
    payload = {"leaderboard": lb["leaderboard"], "errors": errors}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[report] 榜单+错误分析 -> {path}")
    return payload