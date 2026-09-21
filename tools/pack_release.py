#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重新打包免安装整合包（可重复执行）。

整合包 = 发行暂存目录（含 runtime/ 内嵌 Python、llama/、skills/、游戏本体）
        打包成一个 zip，并校验必需条目齐全。

用法:
    python tools/pack_release.py                 # 打包到默认位置并校验
    python tools/pack_release.py --check         # 只检查已有 zip 是否包含必需文件
    python tools/pack_release.py --src <目录> --out <zip> [--out <zip> ...]

默认路径（相对仓库自动定位，不写死盘符）:
    源目录: <仓库同级>/release/欢乐斗地主AI版
    产物  : <仓库>/dist/欢乐斗地主AI版_免安装整合包.zip

注意: dist 下的 zip 是二进制产物，默认被 .gitignore / 自动提交守护排除。
      若 README 挂了它的在线下载链接，发布前必须手动提交一次，否则用户下到旧包。
"""

import argparse
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]          # .../doudizhu
STAGING = REPO.parent / "release" / "欢乐斗地主AI版"  # .../release/欢乐斗地主AI版

ZIP_ROOT = "欢乐斗地主AI版"
DEFAULT_SRC = STAGING
DEFAULT_OUTS = [
    REPO.parent / "release" / f"{ZIP_ROOT}_免安装整合包.zip",
    REPO / "dist" / f"{ZIP_ROOT}_免安装整合包.zip",
]

# 不该进包的东西：模型权重（首次运行下载）、运行期状态、缓存
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".gguf"}
EXCLUDE_NAMES = {"wallet.json", ".DS_Store", "Thumbs.db", "_e2e_server.log"}

# 打包后必须存在的条目（少一个就说明打包残缺）
REQUIRED = [
    f"{ZIP_ROOT}/启动游戏.bat",
    f"{ZIP_ROOT}/启动AI助手.bat",
    f"{ZIP_ROOT}/使用说明.txt",
    f"{ZIP_ROOT}/server.py",
    f"{ZIP_ROOT}/runtime/python/python.exe",
    f"{ZIP_ROOT}/runtime/local_agent.py",
    f"{ZIP_ROOT}/skills/index.json",
    f"{ZIP_ROOT}/skills/README.md",
    f"{ZIP_ROOT}/skills/superpowers/SKILL.md",
    f"{ZIP_ROOT}/skills/web-design-engineer/SKILL.md",
    f"{ZIP_ROOT}/skills/taptap-maker/SKILL.md",
    f"{ZIP_ROOT}/skills/skills-security-check/SKILL.md",
]


def included(p: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in p.parts):
        return False
    if p.suffix.lower() in EXCLUDE_SUFFIX or p.name in EXCLUDE_NAMES:
        return False
    return True


def build(src: Path, dst: Path) -> tuple:
    files = [p for p in src.rglob("*") if p.is_file() and included(p)]
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    total = skipped = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, f in enumerate(files, 1):
            rel = f.relative_to(src).as_posix()
            try:
                z.write(f, f"{ZIP_ROOT}/{rel}")
                total += f.stat().st_size
            except (PermissionError, OSError):
                skipped += 1
            if i % 1000 == 0:
                print(f"    已写入 {i}/{len(files)} 个文件…", flush=True)
    if dst.exists():
        dst.unlink()
    tmp.replace(dst)
    return len(files), total, skipped


def check(zp: Path) -> bool:
    if not zp.exists():
        print(f"\n[跳过] 不存在: {zp}")
        return True
    with zipfile.ZipFile(zp) as z:
        names = set(z.namelist())
        broken = z.testzip()
    size_mb = zp.stat().st_size / 1048576
    print(f"\n检查 {zp.name}: {len(names)} 条记录, {size_mb:.2f} MB")
    print(f"  压缩包完整性: {'有损坏条目 -> ' + str(broken) if broken else '无损坏'}")
    ok = not broken
    for r in REQUIRED:
        hit = r in names
        ok &= hit
        print(("  [有] " if hit else "  [缺] ") + r)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="重新打包免安装整合包")
    ap.add_argument("--check", action="store_true", help="只检查已有 zip")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC, help="发行暂存目录")
    ap.add_argument("--out", type=Path, action="append", default=None,
                    help="产物 zip 路径，可重复指定（默认两个位置）")
    args = ap.parse_args()

    outs = args.out or DEFAULT_OUTS

    if args.check:
        results = [check(p) for p in outs if p.exists()]
        if not results:
            print("没有找到任何 zip，无法检查。")
            return 1
        return 0 if all(results) else 1

    if not args.src.exists():
        print(f"[错误] 源目录不存在: {args.src}")
        print("       用 --src 指定发行暂存目录，或先准备好该目录。")
        return 1

    for dst in outs:
        print(f"\n打包 → {dst}")
        n, total, skipped = build(args.src, dst)
        print(f"    完成: {n - skipped}/{n} 个文件, 原始 {total / 1048576:.1f} MB, "
              f"压缩后 {dst.stat().st_size / 1048576:.2f} MB")
        if skipped:
            print(f"    [注意] {skipped} 个文件被占用而跳过（通常是推理服务正在运行）")

    return 0 if all(check(p) for p in outs) else 1


if __name__ == "__main__":
    sys.exit(main())
