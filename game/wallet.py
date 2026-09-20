# -*- coding: utf-8 -*-
"""
Token 钱包
==========
以 token 为赌注的积分系统:

* 每局底注 stake (token), 结算输赢 = 底注 x 倍数 (炸弹/春天翻倍由引擎完成);
* 地主赢 2 倍底注(每个农民输 1 倍), 农民赢各得 1 倍(地主输 2 倍);
* 余额持久化到 wallet.json, 跨局累计;
* 余额低于最小底注时禁止开局, 可重置。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WALLET_PATH = os.path.join(BASE_DIR, "wallet.json")

START_BALANCE = 10000        # 新钱包初始 token
MIN_STAKE = 10               # 单局最小底注
HISTORY_KEEP = 30            # 保留最近多少条结算记录


class Wallet:
    """线程安全的单用户钱包。"""

    def __init__(self, path: str = WALLET_PATH):
        self.path = path
        self.lock = threading.Lock()
        self.balance = START_BALANCE
        self.total_played = 0
        self.total_won = 0
        self.history: List[Dict] = []
        self._load()

    # ---------------- 持久化 ----------------

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.balance = int(data.get("balance", START_BALANCE))
            self.total_played = int(data.get("total_played", 0))
            self.total_won = int(data.get("total_won", 0))
            self.history = list(data.get("history", []))[:HISTORY_KEEP]
        except Exception:
            pass                       # 文件不存在或损坏 -> 用默认值

    def _save(self) -> None:
        data = {
            "balance": self.balance,
            "total_played": self.total_played,
            "total_won": self.total_won,
            "history": self.history[:HISTORY_KEEP],
            "updated": time.time(),
        }
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    # ---------------- 业务 ----------------

    def snapshot(self) -> Dict:
        with self.lock:
            return {
                "balance": self.balance,
                "start_balance": START_BALANCE,
                "min_stake": MIN_STAKE,
                "total_played": self.total_played,
                "total_won": self.total_won,
                "can_play": self.balance >= MIN_STAKE,
                "history": self.history[:10],
            }

    def can_afford(self, stake: int) -> bool:
        """地主最多输 2 倍底注, 因此要求余额 >= 2*stake 才算付得起。"""
        with self.lock:
            return self.balance >= 2 * max(stake, MIN_STAKE)

    def settle(self, delta: int, summary: str) -> int:
        """结算一局, delta 为本局 token 变化(正赢负输)。返回结算后余额。"""
        with self.lock:
            self.balance += delta
            self.total_played += 1
            if delta > 0:
                self.total_won += 1
            self.history.insert(0, {
                "t": round(time.time()),
                "delta": delta,
                "balance": self.balance,
                "summary": summary,
            })
            self.history = self.history[:HISTORY_KEEP]
            self._save()
            return self.balance

    def reset(self) -> int:
        with self.lock:
            self.balance = START_BALANCE
            self.total_played = 0
            self.total_won = 0
            self.history.insert(0, {
                "t": round(time.time()),
                "delta": 0,
                "balance": self.balance,
                "summary": "重置钱包",
            })
            self.history = self.history[:HISTORY_KEEP]
            self._save()
            return self.balance
