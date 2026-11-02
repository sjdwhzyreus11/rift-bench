"""riftbench.engine: 《符文战场》规则执行引擎。

P1 MVP 范围（见 plans/unified-drifting-scone.md）:
  - 单态状态机（普通+开环），无响应窗口
  - 纯结构骨架，不解析卡牌效果文本（效果留 P2）
  - 简化战斗（跳过法术对决步骤，只做伤害+结算+得分）
  - 1v1 标准赛制（胜利分=8，战场=2，后手首召出+1符文）

模块:
  model    — 游戏物体/区域/玩家 + 枚举
  state    — GameState 状态对象
  setup    — 初始布置
  costs    — 费用计算与支付
  play     — 打出卡牌流程
  actions  — 合法行动枚举与校验
  scoring  — 得分与胜负
  combat   — 简化战斗
  triggers — 极简触发（打出效果/征服据守记账）
  cleanup  — 清理步骤
  turn     — 回合驱动
  driver   — 对局驱动器
  errors   — 异常
  agents   — AI agent（random baseline）
"""
from riftbench.engine.errors import GameOver, IllegalActionError

__all__ = ["GameOver", "IllegalActionError"]
