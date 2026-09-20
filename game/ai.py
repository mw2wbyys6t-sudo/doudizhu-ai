# -*- coding: utf-8 -*-
"""
AI 玩家: 规则引擎筛选合法出牌 + 大模型决策
==========================================

设计要点
--------
1. 合法性 100% 由规则引擎保证 —— 模型只在"合法候选"里挑一个;
2. 模型输出 JSON:  {"play": 编号, "say": "一句话"} / {"bid": 分值, "say": "..."}
3. 模型超时 / 输出异常时, 自动回退到启发式策略, 保证游戏永不卡死;
4. 静态 system prompt 放在最前面, 便于 llama-server 命中 prompt 缓存加速。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Dict, List, Optional, Tuple

import requests

from .cards import TYPE_NAMES, hand_power
from .engine import SEAT_NAMES_AI

log = logging.getLogger("ai")

SYSTEM_PROMPT = (
    "你是斗地主高手，出牌果断、讲究配合。"
    "只能从给定候选中选择，禁止自创出法。"
    "只输出一行 JSON，不要解释。"
)


# ================================================================ 模型客户端

class LLMClient:
    """调用 llama-server 的 OpenAI 兼容接口。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8000/v1",
                 model: str = "qwen3-4b", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False          # 绕过系统代理, 直连 localhost
        self.total_calls = 0
        self.total_time = 0.0

    def available(self) -> bool:
        """快速探测模型服务是否在线(总耗时上限约 2.5 秒)。"""
        for url in (f"{self.base_url}/models", "http://127.0.0.1:8000/health"):
            try:
                if self.session.get(url, timeout=1.2).status_code == 200:
                    return True
            except Exception:
                continue
        return False

    def chat(self, user_prompt: str, max_tokens: int = 48,
             temperature: float = 0.4, timeout: Optional[float] = None) -> Optional[str]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.8,
            "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        t0 = time.time()
        try:
            r = self.session.post(f"{self.base_url}/chat/completions",
                                  json=payload, timeout=timeout or self.timeout)
            r.raise_for_status()
            data = r.json()
            self.total_calls += 1
            self.total_time += time.time() - t0
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            log.warning("模型调用失败: %s", exc)
            return None


# ================================================================ 输出解析

