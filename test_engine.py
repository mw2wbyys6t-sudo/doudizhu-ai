# -*- coding: utf-8 -*-
"""斗地主引擎压力测试: 用启发式 AI 自动打完整局, 检查规则合法性与终止性。"""

import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from game.ai import heuristic_bid, heuristic_play, hand_power_cached
from game.cards import TYPE_NAMES, cards_text, find_cards_in_hand, parse, ranks_of
from game.engine import PHASE_BID, PHASE_OVER, PHASE_PLAY, SEAT_NAMES_AI, Game


def play_one(seed: int, verbose: bool = False):
    g = Game(seed=seed)
    steps = 0
    while g.phase != PHASE_OVER:
        steps += 1
        if steps > 800:
            raise RuntimeError("对局未能在 800 步内结束, 可能死循环")

        seat = g.current
        if g.phase == PHASE_BID:
            legal = g.legal_bids(seat)
            ctx = g.ai_context(seat)
            v = heuristic_bid(hand_power_cached(ctx["hand"]), legal)
            assert v in legal, f"非法叫分 {v} not in {legal}"
            ok = g.do_bid(seat, v)
            assert ok, f"叫分被拒绝 seat={seat} v={v}"
        else:
            moves = g.legal_moves(seat)
            hand_count = len(g.hands[seat])
            is_leader = g.must_play(seat)
            if is_leader:
                assert moves, f"先手却无合法出牌! hand={cards_text(g.hands[seat])}"
            last = g.last_play
            last_team = False
            last_cnt = 99
            if last is not None and not is_leader:
                last_team = ((last["seat"] == g.landlord) == (seat == g.landlord))
                last_cnt = len(g.hands[last["seat"]])
            idx = heuristic_play(moves, hand_count, is_leader,
                                 last_by_teammate=last_team,
                                 last_player_count=last_cnt)
            if idx < 0:
                assert not is_leader, "先手不能过牌"
                ok = g.do_play(seat, None)
                assert ok, "过牌被拒绝"
            else:
                cards = find_cards_in_hand(g.hands[seat], moves[idx]["ranks"])
                assert cards is not None, "手牌不足以组成该出牌"
                # 再独立校验一次牌型与大小
                p = parse(ranks_of(cards))
                assert p is not None, f"非法牌型 {cards}"
                if last is not None and last["seat"] != seat:
                    from game.cards import can_beat
                    assert can_beat(p, last["parsed"]), f"管不住却出了: {cards}"
                ok = g.do_play(seat, cards)
                assert ok, f"出牌被拒绝 seat={seat} cards={cards}"

    # 结算校验: 剩余手牌 + 已打出牌 = 54 张
    played = sum(len(h["cards"]) for h in g.history if not h.get("pass"))
    total = sum(len(h) for h in g.hands) + played
    assert total == 54, f"牌数不守恒: 剩余{sum(len(h) for h in g.hands)} + 已出{played} = {total}"
    assert g.winner is not None
    assert g.phase == PHASE_OVER
    return g


def main():
    n = 500
    t0 = time.time()
    winner_seat = Counter()
    landlord_wins = 0
    springs = 0
    redeals = 0
    max_steps = 0
    for i in range(n):
        g = play_one(seed=i)
        winner_seat[g.winner] += 1
        if g.winner == g.landlord:
            landlord_wins += 1
        springs += 1 if getattr(g, "spring", False) else 0
        redeals += g.redeal_count
        assert sum(g.delta) == 0, f"分数不守恒: {g.delta}"
    dt = time.time() - t0
    print(f"完成 {n} 局, 耗时 {dt:.2f}s ({dt/n*1000:.1f} ms/局)")
    print(f"地主胜率 : {landlord_wins}/{n} = {landlord_wins/n*100:.1f}%   (真实斗地主约 45~55%)")
    print(f"春天局数 : {springs} ({springs/n*100:.1f}%)   (正常应 < 8%)")
    print(f"重新发牌 : {redeals} 次 ({redeals/n:.2f} 次/局)   (正常约 0.1~0.4)")
    print("各家获胜 :", {SEAT_NAMES_AI[k]: v for k, v in sorted(winner_seat.items())})

    # 展示一局示例
    print("\n=== 示例对局 ===")
    g = play_one(seed=7)
    for e in g.log:
        print("  ", e["text"])
    print("   结算:", g.delta, "胜者:", SEAT_NAMES_AI[g.winner])
    print("\nALL PASSED")


if __name__ == "__main__":
    main()
