# rift-bench

> 《符文战场》(Riftbound) 规则引擎 + 规则能力 benchmark + 规则问答智能体

完整设计见 [`开发计划书.md`](开发计划书.md)。

> [!IMPORTANT]
> 本仓库仅分发原创代码、测试和项目文档。Riot Games 的官方规则书、卡牌文字、FAQ、勘误、禁卡表、图片及抓取素材不进入 Git；由这些内容生成的数据集也不提交。详情见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 和 [`docs/DATA_SETUP.md`](docs/DATA_SETUP.md)。

## 项目定位

以 Riot Games 的 TCG《符文战场》为载体，构建三层平台：

1. **规则引擎** — 程序化、可验证地执行核心规则，作为 ground truth 基座。
2. **benchmark** — 评测 LLM / AI agent 的规则掌握（合法性判断、合法行动枚举、最优出牌、堆栈/战斗结算预测、构筑校验、规则问答）。
3. **规则问答智能体** — RAG + 引擎核验，回答玩家规则问题，引用规则编号。

**赛制范围**：v1.0 锁定 1v1 标准赛制。

## 技术栈

Python 单语言贯穿引擎 / 评测 / agent / UI。详见计划书 §2。

## 目录结构

```text
rift-bench/
├── .gitignore
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── README.md
├── 开发计划书.md
├── pyproject.toml
├── config/
│   └── llm.example.json
├── docs/
│   └── DATA_SETUP.md
├── src/riftbench/
│   ├── cards/
│   ├── banlist/
│   ├── errata/
│   ├── faq/
│   ├── engine/
│   ├── bench/
│   └── qa/
├── scripts/
├── tests/
└── .gitignore
```

以下目录只存在于本地开发环境，并已被 `.gitignore` 排除：

```text
规则书/          # 官方规则/FAQ PDF
raw/             # 原始 API、HTML 和 PDF
rules/           # 从官方 PDF 提取的文本
data/            # 由第三方内容生成的结构化数据
.scrape/         # 网站抓取产物
.extracted/      # PDF 临时提取文本
```

数据准备和重建方法见 [`docs/DATA_SETUP.md`](docs/DATA_SETUP.md)。
## P1 引擎 MVP — ✅ 完成

程序化执行简化但对局规则的引擎（开发计划书 §5/§8 MVP 边界）。

- **模块**（`src/riftbench/engine/`）：model（物体/区域/玩家）、state（GameState+快照+确定性）、setup（布置 110-118/485）、costs（费用+符文能量 164.2.a）、play（打出六步 349-359）、actions（合法行动+标准移动）、combat（简化战斗 459-466）、scoring（得分胜负 467-472+燃尽 431）、triggers（极简触发接口 383）、cleanup（清理固定步骤 323）、turn（回合驱动 315-317）、driver（对局驱动+回放）、agents/random（随机 baseline）。
- **MVP 边界**（已确认的三项精简决策）：①纯结构骨架不解析效果文本 ②跳过战斗法术对决步骤，只做伤害+结算+征服/据守 ③单态状态机（普通+开环），无响应窗口，[反应]牌不可用。
- **跑通的完整对局**：Setup → 回合循环 → 打出(原子回滚 358.5) → 基础符文产法力 → 标准移动+Contested(190.3) → 清理(323) → 战斗(465/466) → 征服/据守得分(470,终分封顶 471.1.b) → 胜利(8分)或燃尽(431)。
- **验证**：46 项引擎测试 + 100 局随机自我对局压力测试（0 异常、确定性可复现、平均 78 回合结束）。

## P2.1 效果引擎 — ✅ 完成

让卡牌效果真正可执行（此前 1000/1020 张卡是"白板"）。**1020 张主卡全部可解析**，其中 1004 张有可执行能力（触发 402 / 主动技能 64 / 指令 854 个）。

