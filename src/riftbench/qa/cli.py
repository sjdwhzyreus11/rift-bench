"""规则问答 CLI（qa/cli.py）— 交互式裁判问答。

用法:
  python -m riftbench.qa.cli
  # 启用 LLM 裁判模式（推荐）:
  #   pip install anthropic
  #   export ANTHROPIC_API_KEY=sk-ant-...
  #   python -m riftbench.qa.cli

无 key 时走"结构化裁判回退"（卡牌原文 + 效果结构 + 引擎流程 + 规则依据）。
"""
from __future__ import annotations

import re

from riftbench.qa.agent import RiftboundQA


def _parse_decklist(line: str) -> list[tuple[str, int]]:
    body = line.split("构筑", 1)[1] if "构筑" in line else line
    deck = []
    for part in body.split(","):
        part = part.strip()
        m = re.match(r"(.+?)\s*x\s*(\d+)", part)
        if m:
            deck.append((m.group(1).strip(), int(m.group(2))))
    return deck


def main() -> None:
    qa = RiftboundQA()
    print(f"rift-bench 规则问答智能体 · LLM 裁判层：[{qa.llm.describe()}]")
    if not qa.llm.is_configured:
        print("  启用 LLM 裁判：编辑 config/llm.json 填入 api_key（base_url/model 已预填 DeepSeek）")
        print("  一次填写，之后默认 LLM 裁判模式（建议：DEEPSEEK/通义/Kimi/智谱/本地Ollama 均可，见 config/llm.example.json）")
    print("输入 q 退出。可问复杂判例，如：")
    print("  · 对方用 Reaction 响应时结算链怎么结算")
    print("  · Adap 的效果按什么顺序执行")
    print("  · 构筑 Abandon x3, Adaptatron x2")
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.lower() in ("q", "quit", "exit"):
            break
        decklist = _parse_decklist(line) if ("构筑" in line or "牌表" in line) else None
        r = qa.answer(line, decklist)
        print(r["answer"])
        if r.get("citations"):
            print(f"  引用规则: {', '.join(str(c) for c in r['citations'][:6])}")


if __name__ == "__main__":
    main()
