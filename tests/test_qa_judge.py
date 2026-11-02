"""P5.1 裁判增强测试（tests/test_qa_judge.py）。

覆盖:
  - 卡牌匹配: 部分名(Adap→Adaptatron)/多卡/模糊拼写
  - 规则依据链: 点分层级父链 + 章节
  - 引擎流程: 结算链→FEPR四步 / 战斗→三步骤
  - 效果结构: 卡牌效果拆解
  - LLM 裁判层: Mock client 验证流程; 无 key 回退
  - 端到端: 复杂判例返回结构化依据
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.qa.agent import RiftboundQA
from riftbench.qa.card_match import CardMatcher
from riftbench.qa.corpus import Corpus
from riftbench.qa.effect_explain import EffectExplainer
from riftbench.qa.flow_explain import FlowExplainer
from riftbench.qa.llm import JudgeLLM
from riftbench.qa.rule_chain import RuleChainBuilder, parent_chain

ROOT = Path(__file__).resolve().parents[1]


def _corpus():
    return Corpus(ROOT).load()


# ---------- 卡牌匹配 ----------

def test_card_match_partial():
    """部分名 Adap → Adaptatron。"""
    m = CardMatcher(_corpus())
    res = m.match_all("Adap 的效果")
    names = [r["name"] for r in res]
    assert any("Adaptatron" == n for n in names), f"应匹配 Adaptatron: {names}"


def test_card_match_multi():
    """一句话含多张卡 → 全部识别。"""
    m = CardMatcher(_corpus())
    res = m.match_all("Abandon 和 Adaptatron 同时在链上怎么结算")
    names = {r["name"] for r in res}
    assert "Abandon" in names and "Adaptatron" in names, f"应含两卡: {names}"


def test_card_match_exact():
    m = CardMatcher(_corpus())
    res = m.match_all("Scrapheap 是什么")
    assert any(r["name"] == "Scrapheap" for r in res)


# ---------- 规则依据链 ----------

def test_parent_chain():
    assert parent_chain("465.2.c.5") == ["465.2.c", "465.2", "465"]
    assert parent_chain("431") == []


def test_rule_chain_contains_anchor_and_parents():
    c = _corpus()
    b = RuleChainBuilder(c)
    ch = b.build("465.2.c.5")
    rules = [p["rule"] for p in ch["chain"]]
    assert "465.2.c.5" in rules, f"链应含锚点: {rules}"
    assert "465" in rules, f"链应含顶层: {rules}"
    # 章节可选（chapters.json 只收录正文为标题的顶级编号）


# ---------- 引擎流程 ----------

def test_flow_chain_resolution():
    f = FlowExplainer().detect("结算链怎么结算")
    assert f is not None
    rules = [s["rule"] for s in f["steps"]]
    assert "337" in rules and "340" in rules, f"FEPR 四步: {rules}"


def test_flow_combat():
    f = FlowExplainer().detect("战斗伤害怎么分配")
    assert f is not None
    rules = [s["rule"] for s in f["steps"]]
    assert "465" in rules, f"战斗伤害应含 465: {rules}"


def test_flow_turn():
    f = FlowExplainer().detect("回合有哪些阶段")
    assert f is not None
    assert any("315" in s["rule"] or "316" in s["rule"] for s in f["steps"])


# ---------- 效果结构 ----------

def test_effect_explain_triggered():
    e = EffectExplainer()
    r = e.explain("Adaptatron", "When I conquer, you may kill a gear.")
    assert r["parseable"]
    joined = " ".join(r["structure"])
    assert "触发式" in joined and "摧毁" in joined, joined


def test_effect_explain_activated():
    e = EffectExplainer()
    r = e.explain("T", "[T]: Give a unit +3 [M] this turn.")
    assert any("主动技能" in s for s in r["structure"]), r["structure"]


# ---------- LLM 裁判层 ----------

class _MockBlock:
    def __init__(self, text):
        self.text = text


class _MockMsg:
    def __init__(self, text):
        self.content = [_MockBlock(text)]


class _MockClient:
    class messages:
        @staticmethod
        def create(**kwargs):
            return _MockMsg("【结论】测试裁判回答 [规则 465.2]")


def test_llm_not_configured_returns_none(tmp_path):
    """无 key 且无 config → 未配置（隔离真实 config）。"""
    import os
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        llm = JudgeLLM(config_path=tmp_path / "no_such.json")
        assert llm.is_configured is False
        assert llm.judge("q", "facts") is None
    finally:
        if saved:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_llm_mock_client():
    """注入 Mock client → 走 LLM 裁判路径。"""
    llm = JudgeLLM(client=_MockClient())
    assert llm.is_configured is True
    out = llm.judge("测试问题", "材料")
    assert out and "规则" in out


def test_agent_with_mock_llm_uses_judge():
    """agent + Mock LLM → source=judge。"""
    qa = RiftboundQA(ROOT, llm=JudgeLLM(client=_MockClient()))
    r = qa.answer("战斗伤害怎么分配")
    assert r["source"] == "judge", f"应走 LLM 裁判: {r['source']}"
    assert "规则" in r["answer"]


# ---------- 端到端（无 key 结构化回退） ----------

def test_agent_structured_fallback_flow():
    qa = RiftboundQA(ROOT)
    r = qa.answer("对方用 Reaction 响应时结算链怎么结算")
    assert r["source"] in ("structured", "judge")
    assert "337" in r["citations"] or "338" in r["citations"]


def test_agent_card_effect_order():
    qa = RiftboundQA(ROOT)
    r = qa.answer("Adap 的效果按什么顺序执行")
    assert "Adaptatron" in r["cards"]
    assert "效果执行结构" in r["answer"] or "383" in str(r["citations"])


def test_agent_simple_card_still_engine():
    """单纯问卡牌 → 仍走引擎核验。"""
    qa = RiftboundQA(ROOT)
    r = qa.answer("Abandon 是什么卡")
    assert r["source"] == "engine"


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


# ---------- P5.2 多 provider ----------

def test_provider_infer_openai(tmp_path):
    """设 OPENAI_API_KEY + BASE_URL → provider=openai。"""
    import os
    saved = {k: os.environ.get(k) for k in
             ["RIFTBENCH_LLM_PROVIDER", "RIFTBENCH_LLM_BASE_URL", "RIFTBENCH_LLM_API_KEY",
              "RIFTBENCH_LLM_MODEL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
              "ANTHROPIC_API_KEY"]}
    try:
        for k in saved:
            os.environ.pop(k, None)
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com/v1"
        os.environ["OPENAI_MODEL"] = "deepseek-chat"
        empty = tmp_path / "empty.json"
        llm = JudgeLLM(config_path=empty)
        assert llm.provider == "openai"
        assert llm.is_configured is True
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)


def test_provider_infer_anthropic(tmp_path):
    import os
    saved = {k: os.environ.get(k) for k in
             ["RIFTBENCH_LLM_PROVIDER", "RIFTBENCH_LLM_BASE_URL", "RIFTBENCH_LLM_API_KEY",
              "RIFTBENCH_LLM_MODEL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY"]}
    try:
        for k in saved:
            os.environ.pop(k, None)
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        empty = tmp_path / "empty.json"
        llm = JudgeLLM(config_path=empty)
        assert llm.provider == "anthropic"
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)


def test_openai_compat_judge():
    """注入 Mock _post → 验证 OpenAI 兼容调用。"""
    calls = {}

    def mock_post(url, headers, payload, timeout=60):
        calls["url"] = url
        calls["headers"] = headers
        calls["payload"] = payload
        return {"choices": [{"message": {"content": "【结论】第三方模型裁判回答 [规则 465.2]"}}]}

    llm = JudgeLLM(provider="openai", api_key="sk-x",
                   base_url="https://api.deepseek.com/v1", model="deepseek-chat",
                   _post=mock_post)
    assert llm.is_configured
    out = llm.judge("战斗伤害怎么分配", "材料块")
    assert "规则 465.2" in out
    assert calls["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert "Bearer sk-x" in calls["headers"]["Authorization"]
    assert calls["payload"]["model"] == "deepseek-chat"
    assert any(m["role"] == "system" for m in calls["payload"]["messages"])


def test_env_priority_riftbench_over_openai():
    """RIFTBENCH_LLM_* 优先于 OPENAI_*。"""
    import os
    saved = {k: os.environ.get(k) for k in
             ["RIFTBENCH_LLM_BASE_URL", "RIFTBENCH_LLM_MODEL", "OPENAI_BASE_URL", "OPENAI_MODEL",
              "RIFTBENCH_LLM_API_KEY", "OPENAI_API_KEY"]}
    try:
        os.environ["OPENAI_BASE_URL"] = "https://a.example/v1"
        os.environ["RIFTBENCH_LLM_BASE_URL"] = "https://b.example/v1"
        os.environ["RIFTBENCH_LLM_API_KEY"] = "k"
        os.environ["RIFTBENCH_LLM_MODEL"] = "m1"
        llm = JudgeLLM()
        assert llm.base_url == "https://b.example/v1"
        assert llm.model == "m1"
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)


def test_describe_no_key_leak():
    llm = JudgeLLM(provider="openai", api_key="SECRET", base_url="https://x/v1", model="m")
    d = llm.describe()
    assert "SECRET" not in d
    assert "openai" in d


# ---------- P5.4 配置文件加载 ----------

def test_config_file_loading(tmp_path):
    """从 config 文件读取 provider/base_url/model/api_key。"""
    import json
    cfg = tmp_path / "llm.json"
    cfg.write_text(json.dumps({"provider": "openai", "base_url": "https://x.example/v1",
                               "api_key": "sk-cfg", "model": "m-cfg"}), encoding="utf-8")
    llm = JudgeLLM(config_path=cfg)
    assert llm.provider == "openai"
    assert llm.base_url == "https://x.example/v1"
    assert llm.model == "m-cfg"
    assert llm.is_configured is True


def test_config_empty_key_not_configured(tmp_path):
    """config 里 api_key 为空 → 未配置（走回退）。"""
    import json
    cfg = tmp_path / "llm.json"
    cfg.write_text(json.dumps({"provider": "openai", "base_url": "https://x/v1",
                               "api_key": "", "model": "m"}), encoding="utf-8")
    llm = JudgeLLM(config_path=cfg)
    assert llm.is_configured is False


def test_env_overrides_config(tmp_path):
    """环境变量覆盖配置文件。"""
    import json, os
    cfg = tmp_path / "llm.json"
    cfg.write_text(json.dumps({"provider": "openai", "base_url": "https://cfg/v1",
                               "api_key": "sk-cfg", "model": "m-cfg"}), encoding="utf-8")
    saved = os.environ.get("RIFTBENCH_LLM_MODEL")
    try:
        os.environ["RIFTBENCH_LLM_MODEL"] = "m-env"
        llm = JudgeLLM(config_path=cfg)
        assert llm.model == "m-env", "环境变量应覆盖 config"
    finally:
        if saved is not None:
            os.environ["RIFTBENCH_LLM_MODEL"] = saved
        else:
            os.environ.pop("RIFTBENCH_LLM_MODEL", None)


def test_param_overrides_env(tmp_path):
    """显式参数覆盖环境变量。"""
    import json, os
    cfg = tmp_path / "llm.json"
    cfg.write_text(json.dumps({"provider": "openai", "base_url": "https://cfg/v1",
                               "api_key": "sk-cfg", "model": "m-cfg"}), encoding="utf-8")
    llm = JudgeLLM(model="m-param", config_path=cfg)
    assert llm.model == "m-param"


def test_real_config_file_shape():
    """项目 config/llm.json 存在且结构正确。"""
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "config" / "llm.json"
    assert p.exists(), "config/llm.json 应存在"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    for k in ("provider", "base_url", "api_key", "model"):
        assert k in cfg, f"config 缺字段 {k}"
