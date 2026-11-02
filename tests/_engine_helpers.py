"""测试共用助手：构造引擎测试用的小型合法卡组与对局。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from riftbench.cards import CardDatabase, CardType
from riftbench.engine.agents.random import RandomAgent
from riftbench.engine.driver import run_game
from riftbench.engine.setup import Deck, setup_game

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "cards" / "cards.json"
DB = CardDatabase.load(DATA_PATH) if DATA_PATH.exists() else None


def _cards(set_id: str, ctype: CardType):
    return [c for c in DB.cards if not c.is_variant and c.static.set_id.value == set_id
            and ctype in c.static.types]


def make_deck(set_id: str = "OGN", main_units: int = 20, main_spells: int = 20) -> Deck:
    """构造一个小型合法卡组。符文用基础符文重复填满12（符文牌堆无同名限制）。
    传奇/英雄/战场各取首个可用。"""
    units = _cards(set_id, CardType.UNIT)
    spells = _cards(set_id, CardType.SPELL)
    runes = _cards(set_id, CardType.RUNE) or _cards("OGN", CardType.RUNE)
    legends = _cards(set_id, CardType.LEGEND)
    bfs = _cards(set_id, CardType.BATTLEFIELD)
    # champion 超类型
    champs = [c for c in DB.cards if not c.is_variant
              and any(s.value == "champion" for s in c.static.super_types)]
    assert units and spells and runes and legends and bfs and champs, f"set {set_id} 卡池不足"

    main = [c.static.internal_id for c in (units[:main_units] + spells[:main_spells])]
    # 配 40 张：不足则扩充或复用
    while len(main) < 40:
        main.append(main[len(main) % len(main)])
    rune_ids = ([r.static.internal_id for r in runes] * 6)[:12]
    return Deck(
        main_deck=main,
        rune_deck=rune_ids,
        legend=legends[0].static.internal_id,
        chosen_champion=champs[0].static.internal_id,
        battlefield_candidates=[b.static.internal_id for b in bfs[:3]],
    )


def make_two_decks() -> tuple[Deck, Deck]:
    n = make_deck("OGN")
    s = make_deck("SFD")
    return n, s


def make_state(seed: int | None = 42):
    n, s = make_two_decks()
    return setup_game(n, s, DB, seed=seed)


def run_small_game(seed: int = 42, max_steps: int = 3000):
    n, s = make_two_decks()
    return run_game(RandomAgent(seed=1), RandomAgent(seed=2), n, s, DB,
                    seed=seed, max_steps=max_steps)