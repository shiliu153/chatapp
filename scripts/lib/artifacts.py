#!/usr/bin/env python3
"""「生成物 == HEAD」的比对语义(唯一一份实现,C9)。

为什么需要它
------------
``openapi.yml`` 与 ``schema.d.ts`` 是**生成物**:它们必须「与代码一致」且「已经提交」。
2026-11-14 之前这条判定只有 shell 一份实现(住在 ``scripts/stacks/env.sh``,由
``stacks/{backend,web}.sh`` 调用),Python 侧无法复用,于是门禁注册表(第 4 节)里没有它,
「新增一道门禁的改动点 = 1 处」对这两条不成立。

为什么不用 ``git diff --exit-code``
-----------------------------------
本仓库在 Windows 上检出是 CRLF,而 WSL / CI 里的 git 按 LF 理解索引 —— ``git diff`` 会把
上千个文件都算成改动(实测 1094 个),这条判定在 WSL 里等于永远红。所以比的是**内容**:
把两边的 ``\\r`` 都去掉再比。语义与原 shell 实现完全一致,区别只有退出码 ——
「生成物不在 HEAD / 与代码不一致」是**判定失败**(门禁红,退出码 1),
不是「执行器故障」;只有 git 本身不可用才是 2。

用法
----
    python scripts/lib/artifacts.py docs/api/openapi.yml      # 0 一致 / 1 不一致 / 2 判不出来

门禁注册表里 ``kind = "artifact"`` 的 ``command`` 就是**生成物的仓库相对路径**,
``scripts/run_gates.py`` 按这条命令跑本文件 —— 人也可以手跑同一条。

本文件**不 import** ``scripts.lib`` 里的任何东西:它要能被直接执行(``sys.path[0]`` 是
``scripts/lib/``),仓库根由 ``__file__`` 往上三层推出来。
"""

from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: 仓库根目录(``scripts/lib/artifacts.py`` 往上三层)。
ROOT = Path(__file__).resolve().parents[2]

#: 差异输出最多打印多少行(与旧 shell 实现的 ``head -40`` 一致,避免刷屏)。
DIFF_LINES = 40


class ArtifactError(RuntimeError):
    """判不出来:git 不可用、路径非法、目标不是仓库内文件。调用方应退出 2。"""


@dataclass(frozen=True)
class Result:
    """一次生成物比对的结果。

    Attributes:
        ok: 是否一致(既在 HEAD 里、内容也相同)。
        path: 被比对的仓库相对路径。
        problems: 逐条中文问题描述(空表示通过)。
        diff: 便于人看的统一 diff(前 :data:`DIFF_LINES` 行;无差异时为空串)。
    """

    ok: bool
    path: str
    problems: tuple[str, ...]
    diff: str = ""


def normalize(data: bytes) -> bytes:
    """把行尾统一成 ``\\n``(只动 ``\\r``,不动其它字节)。

    Args:
        data: 原始字节。

    Returns:
        去掉 ``\\r`` 之后的字节。CRLF 与 LF 的同一份内容在这里相等。
    """
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def compare(rel_path: str, root: Path = ROOT) -> Result:
    """比对「工作区的生成物」与「HEAD 里的那一版」。

    Args:
        rel_path: 生成物的仓库相对路径,如 ``docs/api/openapi.yml``。
        root: 仓库根目录(自测时可指向临时仓库)。

    Returns:
        :class:`Result`。三种失败都返回结果而不是抛异常:不在 HEAD 里、文件不存在、
        内容不一致 —— 它们都是**判定失败**(门禁红),不是执行器故障。

    Raises:
        ArtifactError: 路径是绝对路径或含 ``..``,或 git 不可用 / 目标不在仓库里(判不出来)。
    """
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ArtifactError(f"生成物路径必须是仓库内的相对路径:{rel_path}")
    posix = rel.as_posix()
    working = Path(root) / rel

    head = _head_bytes(Path(root), posix)
    if head is None:
        return Result(
            ok=False,
            path=posix,
            problems=(
                f"{posix} 不在 HEAD 里:新增生成物请先提交,否则 CI 会对不上",
            ),
        )
    try:
        current = working.read_bytes()
    except OSError as error:
        return Result(
            ok=False,
            path=posix,
            problems=(f"{posix} 在工作区读不到:{error}",),
        )

    if normalize(head) == normalize(current):
        return Result(ok=True, path=posix, problems=())

    diff = "\n".join(
        list(
            difflib.unified_diff(
                normalize(head).decode("utf-8", "replace").splitlines(),
                normalize(current).decode("utf-8", "replace").splitlines(),
                fromfile=f"HEAD:{posix}",
                tofile=posix,
                lineterm="",
            )
        )[:DIFF_LINES]
    )
    return Result(
        ok=False,
        path=posix,
        problems=(f"{posix} 与代码不一致:重新生成并提交",),
        diff=diff,
    )


def _head_bytes(root: Path, posix: str) -> bytes | None:
    """取 ``HEAD:<path>`` 的内容。

    Args:
        root: 仓库根目录。
        posix: 仓库相对路径(POSIX 分隔符)。

    Returns:
        该文件在 HEAD 里的字节;文件不在 HEAD 里时返回 ``None``。

    Raises:
        ArtifactError: git 不可用,或 ``root`` 不是 git 仓库(判不出来)。
    """
    exists = _git(root, "cat-file", "-e", f"HEAD:{posix}", check=False)
    if exists.returncode != 0:
        # 区分「文件不在 HEAD 里」与「HEAD 本身不存在 / 不是仓库」:
        # 后者是判不出来(2),不能冒充「生成物没提交」(1)。
        head = _git(root, "rev-parse", "--verify", "HEAD", check=False)
        if head.returncode != 0:
            raise ArtifactError(f"{root} 不是 git 仓库或还没有提交,无法比对生成物")
        return None
    return _git(root, "show", f"HEAD:{posix}").stdout


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """在指定仓库里跑一条 git 命令。

    Args:
        root: 仓库根目录。
        *args: 传给 git 的参数。
        check: 为 ``True`` 时非零退出抛 :class:`ArtifactError`。

    Returns:
        完成的进程对象(stdout 是字节)。

    Raises:
        ArtifactError: git 不存在,或 ``check=True`` 时命令失败。
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, check=False
        )
    except FileNotFoundError as error:
        raise ArtifactError("找不到 git 命令,无法比对生成物") from error
    if check and completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise ArtifactError(f"git {' '.join(args)} 失败:{message or completed.returncode}")
    return completed


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表;``None`` 表示取 ``sys.argv[1:]``。

    Returns:
        0 一致;1 不一致(生成物不在 HEAD / 内容不同);2 判不出来。
    """
    parser = argparse.ArgumentParser(
        description="校验生成物与 HEAD 里的那一版一致(比内容、忽略行尾)"
    )
    parser.add_argument("path", help="生成物的仓库相对路径,如 docs/api/openapi.yml")
    parser.add_argument("--root", type=Path, default=ROOT, help="仓库根,默认本仓库")
    args = parser.parse_args(argv)

    try:
        result = compare(args.path, args.root)
    except ArtifactError as error:
        print(f"[生成物] 判不出来:{error}", file=sys.stderr)
        return 2

    if result.ok:
        print(f"生成物一致: {result.path}")
        return 0
    for problem in result.problems:
        print(f"[生成物] {problem}", file=sys.stderr)
    if result.diff:
        print(f"--- {result.path} 与 HEAD 的差异(前 {DIFF_LINES} 行) ---", file=sys.stderr)
        print(result.diff, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