- **DSL**（`src/riftbench/engine/effects/`）：`model.py`（Ability/Trigger/Instruction/TargetFilter AST）、`parser.py`（卡面文本→能力，支持触发/主动/被动 + you may/if/this turn + 目标过滤器）、`executor.py`（指令→引擎操作，容错 055）、`events.py`（事件一等对象 + 触发注册/匹配/立即结算）、`keywords.py`（Temporary/Stun/Tank/Backline/Empower 等）、`manager.py`（集成钩子）。
- **能力覆盖**：触发（打出/征服/据守/死亡/进攻）、主动技能 `[T]:`、指令（play/give/ready/draw/deal/kill/score/gain...）。
- **触发立即结算**（已确认决策）：事件→匹配→排序→立即逐条执行，无响应窗口（P2.2 改入链+优先权）。
- **引擎集成**：`play.py` 进场触发+法术执行、`scoring.py` 征服/据守事件、`cleanup.py`/`combat.py` 死亡事件、`turn.py` 结束清效果+抽牌事件、`actions.py` activate 主动技能。
- **验证**：`tests/test_engine_effects.py` 20 项 + 全套 126 项测试全绿 + 100 局压力 0 异常。
- **覆盖率**：`scripts/effects_coverage.py`。

## P2.2 链与优先权 — ✅ 完成

把引擎从"原子立即结算"升级为**完整链式 + 优先权**架构（规则 332-348）。

- **四态状态机**（`state.py`）：`turn_state` 改为派生属性（Showdown? × Closed?），新增 `priority_player`/`focus_player`/`showdown_active` 字段。
- **FEPR 循环**（新 `fepr.py`）：Finalize(FIFO,337) → Execute(优先权,338) → Pass(让过,339) → Resolve(LIFO,340)；Add 技能即时结算（429.2）；Showdown 让过关闭（348）。
- **打出流程拆分**（`play.py`）：`begin_play`（354 入链+Pending+Closed）/ `finalize_pending`（337.1）/ `resolve_immediately`（337.2 Unit/Gear 立即进场）/ `resolve_spell`（法术留链→Execute 窗口）；合法时机按四态×[Reaction]/[Action] 判定（309.1.a/308.1.a）。
- **触发入链**（`effects/events.py`）：触发作为 Pending Chain Item 入链（383.3），对手可响应；Add 触发即时结算。
- **战斗法术对决**（`combat.py`）：`begin_combat` 进入 Showdown（464，Attacker 获 Focus），关闭后伤害+征服（465/466）。
- **driver**：主循环改为 cleanup → fepr → 优先权决策（[Reaction] 响应）→ resolve。
- **术语澄清**：无 "Swift" 关键字——[Swift]=规则 806 Action（迅捷），[Reaction]=813；[Action] 只给 Showdown 权限，[Reaction] 含 Closed 权限。
- **验证**：`tests/test_engine_fepr.py` 13 项（状态机/FEPR顺序/优先权/[Reaction]/[Action]/Counter窗口/战斗Showdown/触发入链）+ 全套 139 项全绿 + 50 局压力 0 异常。

## P2.3 深度规则 — ✅ 完成

补上替换效果 / Counter 完整 / 连续效果层 / 依赖关键字，让 L3 复杂度卡牌（含 instead/prevent）真正可执行。

- **连续效果层**（新 `effects/continuous.py`，规则 473-480）：持续修正（+N[M] / costs N less / 免伤）三层应用至收敛，写入 `continuous_might_mod`/`continuous_cost_mod`/`damage_immune`，`effective_might`/`determine_total_cost` 读取。
- **替换效果**（新 `effects/replacement.py`，规则 367-370）：统一"would X 发生 → 改做 Y"——prevent N 减伤 / double 翻倍 / damage_immune 免疫；伤害结算点调 `apply_damage`。
- **Counter 完整**（规则 425）：`_op_counter` 标记链上最近对手法术为 countered，`resolve_spell` 结算时进废牌堆不执行；防反修饰（uncounterable）。11 张 [Reaction] 反制卡全部可用。
- **依赖关键字**（规则 726-727）：parser 识别 `[Empowered][>]`/`[Level N][>]`/`[Legion][>]` → `condition_keyword`，executor 条件门控；Empowered 状态 / XP（规则 728）追踪。
- **验证**：`tests/test_engine_deep.py` 13 项 + 全套 152 项全绿 + 50 局压力 0 异常。
- **后续**：Linked Abilities（37 张，最发散，需跨段对象解析）、Delayed/Reflexive、非战斗 Showdown 独立里程碑。

