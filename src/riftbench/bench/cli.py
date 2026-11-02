"""Benchmark CLI — 运行评测并输出榜单。

用法:
  python -m riftbench.bench.cli --task T2 --model random --n 20 --seed 0
  python -m riftbench.bench.cli --all --n 20 --seed 0          # 全任务 × random/heuristic
  python -m riftbench.bench.cli --self-check T2                 # 引擎一致性检查
"""
from __future__ import annotations

import argparse
import sys

from riftbench.bench import harness, report
from riftbench.bench.models import HeuristicModel, LLMAdapter, RandomModel


def _models(name: str):
    if name == "random":
        return RandomModel()
    if name == "heuristic":
        return HeuristicModel()
    if name == "llm":
        return LLMAdapter()
    raise ValueError(f"未知模型 {name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="rift-bench benchmark")
    ap.add_argument("--task", choices=["T2", "T3", "T5", "T6"])
    ap.add_argument("--all", action="store_true", help="跑全部任务")
    ap.add_argument("--model", default="random", help="random/heuristic/llm")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--self-check", metavar="TASK", help="引擎一致性检查")
    args = ap.parse_args()

    if args.self_check:
        r = harness.self_check(args.self_check, n=5, seed=args.seed)
        print(f"[self-check] {args.self_check}: {r}")
        return

    tasks = ["T2", "T3", "T5", "T6"] if args.all else [args.task]
    if not tasks or (not args.all and args.task is None):
        ap.print_help()
        sys.exit(1)

    runs = []
    for t in tasks:
        m = _models(args.model)
        r = harness.run(t, m, n=args.n, seed=args.seed)
        print(f"[{t}] {args.model}: mean={r['aggregate']['mean']:.3f} "
              f"pass={r['aggregate']['pass']}/{r['aggregate']['total']}")
        runs.append(r)

    report.save_report(runs, "data/bench/leaderboard.json")
    print("[done] 榜单 -> data/bench/leaderboard.json")


if __name__ == "__main__":
    main()