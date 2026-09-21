#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
autocommit.py —— 一有新内容就自动提交并推送

两层机制配合使用：
  1. 本脚本（文件监听守护）：盯着工作区，检测到内容变化 → 防抖等待 → git add/commit/push
  2. .githooks/post-commit（git 钩子）：你手动 commit 时也会自动推送到所有远端

常用命令：
    python tools/autocommit.py --install-hooks     # 启用 git 钩子
    python tools/autocommit.py                     # 启动监听（前台，Ctrl+C 退出）
    python tools/autocommit.py --once              # 只检查一次，有变化就提交推送
    python tools/autocommit.py --dry-run --once    # 只报告将要提交什么，不动仓库
    python tools/autocommit.py --status            # 看当前有哪些待提交内容被纳入

设计原则（都是刻意的，别随手改）：
    · 绝不 force push，绝不自动合并冲突 —— 推送被拒只报告，交给人处理
    · 默认不自动提交构建产物（dist/*.zip 51MB），否则每次提交都会永久撑大仓库
    · 合并/变基进行中不提交；索引被占用时等待
    · 推送失败只写日志，已提交的代码永远安全留在本地
"""

import argparse
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parent.parent
LOG_FILE = Path(__file__).resolve().parent / "autocommit.log"
PID_FILE = REPO / ".git" / "autocommit.pid"
INDEX_LOCK = REPO / ".git" / "index.lock"

# 不监听、也不自动提交的内容
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".idea",
                ".vscode", "_MACOSX", ".pytest_cache", "runtime", "model"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".pyd", ".log", ".tmp", ".swp", ".bak"}
EXCLUDE_GLOBS = ["dist/*.zip", "*/dist/*.zip"]

# 代理端口候选（GitHub 直连不稳定时用）
PROXY_PORTS = [7897, 7890, 10809, 10808, 7891]


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def log(msg: str, also_print: bool = True):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    if also_print:
        print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def git_env(proxy: str = None) -> dict:
    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        env.pop(k, None)
    env["GIT_TERMINAL_PROMPT"] = "0"        # 绝不弹凭据窗口卡住后台进程
    env["GIT_ASKPASS"] = "echo"
    if proxy:
        env["http_proxy"] = env["https_proxy"] = proxy
    return env


def run(args, *, proxy=None, timeout=180, check=False):
    """执行外部命令，返回 (returncode, 合并输出)。"""
    try:
        p = subprocess.run(args, cwd=str(REPO), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=git_env(proxy),
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"[超时] {' '.join(args)} 超过 {timeout}s"
    except FileNotFoundError as e:
        return 127, f"[找不到命令] {e}"
    out = (p.stdout or "") + (p.stderr or "")
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} 失败({p.returncode}): {out.strip()[:500]}")
    return p.returncode, out


def git(*args, proxy=None, timeout=180, check=False):
    return run(["git", *args], proxy=proxy, timeout=timeout, check=check)


def detect_proxy():
    """探测本机常见的本地代理端口，用于 GitHub 兜底。"""
    for p in PROXY_PORTS:
        s = socket.socket()
        s.settimeout(0.4)
        try:
            s.connect(("127.0.0.1", p))
            return f"http://127.0.0.1:{p}"
        except Exception:
            continue
        finally:
            s.close()
    return None


def is_excluded(rel: str) -> bool:
    parts = Path(rel).parts
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    if Path(rel).suffix.lower() in EXCLUDE_SUFFIX:
        return True
    posix = rel.replace("\\", "/")
    return any(fnmatch(posix, g) for g in EXCLUDE_GLOBS)


# --------------------------------------------------------------------------
# 工作区快照：只用来判断「有没有新内容」
# --------------------------------------------------------------------------

def snapshot() -> dict:
    files = {}
    stack = [REPO]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        if e.name in EXCLUDE_DIRS:
                            continue
                        stack.append(Path(e.path))
                    elif e.is_file(follow_symlinks=False):
                        rel = str(Path(e.path).relative_to(REPO))
                        if is_excluded(rel):
                            continue
                        try:
                            st = e.stat()
                            files[rel] = (st.st_mtime_ns, st.st_size)
                        except OSError:
                            pass
        except (PermissionError, OSError):
            continue
    return files


def diff_snapshot(old: dict, new: dict) -> list:
    names = set(old) | set(new)
    return sorted(n for n in names if old.get(n) != new.get(n))


# --------------------------------------------------------------------------
# 待提交内容（以 git 为准，尊重 .gitignore）
# --------------------------------------------------------------------------

def pending_changes() -> list:
    """返回 [(状态码, 路径)]，已剔除构建产物/被忽略项。"""
    rc, out = git("status", "--porcelain", "-z")
    if rc != 0:
        return []
    tokens = [t for t in out.split("\0") if t]
    items, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if len(t) < 3:
            i += 1
            continue
        code, path = t[:2], t[3:]
        items.append((code, path))
        # 重命名/复制会多带一个旧路径
        if code[0] in ("R", "C") or code[1] in ("R", "C"):
            i += 2
        else:
            i += 1
    return [(c, p) for c, p in items if not is_excluded(p)]


# --------------------------------------------------------------------------
# 提交 + 推送
# --------------------------------------------------------------------------

def busy_state() -> str:
    gd = REPO / ".git"
    for name, label in (("MERGE_HEAD", "合并进行中"), ("rebase-merge", "变基进行中"),
                        ("rebase-apply", "变基进行中"), ("CHERRY_PICK_HEAD", "拣选进行中"),
                        ("BISECT_LOG", "二分查找进行中")):
        if (gd / name).exists():
            return label
    return ""


def wait_for_index(timeout=120):
    waited = 0
    while INDEX_LOCK.exists() and waited < timeout:
        time.sleep(1)
        waited += 1
    return not INDEX_LOCK.exists()


def commit_and_push(changes, args) -> int:
    if busy_state():
        log(f"跳过：仓库正处在「{busy_state()}」，交给你手动处理")
        return 0
    if not wait_for_index():
        log("跳过：.git/index.lock 一直存在（可能有其它 git 进程在跑）")
        return 0

    paths = [p for _, p in changes]
    staged_desc = " ".join(f"{c}:{p}" for c, p in changes[:5])
    if args.dry_run:
        log(f"[dry-run] 本应提交 {len(changes)} 个文件：{staged_desc}")
        return 0

    rc, out = git("add", "-A", "--", *paths)
    if rc != 0:
        log(f"git add 失败：{out.strip()[:300]}")
        return 1

    rc, _ = git("diff", "--cached", "--quiet")
    if rc == 0:
        log("暂存区为空（变化可能都被 .gitignore 忽略），跳过提交")
        return 0

    rc, detail = git("diff", "--cached", "--name-status")
    body_lines = [f"{line.split(chr(9))[0]:<3} {line.split(chr(9))[-1]}"
                  for line in detail.strip().splitlines() if line.strip()][:40]
    head = f"auto: {len(changes)} 个文件变更 · {datetime.now():%Y-%m-%d %H:%M}"
    rc, out = git("commit", "-m", head, "-m", "\n".join(body_lines))
    if rc != 0:
        log(f"提交失败：{out.strip()[:300]}")
        return 1
    log(f"已提交 {len(changes)} 个文件：{staged_desc}" + (" …" if len(changes) > 5 else ""))

    if args.no_push:
        log("（--no-push：本次不推送）")
        return 0
    return push_all(args)


def push_all(args) -> int:
    rc, out = git("rev-parse", "--abbrev-ref", "HEAD")
    branch = out.strip() if rc == 0 else ""
    if not branch or branch == "HEAD":
        log("当前不在分支上（游离 HEAD），跳过推送")
        return 0

    rc, out = git("remote")
    remotes = args.remotes or [r.strip() for r in out.split() if r.strip()]
    if not remotes:
        log("没有配置任何远端，跳过推送")
        return 0

    rc, local_sha = git("rev-parse", "HEAD")
    local_sha = local_sha.strip()
    failures = 0

    for remote in remotes:
        ok, note = _push_one(remote, branch, args)
        if ok:
            log(f"  [{remote}] 推送成功 → {branch} ({local_sha[:7]}) {note}")
        else:
            failures += 1
            log(f"  [{remote}] 推送失败 {note}（代码已安全提交在本地，请手动处理）")
    return 1 if failures == len(remotes) else 0


def _push_one(remote: str, branch: str, args) -> tuple:
    """直连 → 失败则走本机代理重试。返回 (是否成功, 附带说明)。"""
    rc, out = git("push", remote, f"HEAD:{branch}", timeout=args.push_timeout)
    if rc == 0:
        return True, ""
    first = _short(out)

    proxy = args.proxy or detect_proxy()
    if proxy:
        rc2, out2 = git("push", remote, f"HEAD:{branch}", proxy=proxy,
                        timeout=args.push_timeout)
        if rc2 == 0:
            return True, f"(经代理 {proxy})"
        return False, f"直连与代理均失败｜直连:{first}｜代理:{_short(out2)}"
    return False, first


def _short(text: str, n: int = 160) -> str:
    text = " ".join((text or "").split())
    return text[:n]


# --------------------------------------------------------------------------
# 单进程保护
# --------------------------------------------------------------------------

def acquire_pid() -> bool:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text().strip() or 0)
        except Exception:
            old = 0
        if old and old != os.getpid() and _alive(old):
            log(f"已有监听进程在运行（PID {old}）。若要强制启动，先关闭它或删除 {PID_FILE}")
            return False
    PID_FILE.write_text(str(os.getpid()))
    return True


def _alive(pid: int) -> bool:
    rc, out = run(["tasklist", "/FI", f"PID eq {pid}"], timeout=15)
    return rc == 0 and str(pid) in out


def release_pid():
    try:
        if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
            PID_FILE.unlink()
    except Exception:
        pass


# --------------------------------------------------------------------------
# 钩子安装
# --------------------------------------------------------------------------

def install_hooks() -> int:
    hooks_dir = REPO / ".githooks"
    hook = hooks_dir / "post-commit"
    if not hook.exists():
        log(f"[错误] 找不到钩子文件 {hook}")
        return 1
    rc, out = git("config", "core.hooksPath", ".githooks")
    if rc != 0:
        log(f"设置 core.hooksPath 失败：{out.strip()}")
        return 1
    try:
        os.chmod(hook, 0o755)
    except Exception:
        pass
    rc, out = git("config", "--get", "core.hooksPath")
    log(f"已启用 git 钩子：core.hooksPath = {out.strip()}")
    log(f"钩子文件：{hook}")
    log("效果：以后每次 commit（含手动提交）都会自动推送到所有远端。")
    log("临时跳过推送：SKIP_AUTOPUSH=1 git commit -m \"...\"")
    return 0


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def do_round(args, reason: str = "") -> int:
    changes = pending_changes()
    if not changes:
        log(f"检查到变化但无可提交内容（{reason} 可能只是构建产物/被忽略文件），跳过")
        return 0
    return commit_and_push(changes, args)


def watch(args) -> int:
    if not acquire_pid():
        return 1
    log("=" * 58)
    log("自动提交守护已启动")
    log(f"  仓库：{REPO}")
    log(f"  轮询间隔：{args.interval}s   防抖：{args.debounce}s")
    log(f"  排除：{'、'.join(sorted(EXCLUDE_DIRS))}；{'，'.join(EXCLUDE_GLOBS)}")
    log(f"  推送目标：{'、'.join(args.remotes) if args.remotes else '全部远端'}"
        f"{'（已禁用 --no-push）' if args.no_push else ''}")
    log("  停止：Ctrl+C")
    log("=" * 58)

    rc, out = git("remote")
    if "github" in out:
        p = detect_proxy()
        log(f"  检测到远端含 github，本机代理：{p or '未发现（GitHub 可能直连失败）'}")

    snap = snapshot()
    log(f"初始快照 {len(snap)} 个受监控文件")
    pending, last_change = False, 0.0
    try:
        while True:
            time.sleep(args.interval)
            cur = snapshot()
            changed = diff_snapshot(snap, cur)
            if changed:
                snap = cur
                pending, last_change = True, time.time()
                if args.verbose:
                    log(f"检测到 {len(changed)} 个文件变动：{', '.join(changed[:4])}"
                        + (" …" if len(changed) > 4 else ""))
            if pending and time.time() - last_change >= args.debounce:
                pending = False
                log("变动已静止，开始提交…")
                try:
                    do_round(args, "本次变动")
                except Exception as e:
                    log(f"提交过程异常（已忽略，继续监听）：{type(e).__name__}: {e}")
                snap = snapshot()          # 重新基线，避免重复触发
    except KeyboardInterrupt:
        log("收到中断，自动提交守护已停止")
    finally:
        release_pid()
    return 0


def show_status(args) -> int:
    snap = snapshot()
    changes = pending_changes()
    print(f"仓库：{REPO}")
    print(f"受监控文件：{len(snap)} 个")
    print(f"待提交内容：{len(changes)} 项")
    for c, p in changes[:30]:
        print(f"  {c}  {p}")
    if len(changes) > 30:
        print(f"  ...（共 {len(changes)} 项）")
    print("\n被排除的规则：")
    print(f"  目录：{', '.join(sorted(EXCLUDE_DIRS))}")
    print(f"  后缀：{', '.join(sorted(EXCLUDE_SUFFIX))}")
    print(f"  通配：{', '.join(EXCLUDE_GLOBS)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="工作区文件监听 + 自动提交推送")
    ap.add_argument("--once", action="store_true", help="只检查并处理一次后退出")
    ap.add_argument("--install-hooks", action="store_true", help="启用 .githooks/post-commit 钩子")
    ap.add_argument("--status", action="store_true", help="显示当前受监控与待提交情况")
    ap.add_argument("--dry-run", action="store_true", help="只报告将要提交什么，不真正提交")
    ap.add_argument("--no-push", action="store_true", help="只提交，不推送")
    ap.add_argument("--include-dist", action="store_true",
                    help="把 dist/*.zip 也纳入自动提交（会让仓库快速变大，慎用）")
    ap.add_argument("--interval", type=float, default=2.0, help="轮询间隔秒，默认 2")
    ap.add_argument("--debounce", type=float, default=8.0, help="内容静止多少秒后才提交，默认 8")
    ap.add_argument("--push-timeout", type=int, default=180, help="单次 push 超时秒，默认 180")
    ap.add_argument("--remotes", help="只推送到指定远端，逗号分隔（默认全部）")
    ap.add_argument("--proxy", help="兜底代理地址，如 http://127.0.0.1:7897（默认自动探测）")
    ap.add_argument("--verbose", action="store_true", help="打印每次检测到的变动")
    args = ap.parse_args()

    if args.include_dist:
        EXCLUDE_GLOBS.clear()
        log("注意：--include-dist 已开启，dist/*.zip 也会被自动提交")

    if args.remotes:
        args.remotes = [r.strip() for r in args.remotes.split(",") if r.strip()]

    if args.install_hooks:
        return install_hooks()
    if args.status:
        return show_status(args)
    if args.once:
        log("单次检查模式")
        return do_round(args, "单次检查")
    return watch(args)


if __name__ == "__main__":
    sys.exit(main())