## P3 Benchmark 评测框架 — ✅ 完成

用引擎作 ground truth 评测模型/agent 的规则掌握——"bench"定位的核心价值。

- **bench 包**（`src/riftbench/bench/`）：`tasks/`（T2 合法性 / T3 行动枚举 / T5 堆栈结算 / T6 战斗结算）、`scenarios.py`（隐私过滤观察视图 + 随机快照生成）、`harness.py`（评测运行器 + 引擎一致性 self_check）、`judge.py`（打分：T2 二值 / T3 F1 / T5·T6 字段匹配）、`models.py`（Random/Heuristic/LLM adapter）、`report.py`（榜单+错误分析）、`cli.py`。
- **评测对象**：RandomModel（naive baseline）、HeuristicModel（贪心策略）、LLMAdapter（可插拔接口，未配置回退）、engine agents（heuristic 对局 agent + LLM agent adapter）。
- **数据产出**：`data/bench/{T2,T3,T5,T6}/train.jsonl`（各 12-30 样本，seed 固定可复现）+ `data/bench/leaderboard.json`。
- **首个榜单**（random baseline，n=15）：T2 0.47 / T3 0.14 / T5 0.00 / T6 0.00——T5/T6 状态预测对无能力 baseline 得 0，展示任务难度下限。
- **验证**：`tests/test_bench.py` 13 项 + 全套 165 项全绿。
- **CLI**：`python -m riftbench.bench.cli --all --model random --n 15 --seed 0`
- **后续**：T1 规则问答（P5 QA）、T4 最优出牌（LLM-judge）、T7 构筑合法性、真实 LLM 评测（配 API key 后）。

## P5 规则问答智能体 — ✅ 完成

三大支柱的第三块——玩家提问规则/卡牌问题时检索作答、引用规则编号，可计算问题路由到引擎权威核验。

- **qa 包**（`src/riftbench/qa/`）：`corpus.py`（规则索引 2381 + 卡牌 1020 + FAQ 171 + 勘误 63）、`retriever.py`（纯 stdlib 轻量检索：中文术语桥接英文语料 + TF 加权 + 定义规则锚定）、`engine_check.py`（构筑校验/卡牌详情/禁卡查询 + 路由）、`agent.py`（RiftboundQA.answer 双模式）、`llm.py`（LLM 接口可插拔）、`cli.py`。
- **核心设计**：中文问题 × 英文语料，用**中英术语表**（`data/qa/terms.json`，73 词，规则编号锚定）桥接。术语核对发现并修正：法盾=Deflect(809, 非 Spellshield)、洞察=Vision(817, 非 Predict)、迅捷=Action(806)。
- **双模式**：①可计算问题（卡名/禁卡/牌表）→ 引擎权威判定 ②规则解释 → 检索命中规则编号+原文。
- **黄金问答集**：`data/qa/eval_questions.jsonl` 20 条，命中率 **90%**（无 LLM 检索型的合理水平）。
- **验证**：`tests/test_qa.py` 12 项 + 全套 177 项全绿。
- **CLI**：`python -m riftbench.qa.cli`（交互式问答）。
- **后续**：配 API key 后 `llm.py` 实现 Claude 中文自然语言解释；裁判 FAQ 中文结构化增强语料。