def _strip_think(text: str) -> str:
    return re.sub(r" thinking.*?<｜end▁of▁thinking｜>", "", text, flags=re.S).strip()


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = _strip_think(text)
    m = re.search(r"\{.*?\}", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            # 容错: 单引号 / 尾逗号
            frag = m.group(0).replace("'", '"')
            frag = re.sub(r",\s*}", "}", frag)
            try:
                return json.loads(frag)
            except Exception:
                pass
    return None


def _extract_int(text: str, *keys: str) -> Optional[int]:
    obj = _extract_json(text)
    if isinstance(obj, dict):
        for k in keys:
            if k in obj:
                try:
                    return int(obj[k])
                except Exception:
                    pass
    if text:
        m = re.search(r"-?\d+", _strip_think(text))
        if m:
            return int(m.group(0))
    return None


def _extract_say(text: str) -> str:
    obj = _extract_json(text)
    if isinstance(obj, dict):
        say = obj.get("say") or obj.get("comment") or ""
        if isinstance(say, str):
            return say.strip()[:40]
    return ""


# ================================================================ 启发式兜底

def heuristic_play(moves: List[Dict], hand_count: int, is_leader: bool,
                   last_by_teammate: bool = False,
                   last_player_count: int = 99) -> int:
    """
    返回候选编号(moves 下标), -1 表示"不要"。绝不返回非法值。

    打分思路:
      出牌基础分 10 起步, 牌越多越好(利于脱手), 牌值越大越不舍得出;
      炸弹重罚(留作关键牌);  能一把走完直接加满。
      非先手时才评估是否过牌: 队友出的牌尽量让过, 对手快跑了必须拦。
    """
    if not moves:
        return -1

    best_idx, best_score = 0, 0.0
    non_bomb_best = None
    for i, m in enumerate(moves):
        ranks = m["ranks"]
        n = len(ranks)
        s = 10.0 + n * 1.5 - m["rank"] * 0.4
        if m["is_bomb"]:
            s -= 60
        elif non_bomb_best is None or s > non_bomb_best[1]:
            non_bomb_best = (i, s)
        if n == hand_count:
            s += 500                              # 一把走完, 直接赢
        if m["type"] in (6, 7, 8, 9, 10):         # 顺子/连对/飞机, 优先脱手
            s += 5
        if i == 0 or s > best_score:
            best_idx, best_score = i, s

    if is_leader:
        return best_idx

    # ---- 非先手: 判断是否应该过牌 ----
    if last_by_teammate:
        # 队友出的牌, 一般不压; 除非自己能一把出完
        return best_idx if best_score >= 500 else -1
    if last_player_count <= 6:
        # 对手(通常是地主)就要跑了 —— 能压就压, 必要时放炸弹
        if non_bomb_best is not None and last_player_count > 2:
            return non_bomb_best[0]
        return best_idx
    if best_score < -20:
        return -1                                 # 只有炸弹才能压, 先留着
    return best_idx


def heuristic_bid(power: float, legal: List[int]) -> int:
    """
    按牌力分位标定:  P90≈43  P72≈32  P50≈25
    """
    if power >= 42:
        want = 3
    elif power >= 32:
        want = 2
    elif power >= 25:
        want = 1
    else:
        want = 0
    if want == 0:
        return 0
    usable = [v for v in legal if v > 0]
    if not usable:
        return 0                                  # 别人已经叫得更高, 只能不叫
    if want in usable:
        return want
    return min(usable) if min(usable) > want else max(usable)


# ================================================================ AI 智能体

class AIAgent:
    def __init__(self, client: LLMClient, allow_say: bool = True,
                 temperature: float = 0.5, max_tokens: int = 64):
        self.client = client
        self.allow_say = allow_say
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.decisions: List[Dict] = []
        self.last_latency = 0.0

    # -------- 叫分 --------
    def decide_bid(self, ctx: Dict, legal: List[int]) -> Tuple[int, str]:
        power = hand_power_cached(ctx["hand"])
        fallback = heuristic_bid(power, legal)

        opts = " / ".join("不叫" if v == 0 else f"{v}分" for v in legal)
        bid_desc = ctx.get("bid_desc") or "还没人叫"
        say_hint = '，say: "一句短话"' if self.allow_say else ""
        prompt = (
            f"【叫地主】我的手牌({ctx['hand_count']}张): {ctx['hand']}\n"
            f"叫分情况: {bid_desc}\n"
            f"我可选: {opts}\n"
            f"（参考：牌力评分 {power:.0f}/100）\n"
            '只回复一行 JSON: {"bid": 分值' + say_hint + "}"
        )
        raw = self.client.chat(prompt, max_tokens=self.max_tokens,
                               temperature=self.temperature)
        val = _extract_int(raw, "bid", "value")
        if val is None or val not in legal:
            val = fallback
        say = _extract_say(raw) if self.allow_say else ""
        return val, say

    # -------- 出牌 --------
    def decide_play(self, ctx: Dict, moves: List[Dict]) -> Tuple[int, str]:
        """
        返回 (候选编号, 台词)。编号 -1 表示"不要"。
        """
        is_leader = ctx["is_leader"]
        last = ctx["last"]
        hand_count = ctx["hand_count"]

        last_by_teammate = False
        last_player_count = 99
        if last is not None:
            last_by_teammate = (last["is_landlord"] == ctx["landlord_is_me"])
            for name, c in ctx["counts"].items():
                if name == last["by"]:
                    last_player_count = c

        fallback = heuristic_play(
            moves, hand_count, is_leader,
            last_by_teammate=last_by_teammate,
            last_player_count=last_player_count,
        )

        if not moves:
            return -1, ""

        # ---- 构造候选项: options[k] 是第 k+1 号候选对应的 moves 下标, -1 表示"不要" ----
        raw_options: List[int] = []
        if not is_leader:
            raw_options.append(-1)                 # 可以过牌
        raw_options.extend(range(len(moves)))

        # 候选过多时裁剪: 保留启发式打分靠前的若干项 + 全部炸弹 + "不要"
        if len(raw_options) > 26:
            scored = []
            for j, oi in enumerate(raw_options):
                if oi == -1:
                    scored.append((0.0, j))
                    continue
                m = moves[oi]
                s = len(m["ranks"]) * 1.6 - m["rank"] * 0.35
                if m["type"] in (6, 7, 8, 9, 10):
                    s += 6
                if m["is_bomb"]:
                    s -= 8
                scored.append((s, j))
            scored.sort(key=lambda x: -x[0])
            keep = {j for _s, j in scored[:24]}
            keep |= {j for j, oi in enumerate(raw_options) if oi >= 0 and moves[oi]["is_bomb"]}
            if raw_options and raw_options[0] == -1:
                keep.add(0)
            raw_options = [raw_options[j] for j in sorted(keep)]

        options = raw_options
        lines = []
        for k, oi in enumerate(options, 1):
            if oi == -1:
                lines.append(f"{k}) 不要")
            else:
                m = moves[oi]
                lines.append(f"{k}) {m['text']}   ({m['type_name']})")

        last_desc = "我先手，可以出任意牌" if is_leader else (
            f"{last['by']}({'地主' if last['is_landlord'] else '农民'}) 出了 {last['text']}（{last['type_name']}），我要压过它"
        )
        others = "，".join(f"{k}剩{v}张" for k, v in ctx["counts"].items() if k != SEAT_NAMES_AI[ctx["seat"]])

        say_hint = '，say: "一句短话"' if self.allow_say else ""
        prompt = (
            f"【出牌】我是{ctx['role']}，手牌({hand_count}张): {ctx['hand']}\n"
            f"场上: {others}\n"
            f"情形: {last_desc}\n"
            f"候选:\n" + "\n".join(lines) + "\n"
            '只回复 JSON: {"play": 编号' + say_hint + "}"
        )

        t0 = time.time()
        raw = self.client.chat(prompt, max_tokens=self.max_tokens,
                               temperature=self.temperature)
        self.last_latency = time.time() - t0

        choice = _extract_int(raw, "play", "card", "choice", "index")
        say = _extract_say(raw) if self.allow_say else ""

        used_fallback = False
        if choice is None or choice < 1 or choice > len(options):
            fallback_pos = (options.index(fallback) + 1) if fallback in options else None
            if fallback_pos is None:
                # "不要" 选项
                if not is_leader:
                    choice = 1
                else:
                    choice = 1
            else:
                choice = fallback_pos
            used_fallback = True

        move_idx = options[choice - 1]
        self.decisions.append({
            "seat": ctx["seat"],
            "choice": choice,
            "move": moves[move_idx]["text"] if move_idx >= 0 else "不要",
            "fallback": used_fallback,
            "latency": self.last_latency,
            "raw": (raw or "")[:120],
        })
        return move_idx, say


# ---------------------------------------------------------------- 小工具

_power_cache: Dict[str, float] = {}


def hand_power_cached(hand_text: str) -> float:
    """hand_power 的文本缓存版(避免重复解析)。"""
    v = _power_cache.get(hand_text)
    if v is None:
        from .cards import SHORT_TO_RANK
        ranks = [SHORT_TO_RANK[t] for t in hand_text.split() if t in SHORT_TO_RANK]
        v = hand_power([f"{r}-0" for r in ranks])
        if len(_power_cache) > 2000:
            _power_cache.clear()
        _power_cache[hand_text] = v
    return v
