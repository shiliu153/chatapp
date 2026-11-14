#!/usr/bin/env python3
"""发版记录的渲染器与校验器(C8 / D1-B)。

``docs/releases.yml`` 是发版记录的**唯一事实来源**;``docs/ops/release.md`` §5 的表格是
**渲染物**,只覆盖 ``<!-- BEGIN generated:release-records -->`` 与
``<!-- END generated:release-records -->`` 之间的内容,区间外的手写内容一字不动
(与 ``scripts/docs_index.py`` 的 ``generated:api-summary`` 同一套做法)。

用法::

    python scripts/releases.py --check     # 渲染物 == releases.yml?不一致退出码 1
    python scripts/releases.py --render    # 重新渲染写回 release.md

为什么单独一个脚本
------------------
``sync_version.py`` 只回答「当前版本有没有留痕」;「渲染物是否过期」是另一条判定,
混在一起会让一条命令同时读两个数据源、给两种退出码理由。分工见
``docs/ops/release.md`` §3.2 的职责边界表。

退出码:0 一致(或已写回);1 不一致;2 判不出来(YAML 语法错 / 字段拼错 / 标记缺失)。

文件信息:
    文件名称          scripts/releases.py
    项目名称          chat_app / 工程脚本
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11
    适用平台          Linux x86_64（本地与 CI）
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# `python scripts/releases.py` 时 sys.path[0] 是 scripts/,显式把仓库根放进去,
# 这样 `from scripts.lib import docs` 在直接跑与 unittest 两种方式下都成立(见 lib/__init__.py)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import docs  # noqa: E402  (必须在 sys.path 修好之后)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 参数列表;``None`` 表示取 ``sys.argv[1:]``。

    返回参数:
        0 一致 / 已写回;1 不一致;2 判不出来。

    使用示例:
        ``python scripts/releases.py --check``

    备注信息:
        无特殊约束。
    """
    parser = argparse.ArgumentParser(
        description="渲染或校验发版记录(docs/releases.yml 是 owner,release.md §5 是渲染物)"
    )
    parser.add_argument("--root", default=".", help="仓库根目录(默认当前目录)")
    parser.add_argument("--check", action="store_true", help="校验(默认行为)")
    parser.add_argument("--render", "--write", dest="render", action="store_true",
                        help="重新渲染并写回 docs/ops/release.md")
    args = parser.parse_args(argv)

    root = Path(args.root)
    try:
        records = docs.load_records(docs.records_path(root))
        if args.render:
            changed = docs.write(root)
        else:
            problems = docs.check(root)
    except docs.DocsError as error:
        print(f"releases: 判不出来 —— {error}", file=sys.stderr)
        return 2

    summary = f"{len(records)} 条记录"
    if args.render:
        if changed:
            print(f"已渲染:docs/ops/release.md §5 发版记录区({summary})")
        else:
            print(f"releases: 渲染物已是最新,无需写入({summary})")
        return 0

    if problems:
        for problem in problems:
            print(problem)
        print(f"\n共 {len(problems)} 处不一致({summary})", file=sys.stderr)
        return 1
    print(f"releases: 发版记录区与 docs/releases.yml 一致({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