## P5.1 规则问答「专业裁判」增强 — ✅ 完成

针对实测短板（复杂判例只返回零散片段、卡牌匹配差、不推理顺序）的增强。

- **证据收集层**（四类依据）：
  - `card_match.py`：多卡识别 + 部分名（`Adap`→Adaptatron）+ 模糊拼写（difflib）
  - `rule_chain.py`：规则依据链（点分层级 `465.2.c.5`→父链→章节 + 兄弟子规则）
  - `flow_explain.py`：**引擎流程权威解释**（结算链→FEPR 337-340 / 战斗→464-466 / 回合→315-317 / 打出→354-359）
  - `effect_explain.py`：卡牌效果结构（复用 P2.1 parser → 中文"触发/主动/被动 + 指令序列"）
  - `evidence.py`：编排四类证据 → LLM 可读"事实块"
- **LLM 裁判层**（`llm.py`）：Claude 把卡牌原文+规则依据+引擎结构组织成**中文裁判回答**，强制引用规则编号与卡牌原文，防幻觉（只依据材料、材料不足要明说）。
- **agent 重构**：引擎核验路由 → 证据收集 → LLM 裁判 / 结构化回退。
- **无 key 回退**：结构化裁判回答（卡牌原文 + 效果结构 + 引擎流程 + 规则依据分块）。
- **验证**：`tests/test_qa_judge.py` 16 项（含 Mock LLM 验证流程）+ 全套 193 项全绿。
- **中文卡名支持**（P5.3）：接入中文官方牌库 `playloltcg.com`，按**卡牌编号**与英文库对照（中文 `OGN·001/298` ↔ 英文 `OGN-001/298`），1175 张中英对照。中文玩家可用**中文全名**（"安蓓萨 - 恶狼意志"）、**英雄简称**（"阿狸"/"亚索"）、**中文别名**（"复仇天使"）提问。第五弹 RAD（未发售）已过滤。产物 `data/qa/card_name_map.json`。入库脚本 `python scripts/ingest_cards_zh.py`。

- **启用 LLM 裁判**（多 provider，一次配置）：编辑 **`config/llm.json`** 填入 `api_key` 即可（`base_url`/`model` 已预填 DeepSeek）。**之后默认走 LLM 裁判模式，无需每次设环境变量。** 用别家的改 `base_url`/`model`（`config/llm.example.json` 含 DeepSeek/通义/Kimi/智谱/OpenAI/本地 Ollama 对照）。
  - 配置优先级：显式参数 > 环境变量 > `config/llm.json`。
  - 环境变量方式（可选）：`RIFTBENCH_LLM_BASE_URL/API_KEY/MODEL`（兼容 `OPENAI_*`/`ANTHROPIC_API_KEY`）。
  - 未填 key 时自动走结构化裁判回退。
  - **OpenAI 兼容服务（推荐，零依赖）**：任何一个 OpenAI 兼容端点，只需三值：
    ```bash
    set RIFTBENCH_LLM_BASE_URL=https://api.deepseek.com/v1
    set RIFTBENCH_LLM_API_KEY=sk-...
    set RIFTBENCH_LLM_MODEL=deepseek-chat
    ```
    主流服务 base_url：DeepSeek `https://api.deepseek.com/v1`｜通义千问 `https://dashscope.aliyuncs.com/compatible-mode/v1`｜Kimi `https://api.moonshot.cn/v1`｜智谱 GLM `https://open.bigmodel.cn/api/paas/v4`｜本地 Ollama `http://localhost:11434/v1`。也兼容 `OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL`。
  - **Anthropic 原生**：`pip install anthropic` + `set ANTHROPIC_API_KEY=...`。
  - 无配置时自动走结构化裁判回退（卡牌原文+效果结构+引擎流程+规则依据）。
- **下一步 P2.3**：替换效果（instead, 41 张）、连续效果层/战力计算、非战斗 Showdown、Counter 完整实现、Reflexive/Delayed/Linked 能力。

