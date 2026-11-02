"""riftbench.bench: Benchmark 评测框架。

用引擎作 ground truth，评测模型/agent 对《符文战场》规则的掌握。
确定性任务四类（计划书 §7）:
  T2 合法性判断 / T3 合法行动枚举 / T5 堆栈结算预测 / T6 战斗结算预测

结构:
  tasks/      — 任务定义与引擎正答生成
  scenarios.py— 黄金样本 + 随机快照生成
  models.py   — 待测模型接口（Random/Heuristic/LLM adapter）
  harness.py  — 评测运行器 + 一致性检查
  judge.py    — 打分器
  report.py   — 榜单 + 错误分析
"""
