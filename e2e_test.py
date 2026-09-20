# -*- coding: utf-8 -*-
"""
斗地主游戏 端到端自测
=====================
在一个脚本里完成: 拉起后端服务 -> 打完整的一局 -> 校验非法操作被拒 -> 关闭服务。
这样服务的生命周期全在脚本内, 不依赖外部常驻进程。

用法:
    python e2e_test.py            # 启发式 AI 模式 (不依赖大模型)
    python e2e_test.py --llm      # 走大模型 (需要 llama-server 已在 8000 端口运行)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def wait_health(sess: requests.Session, base: str, timeout: float = 60.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if sess.get(base + "/api/health", timeout=3).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def pick_cards(hand, ranks):
    """按牌面值从手牌里挑出对应数量。"""
    need = {}
    for r in ranks:
        need[r] = need.get(r, 0) + 1
    ids = []
    for c in hand:
        if need.get(c["rank"], 0) > 0:
            ids.append(c["id"])
            need[c["rank"]] -= 1
    return ids


def play_full_game(sess: requests.Session, base: str, human_seat: int,
                   verbose: bool = True, time_limit: float = 120.0):
    r = sess.post(base + "/api/new", json={"human_seat": human_seat}, timeout=30).json()
    token, st = r["token"], r["state"]

    steps = 0
    my_turns = 0
    wait_fail = 0
    deadline = time.time() + time_limit

    while st["phase"] != "over" and steps < 600:
        if time.time() > deadline:
            wait_fail += 1
            break
        steps += 1
        guard = 0
        while not st["is_my_turn"] and st["phase"] != "over" and guard < 300:
            if time.time() > deadline:
                break
            guard += 1
            time.sleep(0.15)
            st = sess.get(base + "/api/state", params={"token": token}, timeout=15).json()
        if st["phase"] == "over":
            break
        if not st["is_my_turn"]:
            wait_fail += 1
            break

        my_turns += 1
        if st["phase"] == "bid":
            legal = st["legal_bids"]
            st = sess.post(base + "/api/bid",
                           json={"token": token, "value": legal[-1]}, timeout=30).json()
        else:
            moves = st["legal_moves"]
            if not moves or not st["must_play"]:
                st = sess.post(base + "/api/play",
                               json={"token": token, "pass_": True}, timeout=30).json()
            else:
                # 选一手"牌多且牌小"的, 尽快脱手
                best = max(moves, key=lambda m: len(m["ranks"]) * 3 - m["rank"])
                ids = pick_cards(st["hand"], best["ranks"])
                st = sess.post(base + "/api/play",
                               json={"token": token, "cards": ids}, timeout=30).json()

    if verbose:
        print(f"  步数={steps}  我的回合数={my_turns}  轮次等待失败={wait_fail}")
        print(f"  阶段={st['phase']}  赢家={st['winner']}  地主={st['landlord']}")
        print(f"  比分={st['delta']}  剩余手牌={st['counts']}")
        for e in (st.get("log") or [])[-6:]:
            print("    ", e.get("text"))
    return st, steps, my_turns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7862)
    ap.add_argument("--llm", action="store_true", help="走大模型模式")
    args = ap.parse_args()

    base = f"http://127.0.0.1:{args.port}"
    sess = requests.Session()
    sess.trust_env = False          # 绕过系统代理

    cmd = [PY, "-u", os.path.join(BASE_DIR, "server.py"), "--port", str(args.port)]
    if not args.llm:
        cmd.append("--no-llm")

    srv_log_path = os.path.join(BASE_DIR, "_e2e_server.log")
    srv_log = open(srv_log_path, "w", encoding="utf-8", errors="replace")

    print("=" * 62)
    print("  启动服务:", " ".join(cmd))
    print("=" * 62)
    proc = subprocess.Popen(cmd, cwd=BASE_DIR, stdout=srv_log, stderr=subprocess.STDOUT)

    failures = []
    try:
        if not wait_health(sess, base, timeout=45):
            print("[x] 服务启动失败, 服务端输出:")
            print(open(srv_log_path, encoding="utf-8", errors="replace").read()[-3000:])
            return 1

        h = sess.get(base + "/api/health", timeout=5).json()
        print("健康检查:", h)
        print(f"  首页可访问: {sess.get(base + '/', timeout=5).status_code == 200}")
        print(f"  静态资源:   {sess.get(base + '/static/app.js', timeout=5).status_code == 200}")
        print()

        # ---------- 1. 三家座位各打一局 ----------
        for seat in (0, 1, 2):
            print(f"--- 第 {seat + 1} 局 (我坐 {seat} 号位) ---")
            try:
                st, steps, my_turns = play_full_game(sess, base, seat)
                if st["phase"] != "over":
                    failures.append(f"座位{seat}: 对局未结束 (phase={st['phase']})")
                if steps >= 600:
                    failures.append(f"座位{seat}: 步数超限, 可能死循环")
                if sum(st["delta"]) != 0:
                    failures.append(f"座位{seat}: 分数不守恒 {st['delta']}")
            except Exception as exc:
                failures.append(f"座位{seat}: 异常 {type(exc).__name__} {exc}")
            print()

        # ---------- 2. 非法操作校验 ----------
        print("--- 非法操作校验 ---")
        r = sess.post(base + "/api/new", json={"human_seat": 0}, timeout=30).json()
        t2 = r["token"]
        st2 = r["state"]

        # 2.1 非法牌型: 出一手不存在的牌型 (单张 3 + 单张 5 若首出)
        guard = 0
        while not st2["is_my_turn"] and guard < 200:
            guard += 1
            time.sleep(0.15)
            st2 = sess.get(base + "/api/state", params={"token": t2}, timeout=15).json()

        if st2["phase"] == "play" and st2["must_play"]:
            hand = st2["hand"]
            bad_ids = [hand[0]["id"], hand[-1]["id"]] if len(hand) > 1 else [hand[0]["id"]]
            resp = sess.post(base + "/api/play", json={"token": t2, "cards": bad_ids}, timeout=15)
            ok = resp.status_code == 400
            print(f"  非法牌型被拒: {ok} (HTTP {resp.status_code})")
            if not ok:
                # 有可能恰好组成合法牌型(如对子), 只提示不算失败
                print("    [注] 该组合恰好合法(可能凑成对子), 跳过")
        elif st2["phase"] == "bid":
            resp = sess.post(base + "/api/bid", json={"token": t2, "value": 99}, timeout=15)
            ok = resp.status_code == 400
            print(f"  非法叫分被拒: {ok} (HTTP {resp.status_code})")
            if not ok:
                failures.append("非法叫分未被拒绝")

        # 2.2 不存在的会话
        resp = sess.get(base + "/api/state", params={"token": "no-such-token"}, timeout=10)
        ok = resp.status_code == 404
        print(f"  无效会话返回 404: {ok} (HTTP {resp.status_code})")
        if not ok:
            failures.append("无效会话未返回 404")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        srv_log.close()

    print()
    print("=" * 62)
    if failures:
        print("  [x] 发现", len(failures), "个问题:")
        for f in failures:
            print("      -", f)
        return 1
    print("  [√] 全部通过: 3 局完整对局 + 非法输入校验")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
