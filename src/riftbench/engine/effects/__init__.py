"""riftbench.engine.effects: 卡牌效果 DSL 与执行。

P2.1 效果引擎（见 plans/unified-drifting-scone.md §P2.1）:
  - 把 CardEffects.text 解析为可执行的能力 AST（模型见 model.py）。
  - 事件系统 + 触发立即结算（events.py / trigger_queue.py）。
  - 指令执行器（executor.py），关键字执行（keywords.py）。
"""