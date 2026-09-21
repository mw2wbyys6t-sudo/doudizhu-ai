# -*- coding: utf-8 -*-
"""
欢乐斗地主 · 本地 AI 对战服务
=============================

前端: static/ 下的单页游戏
后端: FastAPI, 提供会话化对局 + 托管 AI 轮次
模型: 本机 llama-server (OpenAI 兼容), 不可用时自动降级为启发式 AI

启动:
    python server.py            # 默认 http://127.0.0.1:7860
    python server.py --port 8888 --no-llm
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
import uuid
from typing import Dict, Optional

# 内嵌 Python(隔离模式)不会自动加入脚本目录, 手动补上
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game.ai import AIAgent, LLMClient, heuristic_play
from game.cards import TYPE_NAMES
from game.engine import PHASE_BID, PHASE_OVER, PHASE_PLAY, SEAT_NAMES_AI, Game
from game.wallet import MIN_STAKE, Wallet

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# ---------------------------------------------------------------- 全局配置

CFG = {
    "llm_url": os.environ.get("DDZ_LLM_URL", "http://127.0.0.1:8000/v1"),
    "llm_model": os.environ.get("DDZ_LLM_MODEL", "qwen3-4b"),
    "use_llm": os.environ.get("DDZ_NO_LLM", "") != "1",   # 默认启用大模型决策
    "allow_say": True,
    "think_delay": 0.35,        # 每步 AI 的最小思考时间, 让节奏自然
}

STAKE_OPTIONS = [50, 100, 200, 500]   # 可选底注 (token)

client = LLMClient(CFG["llm_url"], CFG["llm_model"])
model_ok = {"value": False, "checked": 0.0}
wallet = Wallet()


def model_available(force: bool = False) -> bool:
    """探测大模型服务是否可用。未启用模型时直接返回 False, 避免每次请求都去连。

    结果缓存 30 秒, 防止前端高频轮询把时间耗在连接超时上。
    """
    if not CFG["use_llm"]:
        return False
    now = time.time()
    if force or now - model_ok["checked"] > 30:
        model_ok["value"] = client.available()
        model_ok["checked"] = now
    return model_ok["value"]


# ---------------------------------------------------------------- 会话

class Session:
    def __init__(self, human: int = 0, stake: int = 100):
        self.id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.stake = int(stake)
        self.settled = False
        self.game = Game(human_index=human, stake=self.stake)
        self.agents = {
            s: AIAgent(client, allow_say=CFG["allow_say"])
            for s in range(3) if s != human
        }
        self.thinking: Optional[int] = None
        self.says: Dict[int, Dict] = {}
        self.created = time.time()
        self.ai_running = False

    # -------- 状态 --------
    def public_state(self) -> Dict:
        g = self.game
        st = g.state(g.human)
        st["thinking"] = self.thinking
        st["says"] = self.says
        st["llm_ready"] = model_available()
        st["llm_enabled"] = CFG["use_llm"]
        st["wallet"] = wallet.snapshot()
        self._settle_if_over()
        return st

    def _settle_if_over(self) -> None:
        """对局结束时把 token 输赢写入钱包(只结算一次)。须在持有 session 锁时调用。"""
        if self.settled or self.game.phase != PHASE_OVER:
            return
        self.settled = True
        delta = (self.game.delta or [0, 0, 0])[self.game.human]
        if delta:
            landlord_win = self.game.winner == self.game.landlord
            summary = (f"{'地主胜' if landlord_win else '农民胜'}"
                       f" 底注{self.stake}x叫分{self.game.base_score}"
                       f"x倍数{self.game.multiplier}"
                       + (" 春天" if getattr(self.game, "spring", False) else ""))
            wallet.settle(delta, summary)

    # -------- AI 决策 --------
    def _agent(self, seat: int) -> AIAgent:
        if seat not in self.agents:
            self.agents[seat] = AIAgent(client, allow_say=CFG["allow_say"])
        return self.agents[seat]

    def _ai_bid(self, seat: int) -> None:
        g = self.game
        ctx = g.ai_context(seat)
        # 已有叫分情况描述
        parts = []
        for s, v in g.bids.items():
            parts.append(f"{SEAT_NAMES_AI[s]}{'不叫' if v == 0 else f'叫{v}分'}")
        ctx["bid_desc"] = "，".join(parts) if parts else "还没人叫"

        legal = g.legal_bids(seat)
        if CFG["use_llm"] and model_available():
            value, say = self._agent(seat).decide_bid(ctx, legal)
        else:
            from game.ai import heuristic_bid, hand_power_cached
            value = heuristic_bid(hand_power_cached(ctx["hand"]), legal)
            say = ""

        if value not in legal:
            value = 0
        if say:
            self.says[seat] = {"text": say, "t": time.time()}
        g.do_bid(seat, value)

    def _ai_play(self, seat: int) -> None:
        g = self.game
        ctx = g.ai_context(seat)
        moves = g.legal_moves(seat)

        if CFG["use_llm"] and model_available():
            idx, say = self._agent(seat).decide_play(ctx, moves)
        else:
            last = ctx["last"]
            last_team = bool(last) and (last["is_landlord"] == ctx["landlord_is_me"])
            last_cnt = 99
            if last:
                for name, c in ctx["counts"].items():
                    if name == last["by"]:
                        last_cnt = c
            idx = heuristic_play(moves, ctx["hand_count"], ctx["is_leader"],
                                 last_by_teammate=last_team, last_player_count=last_cnt)
            say = ""

        if say:
            self.says[seat] = {"text": say, "t": time.time()}

        if idx < 0 or idx >= len(moves):
            if g.must_play(seat):
                # 必须出牌却没有合法解(理论上不会发生)
                g.do_play(seat, [g.hands[seat][0]])
            else:
                g.do_play(seat, None)
            return

        from game.cards import find_cards_in_hand
        cards = find_cards_in_hand(g.hands[seat], moves[idx]["ranks"])
        if cards is None:
            g.do_play(seat, None if not g.must_play(seat) else [g.hands[seat][0]])
        else:
            g.do_play(seat, cards)

    def run_ai(self) -> None:
        """把所有连续的 AI 回合跑完。"""
        with self.lock:
            if self.ai_running:
                return
            self.ai_running = True
        try:
            guard = 0
            while True:
                with self.lock:
                    g = self.game
                    if g.phase == PHASE_OVER:
                        self.thinking = None
                        return
                    cur = g.current
                    if cur == g.human:
                        self.thinking = None
                        return
                    self.thinking = cur
                guard += 1
                if guard > 400:
                    self.thinking = None
                    return

                t0 = time.time()
                try:
                    if self.game.phase == PHASE_BID:
                        self._ai_bid(cur)
                    elif self.game.phase == PHASE_PLAY:
                        self._ai_play(cur)
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger("ddz").exception("AI 回合异常: %s", exc)
                    with self.lock:
                        g = self.game
                        if g.phase == PHASE_BID:
                            g.do_bid(g.current, 0)
                        elif g.phase == PHASE_PLAY:
                            g.do_play(g.current, None if not g.must_play(g.current)
                                      else [g.hands[g.current][0]])

                spent = time.time() - t0
                if spent < CFG["think_delay"]:
                    time.sleep(CFG["think_delay"] - spent)
        finally:
            with self.lock:
                self.thinking = None
                self.ai_running = False


SESSIONS: Dict[str, Session] = {}
SESS_LOCK = threading.Lock()


def get_session(token: str) -> Session:
    with SESS_LOCK:
        s = SESSIONS.get(token)
        if s is None:
            raise HTTPException(404, "会话不存在, 请重新开始")
        return s


# ---------------------------------------------------------------- API

app = FastAPI(title="欢乐斗地主 · 本地AI版")


class NewReq(BaseModel):
    human_seat: int = 0
    stake: int = 100


class BidReq(BaseModel):
    token: str
    value: int


class PlayReq(BaseModel):
    token: str
    cards: list[str] | None = None
    pass_: bool = False

    model_config = {"populate_by_name": True}


class ConfigReq(BaseModel):
    use_llm: bool | None = None
    allow_say: bool | None = None


@app.post("/api/new")
def api_new(req: NewReq):
    stake = req.stake if req.stake in STAKE_OPTIONS else STAKE_OPTIONS[1]
    if not wallet.can_afford(stake):
        raise HTTPException(
            400, f"余额不足: 地主最多输 {stake * 2} token, 当前余额 {wallet.balance}。"
                 f"请在右上角重置钱包后继续。")
    s = Session(human=req.human_seat, stake=stake)
    with SESS_LOCK:
        SESSIONS[s.id] = s
        if len(SESSIONS) > 50:
            for k in sorted(SESSIONS, key=lambda x: SESSIONS[x].created)[:10]:
                SESSIONS.pop(k, None)
    threading.Thread(target=s.run_ai, daemon=True).start()
    time.sleep(0.05)
    with s.lock:
        return {"token": s.id, "state": s.public_state()}


@app.get("/api/wallet")
def api_wallet():
    snap = wallet.snapshot()
    snap["stake_options"] = STAKE_OPTIONS
    snap["min_stake"] = MIN_STAKE
    return snap


@app.post("/api/wallet/reset")
def api_wallet_reset():
    balance = wallet.reset()
    return {"balance": balance, "message": f"钱包已重置为 {balance} token"}


@app.get("/api/state")
def api_state(token: str):
    s = get_session(token)
    with s.lock:
        return s.public_state()


@app.post("/api/bid")
def api_bid(req: BidReq):
    s = get_session(req.token)
    with s.lock:
        ok = s.game.do_bid(s.game.human, req.value)
        if not ok:
            raise HTTPException(400, "当前不能这样叫分")
        st = s.public_state()
    threading.Thread(target=s.run_ai, daemon=True).start()
    return st


@app.post("/api/play")
def api_play(req: PlayReq):
    s = get_session(req.token)
    with s.lock:
        cards = None if req.pass_ else req.cards
        ok = s.game.do_play(s.game.human, cards)
        if not ok:
            raise HTTPException(400, "这手牌不合法, 出不了")
        st = s.public_state()
    threading.Thread(target=s.run_ai, daemon=True).start()
    return st


@app.post("/api/config")
def api_config(req: ConfigReq):
    if req.use_llm is not None:
        CFG["use_llm"] = req.use_llm
    if req.allow_say is not None:
        CFG["allow_say"] = req.allow_say
    return {"use_llm": CFG["use_llm"], "allow_say": CFG["allow_say"]}


@app.get("/api/health")
def api_health():
    return {
        "ok": True,
        "llm_enabled": CFG["use_llm"],
        "llm_ready": model_available(force=True),
        "llm_url": CFG["llm_url"],
        "calls": client.total_calls,
        "avg_latency": round(client.total_time / client.total_calls, 2) if client.total_calls else 0,
        "sessions": len(SESSIONS),
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------- 入口

def main() -> None:
    import uvicorn
    parser = argparse.ArgumentParser(description="欢乐斗地主本地 AI 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--llm-url", default=CFG["llm_url"])
    parser.add_argument("--no-llm", action="store_true", help="只用启发式 AI, 不调用大模型")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    CFG["llm_url"] = args.llm_url
    client.base_url = args.llm_url.rstrip("/")
    if args.no_llm:
        CFG["use_llm"] = False

    ready = model_available(force=True)
    model_ok["value"] = ready
    print("=" * 62)
    print("  欢乐斗地主 · 本地 AI 版")
    print("=" * 62)
    print(f"  游戏地址   : http://{args.host}:{args.port}")
    print(f"  模型服务   : {args.llm_url}  [{'已连接' if ready else '未连接'}]")
    print(f"  AI 模式    : {'大模型决策 + 规则校验' if (CFG['use_llm'] and ready) else '启发式规则 AI(模型未就绪)'}")
    print("=" * 62)
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
