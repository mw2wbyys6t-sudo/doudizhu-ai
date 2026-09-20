# -*- coding: utf-8 -*-
"""
斗地主核心牌型引擎
==================

纯 Python 实现, 无第三方依赖。

牌值编码 (rank):
    3..10 -> 3..10
    J=11, Q=12, K=13, A=14, 2=15
    小王 = 16, 大王 = 17

牌 id 编码:  "<rank>-<suit>"
    suit: 0=黑桃 1=红桃 2=梅花 3=方块;  大小王固定 suit=0
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- 牌型常量

PASS = 0
SINGLE = 1
PAIR = 2
TRIO = 3
TRIO_SINGLE = 4
TRIO_PAIR = 5
STRAIGHT = 6
STRAIGHT_PAIR = 7
PLANE = 8
PLANE_SINGLE = 9
PLANE_PAIR = 10
FOUR_TWO_SINGLE = 11
FOUR_TWO_PAIR = 12
BOMB = 13
ROCKET = 14

TYPE_NAMES: Dict[int, str] = {
    PASS: "不要",
    SINGLE: "单张",
    PAIR: "对子",
    TRIO: "三张",
    TRIO_SINGLE: "三带一",
    TRIO_PAIR: "三带二",
    STRAIGHT: "顺子",
    STRAIGHT_PAIR: "连对",
    PLANE: "飞机",
    PLANE_SINGLE: "飞机带单",
    PLANE_PAIR: "飞机带对",
    FOUR_TWO_SINGLE: "四带二",
    FOUR_TWO_PAIR: "四带两对",
    BOMB: "炸弹",
    ROCKET: "王炸",
}

SUIT_SYMBOLS = ["♠", "♥", "♣", "♦"]
RANK_LABELS: Dict[int, str] = {
    3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
    11: "J", 12: "Q", 13: "K", 14: "A", 15: "2", 16: "小王", 17: "大王",
}
# 紧凑写法(给模型看)
RANK_SHORT: Dict[int, str] = {
    3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
    11: "J", 12: "Q", 13: "K", 14: "A", 15: "2", 16: "w", 17: "W",
}
SHORT_TO_RANK: Dict[str, int] = {v: k for k, v in RANK_SHORT.items()}

# 顺子/连对/飞机 允许的最大牌值 (A), 不含 2 和王
CHAIN_MAX = 14


# ---------------------------------------------------------------- 牌堆

def make_deck() -> List[str]:
    """生成一副 54 张牌的 id 列表。"""
    deck: List[str] = []
    for rank in range(3, 16):          # 3 .. 2
        for suit in range(4):
            deck.append(f"{rank}-{suit}")
    deck.append("16-0")                # 小王
    deck.append("17-0")                # 大王
    return deck


def card_rank(card_id: str) -> int:
    return int(card_id.split("-")[0])


def card_suit(card_id: str) -> int:
    return int(card_id.split("-")[1])


def ranks_of(cards: Iterable[str]) -> List[int]:
    return [card_rank(c) for c in cards]


def card_label(card_id: str) -> str:
    return RANK_LABELS[card_rank(card_id)]


def cards_text(cards: Sequence[str]) -> str:
    """把一手牌渲染成紧凑字符串, 例如 '5 5 Q Q Q'。用于给模型展示。"""
    rs = sorted(ranks_of(cards))
    return " ".join(RANK_SHORT[r] for r in rs)


# ---------------------------------------------------------------- 牌型识别

def _consec_segments(vals: Sequence[int]) -> List[List[int]]:
    """把有序去重后的牌值切成若干连续段。"""
    out: List[List[int]] = []
    vs = sorted(set(vals))
    i = 0
    while i < len(vs):
        j = i
        while j + 1 < len(vs) and vs[j + 1] == vs[j] + 1:
            j += 1
        out.append(vs[i:j + 1])
        i = j + 1
    return out


def _trio_rank(cnt: Counter) -> Optional[int]:
    cands = [v for v, c in cnt.items() if c == 3]
    if len(cands) == 1:
        return cands[0]
    cands = [v for v, c in cnt.items() if c >= 3]
    return cands[0] if len(cands) == 1 else None


def parse(ranks: Sequence[int]) -> Optional[Tuple[int, int, int]]:
    """
    识别牌型。

    返回 (type, key_rank, length) 或 None (非法牌型)。
        key_rank : 用于比较大小的主牌值 (顺子取最大牌, 飞机取最大三张)
        length   : 链式牌型的"节数" (顺子=张数, 连对=对数, 飞机=三张组数)
    """
    n = len(ranks)
    if n == 0:
        return None

    cnt = Counter(ranks)
    vals = sorted(cnt)
    counts = sorted(cnt.values(), reverse=True)

    # 王炸
    if n == 2 and cnt.get(16, 0) == 1 and cnt.get(17, 0) == 1:
        return (ROCKET, 17, 1)

    if n == 1:
        return (SINGLE, vals[0], 1)

    if n == 2 and counts == [2]:
        return (PAIR, vals[0], 1)

    if n == 3 and counts == [3]:
        return (TRIO, vals[0], 1)

    if n == 4:
        if counts == [4]:
            return (BOMB, vals[0], 1)
        if counts == [3, 1]:
            t = _trio_rank(cnt)
            if t is not None:
                return (TRIO_SINGLE, t, 1)

    if n == 5 and counts == [3, 2]:
        t = _trio_rank(cnt)
        if t is not None:
            return (TRIO_PAIR, t, 1)

    # 顺子: 至少 5 张, 全部单张, 连续, 最大不超过 A
    if n >= 5 and len(vals) == n and vals[-1] <= CHAIN_MAX and vals[-1] - vals[0] == n - 1:
        return (STRAIGHT, vals[-1], n)

    # 连对: 至少 3 对, 连续
    if (n >= 6 and n % 2 == 0 and len(vals) == n // 2
            and all(cnt[v] == 2 for v in vals)
            and vals[-1] <= CHAIN_MAX and vals[-1] - vals[0] == len(vals) - 1):
        return (STRAIGHT_PAIR, vals[-1], len(vals))

    # 飞机系列
    trio_cands = [v for v in vals if cnt[v] >= 3 and v <= CHAIN_MAX]
    if trio_cands:
        for seg in _consec_segments(trio_cands):
            for k in range(len(seg), 1, -1):          # 三张组数, 越长越优先
                for s in range(0, len(seg) - k + 1):
                    chain = seg[s:s + k]
                    base: List[int] = []
                    for v in chain:
                        base += [v] * 3
                    rest = list(ranks)
                    for v in base:
                        rest.remove(v)
                    rn = len(rest)
                    if rn == 0 and n == 3 * k:
                        return (PLANE, chain[-1], k)
                    if rn == k and n == 4 * k:
                        return (PLANE_SINGLE, chain[-1], k)
                    if rn == 2 * k and n == 5 * k:
                        rc = Counter(rest)
                        if len(rc) == k and all(c == 2 for c in rc.values()):
                            return (PLANE_PAIR, chain[-1], k)

    # 四带二单
    if n == 6:
        for q in [v for v in vals if cnt[v] == 4]:
            rest = list(ranks)
            for _ in range(4):
                rest.remove(q)
            if len(rest) == 2:
                return (FOUR_TWO_SINGLE, q, 1)

    # 四带两对
    if n == 8:
        for q in [v for v in vals if cnt[v] == 4]:
            rest = list(ranks)
            for _ in range(4):
                rest.remove(q)
            rc = Counter(rest)
            if len(rc) == 2 and all(c == 2 for c in rc.values()):
                return (FOUR_TWO_PAIR, q, 1)

    return None


def can_beat(play: Optional[Tuple[int, int, int]],
             last: Optional[Tuple[int, int, int]]) -> bool:
    """判断 play 能否压过 last。last 为 None 或 PASS 时表示自由出牌。"""
    if play is None:
        return False
    if last is None or last[0] == PASS:
        return True

    pt, pr, pl = play
    lt, lr, ll = last

    if pt == ROCKET:
        return True
    if lt == ROCKET:
        return False
    if pt == BOMB:
        return lt != BOMB or pr > lr
    if lt == BOMB:
        return False
    return pt == lt and pl == ll and pr > lr


def is_bomb_type(ptype: int) -> bool:
    return ptype in (BOMB, ROCKET)


# ---------------------------------------------------------------- 出牌候选

def _pick_singles(cnt: Counter, exclude: set, k: int) -> Optional[List[int]]:
    """挑 k 张最"不心疼"的单牌: 牌值低、优先拆不开对子的散牌。"""
    pool = [(cnt[v], v) for v in sorted(cnt) if v not in exclude]
    pool.sort(key=lambda x: (x[0] != 1, x[1]))
    out: List[int] = []
    used: Counter = Counter()
    for c, v in pool:
        if len(out) >= k:
            break
        if used[v] < cnt[v]:
            out.append(v)
            used[v] += 1
    return out if len(out) == k else None


def _pick_pairs(cnt: Counter, exclude: set, k: int) -> Optional[List[int]]:
    """挑 k 个最不心疼的对子。"""
    pool = [(cnt[v], v) for v in sorted(cnt) if v not in exclude and cnt[v] >= 2]
    pool.sort(key=lambda x: (x[0] != 2, x[1]))
    if len(pool) < k:
        return None
    out: List[int] = []
    for _c, v in pool[:k]:
        out += [v, v]
    return out


def all_plays(hand: Sequence[str], last: Optional[Tuple[int, int, int]] = None
              ) -> List[Dict]:
    """
    枚举手牌中所有能压过 last 的合法出牌。

    相同 (牌型, 主牌值, 节数) 只保留最省牌的一组, 让候选列表精简可用。

    返回: [{"type":int,"type_name":str,"rank":int,"length":int,
            "ranks":[int,...],"text":str,"is_bomb":bool}, ...]
    """
    cnt = Counter(ranks_of(hand))
    vals = sorted(cnt)
    lt = last[0] if last else PASS
    lr = last[1] if last else 0
    ll = last[2] if last else 0

    res: Dict[Tuple[int, int, int], Tuple[int, List[int]]] = {}

    def put(ranks: List[int]) -> None:
        p = parse(ranks)
        if p is None or not can_beat(p, last):
            return
        key = p
        s = sum(ranks)
        prev = res.get(key)
        if prev is None or s < prev[0]:
            res[key] = (s, ranks)

    free = (lt == PASS)

    # --- 单张 / 对子 / 三张 ---
    if free or lt == SINGLE:
        for v in vals:
            if free or v > lr:
                put([v])
    if free or lt == PAIR:
        for v in vals:
            if cnt[v] >= 2 and (free or v > lr):
                put([v, v])
    if free or lt == TRIO:
        for v in vals:
            if cnt[v] >= 3 and (free or v > lr):
                put([v] * 3)

    # --- 三带一 / 三带二 ---
    if free or lt == TRIO_SINGLE:
        for v in vals:
            if cnt[v] >= 3 and (free or v > lr):
                att = _pick_singles(cnt, {v}, 1)
                if att:
                    put([v] * 3 + att)
    if free or lt == TRIO_PAIR:
        for v in vals:
            if cnt[v] >= 3 and (free or v > lr):
                att = _pick_pairs(cnt, {v}, 1)
                if att:
                    put([v] * 3 + att)

    # --- 顺子 ---
    if free or lt == STRAIGHT:
        cand = [v for v in vals if v <= CHAIN_MAX]
        for seg in _consec_segments(cand):
            for L in range(5, len(seg) + 1):
                if not free and L != ll:
                    continue
                for s in range(0, len(seg) - L + 1):
                    top = seg[s + L - 1]
                    if free or top > lr:
                        put(seg[s:s + L])

    # --- 连对 ---
    if free or lt == STRAIGHT_PAIR:
        cand = [v for v in vals if cnt[v] >= 2 and v <= CHAIN_MAX]
        for seg in _consec_segments(cand):
            for L in range(3, len(seg) + 1):
                if not free and L != ll:
                    continue
                for s in range(0, len(seg) - L + 1):
                    chain = seg[s:s + L]
                    if free or chain[-1] > lr:
                        put([v for v in chain for _ in range(2)])

    # --- 飞机 (不带 / 带单 / 带对) ---
    planes = [(free or lt == PLANE, PLANE),
              (free or lt == PLANE_SINGLE, PLANE_SINGLE),
              (free or lt == PLANE_PAIR, PLANE_PAIR)]
    for enabled, ptype in planes:
        if not enabled:
            continue
        cand = [v for v in vals if cnt[v] >= 3 and v <= CHAIN_MAX]
        for seg in _consec_segments(cand):
            for L in range(2, len(seg) + 1):
                if not free and L != ll:
                    continue
                for s in range(0, len(seg) - L + 1):
                    chain = seg[s:s + L]
                    if not free and chain[-1] <= lr:
                        continue
                    body = [v for v in chain for _ in range(3)]
                    if ptype == PLANE:
                        put(body)
                    elif ptype == PLANE_SINGLE:
                        att = _pick_singles(cnt, set(chain), L)
                        if att:
                            put(body + att)
                    else:
                        att = _pick_pairs(cnt, set(chain), L)
                        if att:
                            put(body + att)

    # --- 四带二 / 四带两对 ---
    if free or lt == FOUR_TWO_SINGLE:
        for v in vals:
            if cnt[v] == 4 and (free or v > lr):
                att = _pick_singles(cnt, {v}, 2)
                if att:
                    put([v] * 4 + att)
    if free or lt == FOUR_TWO_PAIR:
        for v in vals:
            if cnt[v] == 4 and (free or v > lr):
                att = _pick_pairs(cnt, {v}, 2)
                if att:
                    put([v] * 4 + att)

    # --- 炸弹 / 王炸 (永远可以出) ---
    for v in vals:
        if cnt[v] == 4:
            put([v] * 4)
    if cnt.get(16, 0) and cnt.get(17, 0):
        put([16, 17])

    out: List[Dict] = []
    for (ptype, prank, plen), (_s, ranks) in res.items():
        out.append({
            "type": ptype,
            "type_name": TYPE_NAMES[ptype],
            "rank": prank,
            "length": plen,
            "ranks": sorted(ranks),
            "text": cards_text([f"{r}-0" for r in ranks]),
            "is_bomb": is_bomb_type(ptype),
        })
    out.sort(key=lambda m: (m["is_bomb"], m["type"], m["rank"], m["length"]))
    return out


def play_text(ranks: Sequence[int]) -> str:
    return " ".join(RANK_SHORT[r] for r in sorted(ranks))


def find_cards_in_hand(hand: Sequence[str], ranks: Sequence[int]) -> Optional[List[str]]:
    """按牌值从手牌里挑出对应的实际牌 id (同值任取)。返回 None 表示手牌不够。"""
    need = Counter(ranks)
    picked: List[str] = []
    avail = Counter(ranks_of(hand))
    for r, c in need.items():
        if avail[r] < c:
            return None
    used: Counter = Counter()
    for cid in hand:
        r = card_rank(cid)
        if used[r] < need.get(r, 0):
            picked.append(cid)
            used[r] += 1
    return picked if len(picked) == len(ranks) else None


# ---------------------------------------------------------------- 手牌评估

def hand_power(hand: Sequence[str]) -> float:
    """
    粗略评估手牌强度 (0~100), 用于叫地主决策与兜底 AI。
    考虑: 大牌数量、炸弹、王、对子结构、牌型散乱度。
    """
    cnt = Counter(ranks_of(hand))
    score = 0.0

    if cnt.get(17, 0):
        score += 11
    if cnt.get(16, 0):
        score += 8
    if cnt.get(17, 0) and cnt.get(16, 0):
        score += 8          # 王炸加成

    for v, c in cnt.items():
        if c == 4:
            score += 12     # 炸弹
    score += cnt.get(15, 0) * 5          # 2
    score += cnt.get(14, 0) * 3.2        # A
    score += cnt.get(13, 0) * 2.0        # K

    # 顺子/连对潜力
    vals = sorted(v for v in cnt if v <= CHAIN_MAX)
    segs = _consec_segments(vals)
    for seg in segs:
        if len(seg) >= 5:
            score += len(seg) * 1.1
        elif len(seg) >= 3:
            score += len(seg) * 0.5

    # 散牌惩罚
    singles = sum(1 for v, c in cnt.items() if c == 1 and v < 15)
    score -= singles * 1.4

    return max(0.0, min(100.0, score * 100 / 78.0))