## 数据基座成果 (Phase 0)

> 以下数字来自本地开发环境中的数据构建，仅用于说明流程与能力。对应的第三方原始资料和派生数据集不包含在本仓库中。

### 卡牌数据库 — ✅ 完成

- **来源**：playriftbound.com 官方卡牌库 (PCS API + Sanity CMS)，英文。
- **全集**：1189 张 = 1020 主版本 + 169 变体（showcase 全画 / landscape 横版）。
- **覆盖**：set1-4 全量 + OGS 新手系列。

| set | id | 英文名 | 中文 | 主版本数 |
|---|---|---|---|---|
| set1 | OGN | Origins | 起源 | 310 |
| set2 | SFD | Spiritforged | 铸魂淬炼 | 251 |
| set3 | UNL | Unleashed | 破限 | 238 |
| set4 | VEN | Vendetta | 化神争锋 | 197 |
| 新手 | OGS | Proving Grounds | — | 24 |

- **双层模型**（呼应计划书 §4.2）：
  - `CardStatic`（可查询特征层）：类型/超类型/特性/战力/费用/稀有度/标签/编号。
  - `CardEffects`（效果脚本层）：`text`（token 已替换为规则符号 `[1][C][T][S][A]`，去 HTML）+ `text_raw`（原始 HTML 备查）+ `accessibility_text`（权威对照）。
- **超类型**：champion（英雄）/ signature（专属）/ basic（基础符文）/ token（指示物）。
- **验证**：`tests/test_cards_ingest.py` 12 项测试全过。

### 规则语料 — ✅ 完成

- 英文核心规则 PDF（42.9MB）+ 赛事规则 PDF（16.7MB）已下载并提取为纯文本（`rules/en/`）。
- 按规则编号索引化完成：`data/rules/core_rules_index.json` 含 **2381 条规则，0 空正文，0 重复**。
- 关键规则配对经测试验证：002 黄金法则 / 054 Can't beats Can / 055 容错执行 / 103.2.a 选定英雄 / 307 回合状态机 / 465.2.c.5 战斗伤害分配期替换 / 359.3.e.2 目标离场非法 / 805 Accelerate(急速) / 813 Reaction / 815 Tank。
- 章节映射 156 项（`data/rules/chapters.json`）。
- **编号核对结论**：英文版为权威基准，中英文编号一致。黄金法则 = `002`（非 053.1）、Can't beats Can = `054`（非 053.3）、容错执行 = `055`（非 054.2）。
- **核心规则补丁说明**（`data/rules/patch_notes/`）：4 个 set 的规则更新说明（约 86KB 纯文本），作为规则解释语料。

### 禁卡表 — ✅ 完成

- 来源：playriftbound.com rules-hub 页（2026-07-16 更新）。
- **标准 Constructed**：10 张（5 卡 + 5 战场）。
- **2v2 Constructed**：11 张（标准全部 + 1 传奇 Master Yi, Wuju Bladesman）。
- 全部 11 条匹配到卡牌库 internal_id。`tests/test_banlist.py` 7 项测试全过。

### 勘误 / FAQ — ✅ 完成

- 4 个 set 的英文勘误页 + 4 个 FAQ 页已下载并结构化入库（`data/errata/`、`data/faq/`）。
- **勘误**：63 条（OGN 34 / SFD 18 / UNL 8 / VEN 3），按 `卡名 + [NEW TEXT] + [OLD TEXT]` 结构化。63 个卡名经引号归一化 + 别名映射后 **100% 匹配卡牌库**，勘误订正层可自动应用。
- **FAQ**：171 条（OGN 97 / SFD 27 / UNL 13 / VEN 34），按 `主题 + Q + A` 结构化。
- **origins FAQ 已废弃**：官方声明内容已被核心规则 + 勘误吸收，全部 97 条标记 `deprecated: true`。
- **别名机制**：卡库 `Deceiver` 带官方全名别名 `Leblanc, Deceiver`（勘误用全名），通过 `CardStatic.aliases` 字段支持按名匹配。
- `tests/test_errata.py`（14 项）+ `tests/test_faq.py`（13 项）全过。

