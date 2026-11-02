"""bench 评测框架测试。

覆盖:
  - judge 打分正确性（T2 二值 / T3 F1 / T5·T6 字段匹配）
  - 任务生成（T2/T3/T5/T6 样本结构、引擎正答确定可复现）
  - harness 跑通（random/heuristic 模型）
  - 场景生成确定性
  - self_check 引擎一致性
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.bench import harness, scenarios
from riftbench.bench.judge import judge
from riftbench.bench.models import HeuristicModel, RandomModel


# ---------- judge ----------

def test_judge_t2_exact():
    r = judge("T2", {"legal": True}, {"legal": True})
    assert r["score"] == 1.0
    r2 = judge("T2", {"legal": True}, {"legal": False})
    assert r2["score"] == 0.0


def test_judge_t3_f1():
    r = judge("T3",
              {"actions": [{"type": "a"}, {"type": "b"}, {"type": "c"}]},
              {"actions": [{"type": "a"}, {"type": "b"}, {"type": "x"}]})
    # tp=2, fp=1, fn=1 → precision 2/3, recall 2/3, F1 = 2*(2/3)*(2/3)/(2/3+2/3) = 2/3
    assert abs(r["score"] - 2 / 3) < 1e-6
    assert r["detail"]["precision"] == 2 / 3


def test_judge_t6_field_match():
    r = judge("T6",
              {"controller": "south", "north_survivors": 0},
              {"result": {"controller": "south", "north_survivors": 1}})
    # 1/2 字段匹配
    assert r["score"] == 0.5
    # 未作答 → 0
    r2 = judge("T6", {"controller": "south"}, {"result": None})
    assert r2["score"] == 0.0


# ---------- 任务生成 ----------

def test_t2_generate_structure():
    state, vp = scenarios.make_random_scenario_state(seed=42)
    from riftbench.bench.tasks import legality
    import random
    s = legality.generate(state, vp, random.Random(1))
    assert s["question"]["task"] == "T2"
    assert "legal" in s["engine_answer"]


def test_t3_generate_has_candidates():
    state, vp = scenarios.make_random_scenario_state(seed=42)
    from riftbench.bench.tasks import action_enum
    import random
    s = action_enum.generate(state, vp, random.Random(1))
    assert s["question"]["task"] == "T3"
    assert "candidates" in s["question"]
    # 合法集应非空或含候选
    assert s["engine_answer"]["actions"] or s["question"]["candidates"]


def test_t5_generate_or_none():
    """T5 生成返回样本或 None（无 play 行动时跳过）。"""
    state, vp = scenarios.make_random_scenario_state(seed=42)
    from riftbench.bench.tasks import stack_resolve
    import random
    s = stack_resolve.generate(state, vp, random.Random(1))
    if s is not None:
        assert s["question"]["task"] == "T5"
        assert "action" in s["question"]


def test_t6_generate_structure():
    state, vp = scenarios.make_random_scenario_state(seed=42)
    from riftbench.bench.tasks import combat_predict
    import random
    s = combat_predict.generate(state, vp, random.Random(1))
    if s is not None:
        assert s["question"]["task"] == "T6"
        assert "controller" in s["engine_answer"]


# ---------- 场景生成确定性 ----------

def test_scenario_determinism():
    """同 seed 同样本（状态一致）。"""
    st1, vp1 = scenarios.make_random_scenario_state(seed=7)
    st2, vp2 = scenarios.make_random_scenario_state(seed=7)
    assert vp1 == vp2
    # 手牌数一致（简化断言，完整状态比较复杂）
    from riftbench.engine.model import ZoneType
    assert len(st1.objects_in(vp1, ZoneType.HAND)) == len(st2.objects_in(vp2, ZoneType.HAND))


def test_observation_view_has_public_info():
    """观察视图含公开信息（分数/战场/场上单位）。"""
    state, vp = scenarios.make_random_scenario_state(seed=42)
    obs = scenarios.observation_of(state, vp)
    assert "scores" in obs
    assert "battlefields" in obs
    assert "hand" in obs
    assert "turn_player" in obs


# ---------- harness ----------

def test_harness_run_t2():
    r = harness.run("T2", RandomModel(seed=1), n=5, seed=1)
    assert r["samples"] == 5
    assert 0.0 <= r["aggregate"]["mean"] <= 1.0
    assert r["aggregate"]["total"] == 5


def test_harness_heuristic_model():
    r = harness.run("T3", HeuristicModel(seed=1), n=5, seed=1)
    assert r["samples"] == 5


def test_self_check_consistent():
    r = harness.self_check("T2", n=3, seed=1)
    assert r["ok"] is True
    assert r["consistent"] == r["total"]


def test_llm_adapter_not_configured():
    """LLMAdapter 未配置时返回 skipped 占位。"""
    from riftbench.bench.models import LLMAdapter
    a = LLMAdapter()
    assert a.is_configured is False
    r = a.answer({"task": "T2"})
    assert r.get("skipped") is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {type(e).__name__} {e}"); failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)