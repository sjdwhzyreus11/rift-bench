"""初始布置（规则 110-118, 485.4-485.7）。

流程:
  110-118: 传奇放传奇区(111) → 选定英雄放英雄区(112) → 战场先置一旁(113)，
           1v1 下每玩家从3张战场候选随机选1张同时放入战场区(485.4-485.5) →
           主牌堆/符文牌堆各自洗混放入对应区域(114) → 随机定先手(115.1)，
           回合队列从先手开始 → 各抽4张(116) → 按回合顺序 mulligan(117) →
           后手玩家标记首召出阶段+1符文(485.7) → 先手开始第一回合(118)。

Deck 输入: 主牌堆(40+ internal_id 列表)、符文牌堆(12)、传奇(1)、选定英雄(1)、
          战场候选(3)。由调用方从 CardDatabase 构造。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from riftbench.cards import Card, CardDatabase
from riftbench.cards.model import CardType, SuperType
from riftbench.engine.model import (
    BattlefieldState,
    ControlStatus,
    GameObject,
    Phase,
    Player,
    PlayerId,
    Privacy,
    RunePool,
    TurnState,
    Zone,
    ZoneType,
    readiness,
)
from riftbench.engine.state import GameState


@dataclass
class Deck:
    """一套卡组（构筑校验由单独模块负责，此处只承载输入）。"""
    main_deck: list[str] = field(default_factory=list)      # internal_id 列表，40+
    rune_deck: list[str] = field(default_factory=list)      # 12
    legend: str = ""                                        # 1
    chosen_champion: str = ""                               # 1
    battlefield_candidates: list[str] = field(default_factory=list)  # 3

    def validate_counts(self) -> None:
        assert len(self.main_deck) >= 40, f"主牌堆需 ≥40，实得 {len(self.main_deck)}"
        assert len(self.rune_deck) == 12, f"符文牌堆需 12，实得 {len(self.rune_deck)}"
        assert self.legend, "缺传奇"
        assert self.chosen_champion, "缺选定英雄"
        assert len(self.battlefield_candidates) == 3, "需 3 张战场候选"


def _make_zone(zt: ZoneType, owner: PlayerId | None, privacy: Privacy,
               capacity: int | None = None, location_id: str | None = None) -> Zone:
    return Zone(zone_type=zt, owner=owner, privacy=privacy,
                capacity=capacity, location_id=location_id)


def _init_zones(pid: PlayerId, base_location_id: str) -> dict[ZoneType, Zone]:
    """为一名玩家初始化所有区域（规则 107-108 隐私等级）。"""
    return {
        ZoneType.HAND: _make_zone(ZoneType.HAND, pid, Privacy.PRIVATE),
        ZoneType.MAIN_DECK: _make_zone(ZoneType.MAIN_DECK, pid, Privacy.SECRET),
        ZoneType.RUNE_DECK: _make_zone(ZoneType.RUNE_DECK, pid, Privacy.SECRET),
        ZoneType.TRASH: _make_zone(ZoneType.TRASH, pid, Privacy.PUBLIC),
        ZoneType.BANISHMENT: _make_zone(ZoneType.BANISHMENT, pid, Privacy.PUBLIC),
        ZoneType.CHAMPION: _make_zone(ZoneType.CHAMPION, pid, Privacy.PUBLIC),
        ZoneType.LEGEND: _make_zone(ZoneType.LEGEND, pid, Privacy.PUBLIC),
        ZoneType.BASE: _make_zone(ZoneType.BASE, pid, Privacy.PUBLIC, location_id=base_location_id),
        # CHAIN 是共享区域，不在每玩家下；BATTLEFIELD_ZONE 共享
    }


def setup_game(deck_north: Deck, deck_south: Deck, db: CardDatabase,
               seed: int | None = None) -> GameState:
    """布置一局 1v1 对局，返回初始 GameState。"""
    deck_north.validate_counts()
    deck_south.validate_counts()
    rng = random.Random(seed)

    state = GameState(rng=rng)
    state.victory_score = 8  # 485.3

    # 玩家
    p_north = Player(player_id=PlayerId.NORTH)
    p_south = Player(player_id=PlayerId.SOUTH)
    state.players[PlayerId.NORTH] = p_north
    state.players[PlayerId.SOUTH] = p_south

    # 区域
    base_n = "base:north"
    base_s = "base:south"
    state.zones[PlayerId.NORTH] = _init_zones(PlayerId.NORTH, base_n)
    state.zones[PlayerId.SOUTH] = _init_zones(PlayerId.SOUTH, base_s)

    decks = {PlayerId.NORTH: deck_north, PlayerId.SOUTH: deck_south}
    bases = {PlayerId.NORTH: base_n, PlayerId.SOUTH: base_s}

    # 111/112: 传奇放传奇区、选定英雄放英雄区
    for pid, deck in decks.items():
        # 传奇
        legend_card = db.get(deck.legend)
        assert legend_card and legend_card.static.is_unit is False or True  # 传奇是 legend 类型
        rid = state.new_runtime_id()
        g = GameObject.from_card(rid, legend_card, pid, pid, ZoneType.LEGEND)
        g.readiness = readiness.READY  # 传奇区不可移除，始终"就绪"概念
        state.add_object(g)
        # 选定英雄
        champ_card = db.get(deck.chosen_champion)
        assert champ_card, f"选定英雄 {deck.chosen_champion} 不在卡库"
        rid2 = state.new_runtime_id()
        g2 = GameObject.from_card(rid2, champ_card, pid, pid, ZoneType.CHAMPION)
        g2.readiness = readiness.READY
        state.add_object(g2)

    # 485.4-485.5: 每玩家从3张战场候选随机选1张，同时放入战场区
    bf_choices = {}
    for pid, deck in decks.items():
        assert len(deck.battlefield_candidates) == 3
        chosen = rng.choice(deck.battlefield_candidates)
        bf_choices[pid] = chosen
    # 两个战场放入共享战场区（每个战场是该玩家的战场；初始 OPEN 未被据守）
    for pid in (PlayerId.NORTH, PlayerId.SOUTH):
        bf_card = db.get(bf_choices[pid])
        assert bf_card, f"战场 {bf_choices[pid]} 不在卡库"
        bf_loc = f"bf:{pid.value}"
        rid = state.new_runtime_id()
        g = GameObject.from_card(rid, bf_card, pid, pid, ZoneType.BATTLEFIELD, location_id=bf_loc)
        g.readiness = readiness.READY  # 战场不可横置/移动
        # 战场卡本身放入对应战场的共享 Zone
        from riftbench.engine.model import Privacy
        state.battlefield_zones[bf_loc] = Zone(zone_type=ZoneType.BATTLEFIELD, owner=None,
                                               privacy=Privacy.PUBLIC, location_id=bf_loc)
        state.add_object(g)  # zone=BATTLEFIELD, location_id=bf_loc -> 存入 battlefield_zones[bf_loc]
        state.battlefields[bf_loc] = BattlefieldState(
            location_id=bf_loc,
            card_internal_id=bf_card.static.internal_id,
            name=bf_card.static.name,
            controller=None,
            status=ControlStatus.OPEN,
        )
        state.battlefield_order.append(bf_loc)

    # 114: 主牌堆/符文牌堆各自洗混
    for pid, deck in decks.items():
        main_shuffled = list(deck.main_deck)
        rng.shuffle(main_shuffled)
        for iid in main_shuffled:
            card = db.get(iid)
            assert card, f"卡 {iid} 不在卡库"
            rid = state.new_runtime_id()
            g = GameObject.from_card(rid, card, pid, pid, ZoneType.MAIN_DECK)
            state.add_object(g)
        rune_shuffled = list(deck.rune_deck)
        rng.shuffle(rune_shuffled)
        for iid in rune_shuffled:
            card = db.get(iid)
            assert card, f"符文 {iid} 不在卡库"
            rid = state.new_runtime_id()
            g = GameObject.from_card(rid, card, pid, pid, ZoneType.RUNE_DECK)
            state.add_object(g)

    # 115.1: 随机定先手。1v1 无需 opponent_of（turn_order 尚未设置）。
    first = rng.choice([PlayerId.NORTH, PlayerId.SOUTH])
    second = (PlayerId.SOUTH if first == PlayerId.NORTH else PlayerId.NORTH)
    # 设置回合队列从先手开始
    state.turn_order = [first, second]
    state.turn_player_index = 0
    state.players[first].is_first = True
    # 485.7: 后手玩家首召出阶段额外 channel 1
    state.players[second].extra_channel_first_turn = True
    state.is_first_turn_of_game = True

    # 116: 各抽 4 张
    for pid in state.turn_order:  # 按回合顺序
        _draw_cards(state, pid, 4)

    # 117: 按回合顺序 mulligan——MVP 简化：agent 决策由 driver 处理；setup 默认不调度
    # （mulligan 是玩家选择，留给 driver/agent 在对局开始前调用 mulligan()）
    # 此处不强制调度，保持手牌为初始4张。

    # 初始回合状态
    state.phase = Phase.AWAKEN
    state.turn_state = TurnState.NORMAL_OPEN
    state.turn_number = 1

    return state


def _draw_cards(state: GameState, pid: PlayerId, n: int) -> list[GameObject]:
    """从主牌堆顶抽 n 张到手牌。MVP: 牌堆空不触发燃尽（燃尽在 turn.draw_phase 处理）。"""
    drawn = []
    main_zone = state.zones[pid][ZoneType.MAIN_DECK]
    for _ in range(n):
        if not main_zone.objects:
            break
        rid = main_zone.objects[-1]  # 顶 = 列表末尾
        obj = state.objects[rid]
        # 移到手牌
        state.move_object(rid, ZoneType.HAND, pid, None)
        drawn.append(obj)
    return drawn


def draw_cards(state: GameState, pid: PlayerId, n: int) -> list[GameObject]:
    """公开 API：从主牌堆抽 n 张到手牌（供 turn/agent 调用）。"""
    return _draw_cards(state, pid, n)


def mulligan(state: GameState, pid: PlayerId, set_aside_runtime_ids: list[int]) -> None:
    """调度（规则 117）：把至多2张手牌放一边→补抽同等→放一边的牌回收进牌堆底。

    set_aside_runtime_ids: 玩家选择放一边的手牌物体 id 列表（≤2）。
    回收 = 放入主牌堆底（列表头部），规则 416 Recycle。
    """
    assert len(set_aside_runtime_ids) <= 2, "mulligan 至多放2张"
    # 放一边（移到一个临时状态——MVP 直接移到 main_deck 底）
    main_zone = state.zones[pid][ZoneType.MAIN_DECK]
    n = len(set_aside_runtime_ids)
    # 补抽同等数量（先抽，再放底，避免顺序冲突）
    _draw_cards(state, pid, n)
    for rid in set_aside_runtime_ids:
        obj = state.objects.get(rid)
        assert obj and obj.zone == ZoneType.HAND, f"{rid} 不在手牌"
        # 回收进主牌堆底（列表头部）
        state.move_object(rid, ZoneType.MAIN_DECK, pid, None)
        main_zone.objects.remove(rid)
        main_zone.objects.insert(0, rid)  # 底 = 列表头部