## P0 数据基座完成总览

| 模块 | 状态 | 数量 | 测试 |
|---|---|---|---|
| 卡牌数据库 | ✅ | 1020 主版本 + 169 变体 | 13 项 |
| 规则语料索引 | ✅ | 2381 条规则 (0 空正文) | 13 项 |
| 禁卡表 | ✅ | 11 条 (标准 10 + 2v2 11) | 7 项 |
| 核心规则补丁说明 | ✅ | 4 set, 86KB | — |
| 勘误 | ✅ | 63 条 (100% 匹配卡库) | 14 项 |
| FAQ | ✅ | 171 条 (origins 废弃) | 13 项 |

**全套 60 项测试通过**。运行 `PYTHONPATH=src python scripts/p0_overview.py` 查看完整性总览。

## 快速开始

> 本仓库不附带第三方数据。首次运行前请按 [`docs/DATA_SETUP.md`](docs/DATA_SETUP.md) 在本地准备原始资料并生成 `data/`。全新 clone 在完成这些步骤前，数据相关测试和命令不可直接运行。

```bash
# 重新生成卡牌数据库
PYTHONPATH=src python scripts/ingest_cards.py

# 跑卡牌测试
PYTHONPATH=src python tests/test_cards_ingest.py
# 或
pip install -e ".[test]" && pytest

# 使用卡牌库
python -c "
import sys; sys.path.insert(0,'src')
from riftbench.cards import CardDatabase
db = CardDatabase.load('data/cards/cards.json')
c = db.get_main('UNL', 131)
print(c.static.name, c.effects.text)
"
```

## 待办（见计划书路线图）

- [x] P0 卡牌数据库
- [x] P0 规则语料索引化（编号↔正文配对，2381 条）
- [x] P0 勘误/FAQ/禁卡表结构化（63 勘误 + 171 FAQ + 11 禁卡 + 4 补丁说明）
- [x] P1 引擎 MVP（46 测试 + 100 局压力测试）
- [x] P2.1 效果引擎（DSL/触发/主动/关键字，20 测试 + 100% 解析）
- [x] P2.2 链与优先权（完整 FEPR/优先权/[Reaction] 响应/战斗法术对决，13 测试 + 50 局压力）
- [x] P2.3 深度规则（替换效果/Counter/连续效果层/依赖关键字，13 测试 + 50 局压力）
- [x] P3 Benchmark 评测框架（T2/T3/T5/T6 四任务 + harness + 榜单，13 测试）
- [x] P5 规则问答智能体（检索式+引擎核验，12 测试 + 90% 命中率）
- [x] P5.1 裁判增强（证据链+引擎流程+效果结构+LLM 裁判层，16 测试）
- [x] P5.2 QA 多 provider（OpenAI 兼容第三方 LLM，零依赖，5 测试）
- [x] P5.3 中英卡名对照（接入中文牌库 playloltcg.com，按编号对照 1175 张，11 测试）
- [x] P5.4 LLM 配置文件（`config/llm.json` 为本地文件、不提交；一次填写默认 LLM 裁判模式，5 测试）
- [ ] P4/P6：真实 LLM 评测、T4 最优出牌、T7 构筑、QA 接 LLM、可视化
## 许可与第三方内容

本项目原创代码和文档采用 [MIT License](LICENSE)。Riftbound、Riot Games、
League of Legends 及相关名称、规则书、卡牌文字、FAQ、勘误、美术和其他
游戏素材的权利归其各自权利人所有，不在本仓库的 MIT 许可范围内，也未随
仓库分发。详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。