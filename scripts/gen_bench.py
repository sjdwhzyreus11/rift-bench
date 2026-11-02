"""生成 benchmark 样本集 data/bench/{task}/train.jsonl（可复现，seed 固定）。

用法: PYTHONPATH=src python scripts/gen_bench.py [--n 50] [--seed 0]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.bench import harness


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tasks", default="T2,T3,T5,T6")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    for task in args.tasks.split(","):
        samples = harness.generate_samples(task, args.n, seed=args.seed)
        out = root / "data" / "bench" / task / "train.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False, default=str) + "\n")
        print(f"[gen] {task}: {len(samples)} 样本 -> {out.relative_to(root)}")


if __name__ == "__main__":
    main()