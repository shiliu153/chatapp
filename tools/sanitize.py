#!/usr/bin/env python
"""隐私脱敏工具:把仓库里的敏感字面量换成占位符。

两处用途:
1. 就地脱敏当前工作区:            python tools/sanitize.py --apply
2. 生成 git-filter-repo 替换规则:  python tools/sanitize.py --expressions <out.txt>
   (历史重写: git filter-repo --replace-text <out.txt> --force)

替换按「长串优先」排序,避免短串先命中把长串切碎
(例如先换 yourname/chatapp,再换单独的 yourname)。

--------------------------------------------------------------------------
关于本文件自身的写法(重要)
--------------------------------------------------------------------------
本仓库已经脱敏过,所以**代码里不能再出现原始敏感值**——否则这个脚本自己
就成了泄漏源。因此:

* REPLACEMENTS 只写「占位符 -> 占位符」这类恒等规则,是可安全执行的空操作;
* 原始值以打码形式记录在 SANITIZED_RECORDS 里,仅供人工复核"洗过哪些东西"。

给后来者的用法:如果你 fork 之后要清洗自己的部署信息,把 REPLACEMENTS 换成
你自己「真实值 -> 占位符」的映射即可(顺序会按长度自动重排)。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# 可执行替换规则:(原文, 占位符)
# 当前为恒等映射 —— 工作区与历史都已清洗完毕,重跑不会改变任何文件。
REPLACEMENTS: list[tuple[str, str]] = [
    ("<SERVER_IP>", "<SERVER_IP>"),
    ("<PANEL_PORT>", "<PANEL_PORT>"),
    ("<YOUR_DB_PASSWORD>", "<YOUR_DB_PASSWORD>"),
    ("example.com", "example.com"),
    ("yourname/chatapp", "yourname/chatapp"),
    ("yourname", "yourname"),
    (r"C:\Users\you", r"C:\Users\you"),
    ("C:/Users/you", "C:/Users/you"),
    ("~/.ssh/<YOUR_KEY>", "~/.ssh/<YOUR_KEY>"),
]

# 已完成的脱敏记录:原始值打码,只用于说明"当时洗掉了什么"。
# 完整原始值只应存在于私有备份中,不要写进本文件。
SANITIZED_RECORDS: list[tuple[str, str, str]] = [
    ("服务器公网 IP", "47.116.***.***", "<SERVER_IP>"),
    ("宝塔面板端口", "31***", "<PANEL_PORT>"),
    ("个人域名(含 www)", "shiliu***.cn", "example.com"),
    ("GitHub 账号名", "shiliu***", "yourname"),
    ("开发/生产库口令", "chatapp_dev_****", "<YOUR_DB_PASSWORD>"),
    ("Windows 个人目录", r"C:\Users\201**", r"C:\Users\you"),
    ("本机 SSH 私钥路径", "~/.ssh/id_*****", "~/.ssh/<YOUR_KEY>"),
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
                if old != new:            # 恒等规则不计入命中报告
                    hits.setdefault(old, []).append(str(path.relative_to(root)))
                text = text.replace(old, new)
        if text != original and not dry_run:
            # 不用 write_text:它会统一换行符,改变原有换行
            path.write_bytes(text.encode("utf-8"))

    if not hits:
        print("没有需要替换的内容(规则为恒等映射,或仓库已处于脱敏状态)。")
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


def records() -> int:
    """打印已完成的脱敏记录(供人工复核)。"""
    print("已完成的脱敏项(原始值打码):")
    for what, masked, placeholder in SANITIZED_RECORDS:
        print(f"  {what:<18} {masked:<22} -> {placeholder}")
    print("\n注意:完整原始值只应存在于私有备份中,不要写进本仓库。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="就地脱敏工作区")
    parser.add_argument("--dry-run", action="store_true", help="只报告不修改")
    parser.add_argument("--expressions", type=Path, help="写出 filter-repo 替换规则文件")
    parser.add_argument("--records", action="store_true", help="打印已完成的脱敏记录")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    if args.records:
        return records()
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
