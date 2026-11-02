"""riftbench.bench.tasks: 四类确定性 benchmark 任务。

每个任务模块提供:
  generate(state, viewpoint, rng) -> dict  # 生成样本 {question, engine_answer, meta}
  answer(question, state) -> dict          # 引擎正答（供 judge 对比）

T2 legality — 拟议行动合法性判断（二值）
T3 action_enum — 合法行动枚举（F1）
T5 stack_resolve — 堆栈/触发结算预测（状态匹配）
T6 combat_predict — 战斗结算预测（状态匹配）
"""
