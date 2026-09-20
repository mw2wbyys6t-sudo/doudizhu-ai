# -*- coding: utf-8 -*-
"""
斗地主游戏状态机
================

三人局: 0 号座位为人类玩家, 1 号(下家/右) 与 2 号(上家/左) 为 AI。
出牌顺序 0 -> 1 -> 2 -> 0。

叫分规则 (叫地主):
    按随机顺序依次询问, 可选 不叫(0) / 1分 / 2分 / 3分;
    叫 3 分立即成为地主; 否则三人叫完后最高分者为地主, 底分 = 最高叫分;
    三人都不叫则重新发牌。
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Dict, List, Optional, Sequence

from .cards import (
    BOMB, PASS, ROCKET, TYPE_NAMES,
    all_plays, can_beat, card_label, card_rank, card_suit, cards_text,
    find_cards_in_hand, make_deck, parse, play_text, ranks_of,
)

PHASE_BID = "bid"
PHASE_PLAY = "play"
PHASE_OVER = "over"

SEAT_NAMES = ["你", "下家", "上家"]
SEAT_NAMES_AI = ["你", "电脑·小美", "电脑·老张"]

MAX_REDEAL = 6


class Game:
    def __init__(self, human_index: int = 0, seed: Optional[int] = None, stake: int = 1):
        self.rng = random.Random(seed)
        self.human = human_index
        self.stake = max(1, int(stake))          # 底注(token), 输赢 = 底注 x 叫分 x 倍数
        self.redeal_count = 0
        self.log: List[Dict] = []
        self._new_round()

    # ------------------------------------------------------------ 发牌

    def _new_round(self) -> None:
        deck = make_deck()
        self.rng.shuffle(deck)
        self.hands: List[List[str]] = [
            sorted(deck[0:17], key=lambda c: (card_rank(c), card_suit(c))),
            sorted(deck[17:34], key=lambda c: (card_rank(c), card_suit(c))),
            sorted(deck[34:51], key=lambda c: (card_rank(c), card_suit(c))),
        ]
        self.bottom: List[str] = sorted(deck[51:54], key=lambda c: (card_rank(c), card_suit(c)))

        self.phase = PHASE_BID
        self.landlord: Optional[int] = None
        self.winner: Optional[int] = None
        self.base_score = 1
        self.multiplier = 1
        self.bombs_played = 0

        # 叫分
        start = self.rng.randrange(3)
        self.bid_order = [(start + i) % 3 for i in range(3)]
        self.bid_index = 0
        self.bids: Dict[int, int] = {}
        self.highest_bid = 0
        self.highest_bidder: Optional[int] = None
        self.current = self.bid_order[0]

        # 出牌
        self.last_play: Optional[Dict] = None      # 全场上一手有效出牌
        self.round_plays: Dict[int, Dict] = {}     # 本圈各家出的牌
        self.pass_count = 0
        self.played_count: Dict[int, int] = {0: 0, 1: 0, 2: 0}
        self.turn_no = 0
        self.history: List[Dict] = []

    # ------------------------------------------------------------ 工具

    @property
    def round_leader(self) -> Optional[int]:
        return self.last_play["seat"] if self.last_play else None

    def is_ai(self, seat: int) -> bool:
        return seat != self.human

    def _log(self, kind: str, text: str, seat: Optional[int] = None) -> None:
        self.log.append({"kind": kind, "text": text, "seat": seat})
        if len(self.log) > 200:
            self.log = self.log[-200:]

    # ------------------------------------------------------------ 叫分

    def legal_bids(self, seat: int) -> List[int]:
        """当前座位可选的叫分值。"""
        if self.phase != PHASE_BID or seat != self.current:
            return []
        opts = [0]
        for v in range(max(self.highest_bid + 1, 1), 4):
            opts.append(v)
        return opts

    def do_bid(self, seat: int, value: int) -> bool:
        if self.phase != PHASE_BID or seat != self.current:
            return False
        if value not in self.legal_bids(seat):
            return False

        self.bids[seat] = value
        if value > self.highest_bid:
            self.highest_bid = value
            self.highest_bidder = seat

        who = SEAT_NAMES_AI[seat]
        self._log("bid", f"{who} {'不叫' if value == 0 else f'叫 {value} 分'}", seat)

        if value == 3:
            return self._finish_bidding()

        self.bid_index += 1
        if self.bid_index >= 3:
            return self._finish_bidding()

        self.current = self.bid_order[self.bid_index]
        return True

    def _finish_bidding(self) -> bool:
        if self.highest_bidder is None:
            self.redeal_count += 1
            if self.redeal_count >= MAX_REDEAL:
                # 兜底: 随机指定地主
                self.highest_bidder = self.bid_order[0]
                self.highest_bid = 1
            else:
                self._log("system", "三家都不叫, 重新发牌")
                self._new_round()
                return True

        self.landlord = self.highest_bidder
        self.base_score = max(1, self.highest_bid)
        self.hands[self.landlord] = sorted(
            self.hands[self.landlord] + self.bottom,
            key=lambda c: (card_rank(c), card_suit(c)),
        )
        self.phase = PHASE_PLAY
        self.current = self.landlord
        self.turn_no = 0

        tag = "地主" if self.landlord == self.human else "地主"
        self._log("system", f"【{SEAT_NAMES_AI[self.landlord]}】成为{tag}, 底分 {self.base_score} 分")
        return True

    # ------------------------------------------------------------ 出牌

    def must_play(self, seat: int) -> bool:
        """该座位是否必须出牌(自由出牌, 不能过)。"""
        return self.last_play is None or self.last_play["seat"] == seat

    def legal_moves(self, seat: int) -> List[Dict]:
        if self.phase != PHASE_PLAY or seat != self.current:
            return []
        last = None
        if self.last_play is not None and self.last_play["seat"] != seat:
            last = self.last_play["parsed"]
        return all_plays(self.hands[seat], last)

    def do_play(self, seat: int, card_ids: Optional[Sequence[str]]) -> bool:
        """
        出牌。card_ids 为 None 表示不要。
        """
        if self.phase != PHASE_PLAY or seat != self.current:
            return False

        hand = self.hands[seat]

        # ---- 不要 ----
        if card_ids is None or len(card_ids) == 0:
            if self.must_play(seat):
                return False
            self.pass_count += 1
            self.round_plays[seat] = {"pass": True}
            self.history.append({"seat": seat, "pass": True})
            self._log("play", f"{SEAT_NAMES_AI[seat]} 不要", seat)

            if self.pass_count >= 2:
                self.last_play = None
                self.round_plays = {}
                self.pass_count = 0
            self._advance()
            return True

        # ---- 校验牌是否在手里 ----
        cards = list(card_ids)
        if len(set(cards)) != len(cards):
            return False
        if Counter(cards) - Counter(hand):
            return False

        ranks = ranks_of(cards)
        parsed = parse(ranks)
        if parsed is None:
            return False

        last = None
        if self.last_play is not None and self.last_play["seat"] != seat:
            last = self.last_play["parsed"]
        if not can_beat(parsed, last):
            return False

        # ---- 生效 ----
        for cid in cards:
            hand.remove(cid)
        self.pass_count = 0

        info = {
            "seat": seat,
            "pass": False,
            "cards": sorted(cards, key=lambda c: (card_rank(c), card_suit(c))),
            "ranks": sorted(ranks),
            "type": parsed[0],
            "type_name": TYPE_NAMES[parsed[0]],
            "rank": parsed[1],
            "length": parsed[2],
            "text": play_text(ranks),
            "parsed": parsed,
        }
        self.last_play = info
        self.round_plays[seat] = info
        self.history.append({"seat": seat, "pass": False, "cards": info["cards"]})
        self.played_count[seat] += 1
        self.turn_no += 1

        if parsed[0] in (BOMB, ROCKET):
            self.bombs_played += 1
            self.multiplier *= 2
            self._log("bomb", f"{SEAT_NAMES_AI[seat]} 放了个{'王炸' if parsed[0] == ROCKET else '炸弹'}! 倍数 x{self.multiplier}", seat)
        else:
            self._log("play", f"{SEAT_NAMES_AI[seat]} 出 {info['text']}", seat)

        if len(hand) == 0:
            self._settle(seat)
            return True

        if len(hand) <= 2:
            self._log("warn", f"{SEAT_NAMES_AI[seat]} 只剩 {len(hand)} 张牌了!", seat)

        self._advance()
        return True

    def _advance(self) -> None:
        self.current = (self.current + 1) % 3

    # ------------------------------------------------------------ 结算

    def _settle(self, winner: int) -> None:
        self.phase = PHASE_OVER
        self.winner = winner
        landlord_win = (winner == self.landlord)

        # 春天 / 反春天
        spring = False
        if landlord_win:
            farmers = [s for s in range(3) if s != self.landlord]
            if all(self.played_count[s] == 0 for s in farmers):
                spring = True
                self.multiplier *= 2
        else:
            if self.played_count[self.landlord] <= 1:
                spring = True
                self.multiplier *= 2

        score = self.stake * self.base_score * self.multiplier
        delta = [0, 0, 0]
        if landlord_win:
            delta[self.landlord] = 2 * score
            for s in range(3):
                if s != self.landlord:
                    delta[s] = -score
        else:
            delta[self.landlord] = -2 * score
            for s in range(3):
                if s != self.landlord:
                    delta[s] = score

        self.delta = delta
        self.spring = spring
        self.final_score = score

        if spring:
            self._log("system", "春天! 倍数翻倍")
        self._log("system",
                  f"{SEAT_NAMES_AI[winner]} 先出完牌, "
                  f"{'地主' if landlord_win else '农民'}获胜! "
                  f"底注 {self.stake} x 叫分 {self.base_score} x 倍数 {self.multiplier} = {score} token")

    # ------------------------------------------------------------ 序列化

    def hand_state(self, seat: int) -> List[Dict]:
        return [
            {
                "id": c,
                "rank": card_rank(c),
                "suit": card_suit(c),
                "label": card_label(c),
            }
            for c in self.hands[seat]
        ]

    @staticmethod
    def _public_cards(cards: Sequence[str]) -> List[Dict]:
        return [
            {"id": c, "rank": card_rank(c), "suit": card_suit(c), "label": card_label(c)}
            for c in sorted(cards, key=lambda x: (card_rank(x), card_suit(x)))
        ]

    def state(self, viewer: int) -> Dict:
        last_public = None
        if self.last_play is not None:
            last_public = {
                "seat": self.last_play["seat"],
                "cards": self._public_cards(self.last_play["cards"]),
                "type_name": self.last_play["type_name"],
                "text": self.last_play["text"],
            }

        round_plays = {}
        for s, v in self.round_plays.items():
            if v.get("pass"):
                round_plays[str(s)] = {"pass": True}
            else:
                round_plays[str(s)] = {
                    "pass": False,
                    "cards": self._public_cards(v["cards"]),
                    "type_name": v["type_name"],
                }

        return {
            "phase": self.phase,
            "viewer": viewer,
            "hand": self.hand_state(viewer),
            "counts": [len(h) for h in self.hands],
            "current": self.current,
            "landlord": self.landlord,
            "bottom": self._public_cards(self.bottom) if self.landlord is not None else [],
            "last_play": last_public,
            "round_plays": round_plays,
            "must_play": self.must_play(viewer) if self.phase == PHASE_PLAY else True,
            "legal_moves": [
                {k: v for k, v in m.items() if k != "ranks"} | {"ranks": m["ranks"]}
                for m in self.legal_moves(viewer)
            ],
            "bids": {str(k): v for k, v in self.bids.items()},
            "bid_current": self.current if self.phase == PHASE_BID else None,
            "legal_bids": self.legal_bids(viewer),
            "highest_bid": self.highest_bid,
            "base_score": self.base_score,
            "stake": self.stake,
            "multiplier": self.multiplier,
            "winner": self.winner,
            "delta": getattr(self, "delta", None),
            "spring": getattr(self, "spring", False),
            "final_score": getattr(self, "final_score", 0),
            "played_count": self.played_count,
            "is_my_turn": (self.current == viewer and self.phase in (PHASE_BID, PHASE_PLAY)),
            "log": self.log[-40:],
            "redeal_count": self.redeal_count,
        }

    # ------------------------------------------------------------ 给 AI 的局面描述

    def ai_context(self, seat: int) -> Dict:
        """构造给 AI 决策的精简局面信息。"""
        opponents = [s for s in range(3) if s != seat]
        last = None
        if self.last_play is not None and self.last_play["seat"] != seat:
            last = {
                "by": SEAT_NAMES_AI[self.last_play["seat"]],
                "text": self.last_play["text"],
                "type_name": self.last_play["type_name"],
                "count": len(self.last_play["cards"]),
                "is_landlord": self.last_play["seat"] == self.landlord,
            }

        role = "地主" if seat == self.landlord else "农民"
        opp_role = "农民" if seat == self.landlord else "地主"
        return {
            "seat": seat,
            "role": role,
            "opp_role": opp_role,
            "hand": cards_text(self.hands[seat]),
            "hand_count": len(self.hands[seat]),
            "counts": {SEAT_NAMES_AI[s]: len(self.hands[s]) for s in range(3)},
            "landlord": SEAT_NAMES_AI[self.landlord] if self.landlord is not None else None,
            "landlord_is_me": seat == self.landlord,
            "opponents": [SEAT_NAMES_AI[s] for s in opponents],
            "last": last,
            "is_leader": self.must_play(seat),
        }
