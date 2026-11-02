"""LLM 裁判层（qa/llm.py）— 多 provider + 配置文件，把材料组织成中文裁判回答。

配置优先级：显式参数 > 环境变量 > 配置文件(config/llm.json) > 推断。
多 provider:
  - "openai"   : OpenAI 兼容接口（POST {base_url}/chat/completions）——零依赖（stdlib urllib）。
                 DeepSeek/通义千问/Kimi/智谱/硅基流动/OpenAI/本地 Ollama 等均属此类。
  - "anthropic": Anthropic 原生 SDK（需 pip install anthropic）。

配置文件 config/llm.json:
  {"provider":"openai","base_url":"...","api_key":"...","model":"..."}

环境变量（覆盖配置文件）:
  RIFTBENCH_LLM_PROVIDER / BASE_URL / API_KEY / MODEL
  （兼容 OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL / ANTHROPIC_API_KEY）

未配置（api_key 空）→ is_configured=False，judge 返回 None（agent 走结构化回退）。
防幻觉：只依据"事实块"作答；强制引用规则编号与卡牌原文；材料不足要明说。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

SYSTEM_PROMPT = """你是《符文战场》(Riftbound) 的规则裁判。你的回答必须像专业裁判判例一样严谨、有理有据。

严格要求：
1. 只依据【参考材料】作答，禁止编造规则或卡牌效果。
2. 每个结论都要引用依据：规则用编号（如 [规则 465.2.c.5]），卡牌用原文引用。
3. 涉及顺序/流程的问题，要分步骤推理（第一步…第二步…），说明每步的规则依据。
4. 材料不足以判断时，明确说"现有规则材料未明确覆盖此情形，建议查阅裁判 FAQ"，不要臆断。
5. 用中文回答。语气专业、简洁。

输出结构建议：
- 【结论】一句话给出判定
- 【依据与推理】分步骤，每步带规则编号/卡牌原文引用
- 【注意】若有边界情况或例外，一并说明"""


def _default_post(url: str, headers: dict, payload: dict, timeout: int = 60) -> dict:
    """默认 HTTP POST（stdlib）。返回解析后的 JSON。"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class JudgeLLM:
    """多 provider 裁判层。未配置 → judge 返回 None。"""

    CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "llm.json"

    def __init__(self, provider: Optional[str] = None, api_key: Optional[str] = None,
                 base_url: Optional[str] = None, model: Optional[str] = None,
                 client: Optional[object] = None, _post: Optional[Callable] = None,
                 config_path: Optional[Path] = None) -> None:
        # 优先级：显式参数 > 环境变量 > 配置文件
        env = os.environ
        cfg = self._load_config(config_path)
        self.api_key = (api_key or env.get("RIFTBENCH_LLM_API_KEY")
                        or env.get("OPENAI_API_KEY") or env.get("ANTHROPIC_API_KEY")
                        or cfg.get("api_key") or None)
        self.base_url = (base_url or env.get("RIFTBENCH_LLM_BASE_URL")
                         or env.get("OPENAI_BASE_URL") or cfg.get("base_url") or None)
        self.model = (model or env.get("RIFTBENCH_LLM_MODEL")
                      or env.get("OPENAI_MODEL") or cfg.get("model") or None)
        self.provider = (provider or env.get("RIFTBENCH_LLM_PROVIDER")
                         or ("anthropic" if client is not None
                             else (cfg.get("provider") or self._infer_provider())))
        if self.model is None:
            self.model = "claude-sonnet-5" if self.provider == "anthropic" else ""
        self._client = client
        self._post = _post or _default_post

    @classmethod
    def _load_config(cls, config_path: Optional[Path] = None) -> dict:
        """从 config/llm.json 读取配置。不存在/损坏 → {}。"""
        p = config_path or cls.CONFIG_PATH
        if p and Path(p).exists():
            try:
                return json.loads(Path(p).read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _infer_provider(self) -> str:
        env = os.environ
        if env.get("RIFTBENCH_LLM_BASE_URL") or env.get("OPENAI_BASE_URL") or env.get("OPENAI_API_KEY"):
            return "openai"
        if env.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        return "none"

    @property
    def is_configured(self) -> bool:
        if self._client is not None:
            return True
        if self.provider == "openai":
            return bool(self.base_url and self.api_key and self.model)
        if self.provider == "anthropic":
            return bool(self.api_key)
        return False

    def describe(self) -> str:
        if not self.is_configured:
            return "未配置（走结构化回退）——在 config/llm.json 填入 base_url/api_key/model"
        if self.provider == "openai":
            return f"provider=openai base_url={self.base_url} model={self.model}"
        return f"provider=anthropic model={self.model}"

    def judge(self, question: str, facts: str) -> Optional[str]:
        if not self.is_configured:
            return None
        if self.provider == "openai":
            return self._openai_judge(question, facts)
        if self.provider == "anthropic":
            return self._anthropic_judge(question, facts)
        return None

    # ---------- OpenAI 兼容（零依赖） ----------

    def _openai_judge(self, question: str, facts: str) -> Optional[str]:
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{facts}\n\n# 请给出裁判回答\n{question}"},
            ],
            "max_tokens": 1500,
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        resp = self._post(url, headers, payload)
        try:
            return resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

    # ---------- Anthropic 原生 ----------

    def _anthropic_judge(self, question: str, facts: str) -> Optional[str]:
        client = self._client
        if client is None:
            try:
                import anthropic
            except ImportError as e:
                raise RuntimeError("需先安装 anthropic：pip install anthropic") from e
            client = anthropic.Anthropic(api_key=self.api_key)
            self._client = client
        msg = client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"{facts}\n\n# 请给出裁判回答\n{question}"}],
        )
        parts = []
        for block in getattr(msg, "content", []):
            if getattr(block, "text", None):
                parts.append(block.text)
        return "\n".join(parts) if parts else None
