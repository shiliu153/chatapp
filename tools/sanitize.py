#!/usr/bin/env python
"""把仓库里的隐私字面量替换成占位符。

两处用途:
1. 就地脱敏当前工作区:  python tools/sanitize.py --apply
2. 生成 git-filter-repo 的替换规则:  python tools/sanitize.py --expressions <out.txt>

替换按「长串优先」排序,避免短串先命中把长串切碎
(例如先替换 yourname/chatapp,再替换单独的 yourname)。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# (原文, 占位符) —— 顺序在运行时按原文长度倒序重排
REPLACEMENTS: list[tuple[str, str]] = [
    # --- 服务器 IP ---
    ("<SERVER_IP>", "<SERVER_IP>"),
    # --- 个人域名(含 www 前缀,必须先于裸域名) ---
    ("example.com", "example.com"),
    ("example.com", "example.com"),
    # --- GitHub 账号 ---
    ("yourname/chatapp", "yourname/chatapp"),
    ("yourname", "yourname"),
    # --- Windows 个人路径 ---
    (r"C:\Users\you", r"C:\Users\you"),
    ("C:/Users/you", "C:/Users/you"),
    # --- 数据库口令 ---
    ("<YOUR_DB_PASSWORD>", "<YOUR_DB_PASSWORD>"),
    # --- 本机 SSH 私钥路径(运维手册里提到过) ---
    ("~/.ssh/<YOUR_KEY>", "~/.ssh/<YOUR_KEY>"),
]

# 只对文本文件生效的扩展名
TEXT_SUFFIXES = {
    ".md", ".py", ".dart", ".yaml", ".yml", ".json", ".txt", ".cfg", ".ini",
    ".toml", ".sql", ".sh", ".bat", ".gradle", ".kts", ".properties", ".example",
}


def ordered() -> list[tuple[str, str]]:
    """长串优先,长度相同时保持声明顺序。"""
    return sorted(REPLACEMENTS, key=lambda kv: -len(kv[0]))


def tracked_text_files(root: Path) -> Iterable[Path]:
    """git 已跟踪的文本文件(跳过 flutter SDK / 二进制)。"""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    for rel in out.split("\0"):
        if not rel:
            continue
        path = root / rel
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if rel.startswith("flutter/"):
            continue
        yield path


def apply(root: Path, dry_run: bool) -> int:
    mapping = dict(REPLACEMENTS)
    hits: dict[str, list[str]] = {}
    for path in tracked_text_files(root):
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            print(f"  跳过(非 UTF-8): {path.relative_to(root)}", file=sys.stderr)
            continue
        original = text
        for old, new in ordered():
            if old in text:
                hits.setdefault(old, []).append(str(path.relative_to(root)))
                text = text.replace(old, new)
        if text != original and not dry_run:
            # 不用 write_text:它会把 \n 统一成 \n,改变原有换行
            path.write_bytes(text.encode("utf-8"))

    if not hits:
        print("没有命中任何隐私字面量。")
        return 0

    total = sum(len(v) for v in hits.values())
    print(f"{'[dry-run] ' if dry_run else ''}命中 {total} 处,涉及 {len(hits)} 类字面量:")
    for old, files in hits.items():
        print(f"  {old!r} -> {mapping[old]!r}")
        for f in files:
            print(f"      {f}")
    return 0


def expressions(out: Path) -> int:
    """写出 git-filter-repo --replace-text 用的规则: 字面量==>占位符"""
    lines = [f"{old}==>{new}\n" for old, new in ordered()]
    out.write_text("".join(lines), encoding="utf-8", newline="\n")
    print(f"已写出 {len(lines)} 条规则 -> {out}")
    for line in lines:
        print("  " + line.rstrip())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="就地脱敏工作区")
    parser.add_argument("--dry-run", action="store_true", help="只报告不修改")
    parser.add_argument("--expressions", type=Path, help="写出 filter-repo 替换规则文件")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    if args.expressions:
        return expressions(args.expressions)
    if args.dry_run:
        return apply(root, dry_run=True)
    if args.apply:
        return apply(root, dry_run=False)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
