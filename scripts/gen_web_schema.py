#!/usr/bin/env python3
"""`web/src/api/schema.d.ts` 的生成器,以及「它是不是由当前契约生成的」这道判定。

为什么需要它(C10)
-----------------
`docs/api/openapi.yml` 是契约,`web/src/api/schema.d.ts` 是它的**派生生成物**;两者由
**不同的栈**重新生成:`verify.sh backend` 重新生成 openapi.yml,`verify.sh web` 重新生成
schema.d.ts。于是存在一个两头都看不见的缝:

    改视图 docstring(它会进 openapi 的 ``description``)
      → openapi.yml 重新生成并提交,``backend-openapi-artifact`` 绿
      → 但没人跑 ``verify.sh web``,schema.d.ts 已经过期
      → ``verify.sh backend`` **全绿**,只有 ``web`` 轨红

2026-11-16 的 PR #376 就是红的这个:`backend` / `contract` / `smoke` 全绿,`web` 红在
「schema.d.ts 与契约不一致」。当时是靠人合并前逐条核对 diff 才发现的 —— 那是纪律,不是机制。

做法:契约指纹
-------------
生成时在 schema.d.ts **第一行**写一行指纹注释,内容 = openapi.yml 规范化后的 sha256;
``--check`` 只做一件事:比指纹。它**不需要 Node、不需要网络**,所以能挂在 ``contract`` 组
(本地与 CI 每次都跑,秒级),在 backend 轨之后立刻红,而不是等 web 轨或等人肉 review。

指纹按**规范化(LF)后**的内容算:Windows 检出是 CRLF、WSL / CI 是 LF,不规范化会让同一份
契约算出两个哈希 —— 那正是 ``scripts/lib/artifacts.py`` 踩过的同一个坑。

用法
----
    python scripts/gen_web_schema.py            # 重新生成 schema.d.ts(需要 Node + 网络)
    python scripts/gen_web_schema.py --check    # 只比指纹(纯 Python,零依赖)
    python scripts/gen_web_schema.py --print    # 打印当前契约指纹,便于人工核对

退出码:0 一致 / 1 不一致(判定失败)/ 2 判不出来(文件缺失、格式坏掉、npx 失败)。

注意事项
--------
``web/package.json`` 的 ``gen:api`` 仍然是裸的 ``openapi-typescript`` —— 它**不写指纹**,
跑完本门禁会红。生成请用本脚本(``scripts/stacks/web.sh`` 已经改成调它),``npm run gen:api``
只留着给「临时看一眼类型」用。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: 仓库根目录(``scripts/gen_web_schema.py`` 往上两层)。
ROOT = Path(__file__).resolve().parents[1]

#: 契约(生成器的输入)的仓库相对路径。
OPENAPI = "docs/api/openapi.yml"

#: 生成物(生成器的输出)的仓库相对路径。
SCHEMA = "web/src/api/schema.d.ts"

#: 指纹行的前缀。``--check`` 只认这一行的这一种形状。
STAMP_PREFIX = "// @generated-from-openapi sha256="

#: 生成器命令(与 ``web/package.json`` 的 ``gen:api`` 同一个版本,固定版本是为了可复现)。
GENERATOR = ("npx", "--yes", "openapi-typescript@7.13.0")


class CheckError(RuntimeError):
    """判不出来:契约文件缺失、指纹行格式坏掉、生成器跑不起来。调用方应退出 2。"""


@dataclass(frozen=True)
class Result:
    """一次指纹比对的结果。

    Attributes:
        ok: 指纹是否与当前契约一致。
        problems: 逐条中文问题描述(空表示通过)。
        expected: 按当前契约算出来的指纹(判不出来时为空串)。
        actual: schema.d.ts 里写的指纹(缺失时为空串)。
    """

    ok: bool
    problems: tuple[str, ...]
    expected: str = ""
    actual: str = ""


def normalize(data: bytes) -> bytes:
    """把行尾统一成 ``\\n``(只动 ``\\r``,不动其它字节)。

    Args:
        data: 原始字节。

    Returns:
        去掉 ``\\r`` 之后的字节。CRLF 与 LF 的同一份内容在这里相等。
    """
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def fingerprint(root: Path = ROOT) -> str:
    """算出当前契约的指纹。

    Args:
        root: 仓库根目录(自测时可指向临时仓库)。

    Returns:
        ``openapi.yml`` 规范化内容的 sha256 十六进制摘要。

    Raises:
        CheckError: 契约文件不存在或读不出来(判不出来,不是判定失败)。
    """
    path = Path(root) / OPENAPI
    try:
        data = path.read_bytes()
    except OSError as error:
        raise CheckError(f"读不到契约 {OPENAPI}:{error}") from error
    return hashlib.sha256(normalize(data)).hexdigest()


def read_stamp(schema_path: Path) -> str:
    """取生成物第一行里写的指纹。

    Args:
        schema_path: ``schema.d.ts`` 的路径。

    Returns:
        指纹(小写十六进制);第一行不是指纹注释时返回空串。

    Raises:
        CheckError: 文件不存在或读不出来(判不出来)。
    """
    try:
        text = schema_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise CheckError(f"读不到生成物 {SCHEMA}:{error}") from error
    first = text.split("\n", 1)[0].strip()
    if not first.startswith(STAMP_PREFIX):
        return ""
    return first[len(STAMP_PREFIX):].strip()


def check(root: Path = ROOT) -> Result:
    """比对「生成物里写的指纹」与「当前契约算出来的指纹」。

    Args:
        root: 仓库根目录。

    Returns:
        :class:`Result`。生成物缺失、或第一行没有指纹,都算**判定失败**(``ok=False``)
        而不是抛异常 —— 那两种情况都能由人跑一条命令修好。

    Raises:
        CheckError: 契约读不到(判不出来)。
    """
    expected = fingerprint(root)
    schema_path = Path(root) / SCHEMA
    if not schema_path.exists():
        return Result(
            ok=False,
            problems=(f"{SCHEMA} 不存在:跑 python scripts/gen_web_schema.py 生成并提交",),
            expected=expected,
        )
    actual = read_stamp(schema_path)
    if not actual:
        return Result(
            ok=False,
            problems=(
                f"{SCHEMA} 第一行没有契约指纹(它是旧生成物,或者用 npm run gen:api 生成的)",
                "跑 python scripts/gen_web_schema.py 重新生成并提交",
            ),
            expected=expected,
        )
    if actual != expected:
        return Result(
            ok=False,
            problems=(
                f"{SCHEMA} 与契约不一致:它是按另一份 {OPENAPI} 生成的",
                f"  生成物记录的指纹: {actual}",
                f"  当前契约的指纹:   {expected}",
                "改了 openapi.yml(含视图 docstring)就要重新生成并提交:",
                "  python scripts/gen_web_schema.py",
            ),
            expected=expected,
            actual=actual,
        )
    return Result(ok=True, problems=(), expected=expected, actual=actual)


def generator_command() -> list[str]:
    """拼出可执行的生成器命令。

    Returns:
        参数向量,第一项是 ``npx`` 的**解析后路径**。

    Raises:
        CheckError: PATH 里找不到 npx(没装 Node,或 Node 没进 PATH)。

    备注信息:
        Windows 上 ``npx`` 是 ``npx.cmd``,直接写 ``"npx"`` 会 ``FileNotFoundError``
        (``WinError 2``);Linux / CI 里它是普通可执行文件。两种都靠 :func:`shutil.which`
        解析一次,而不是在命令里写死后缀。
    """
    exe = shutil.which(GENERATOR[0])
    if exe is None and os.name == "nt":
        exe = shutil.which(GENERATOR[0] + ".cmd")
    if exe is None:
        raise CheckError(
            "PATH 里找不到 npx:生成需要 Node 22(见 docs/standards/dev-commands.md)"
        )
    return [exe, *GENERATOR[1:]]


def generate(root: Path = ROOT) -> Path:
    """用 openapi-typescript 重新生成 schema.d.ts,并在第一行写入契约指纹。

    Args:
        root: 仓库根目录。

    Returns:
        写好的生成物路径。

    Raises:
        CheckError: 契约缺失、npx 跑不起来或生成失败(判不出来)。
    """
    root = Path(root)
    if not (root / OPENAPI).exists():
        raise CheckError(f"契约 {OPENAPI} 不存在,无从生成")
    command = generator_command()
    target = root / SCHEMA
    target.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件放在目标同目录:openapi-typescript 的输出路径与最终文件同盘,
    # 不跨盘复制;也避免半截文件被 `web-schema-artifact` 门禁读到。
    with tempfile.NamedTemporaryFile(
        "w", suffix=".d.ts", dir=target.parent, delete=False, encoding="utf-8"
    ) as handle:
        tmp_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [*command, OPENAPI, "-o", str(tmp_path)],
            cwd=str(root),
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout).decode("utf-8", "replace").strip()
            raise CheckError(f"生成器失败:{message or completed.returncode}")
        body = tmp_path.read_text(encoding="utf-8")
    finally:
        tmp_path.unlink(missing_ok=True)
    stamp = f"{STAMP_PREFIX}{fingerprint(root)}\n"
    target.write_text(stamp + body, encoding="utf-8", newline="\n")
    return target


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表;``None`` 表示取 ``sys.argv[1:]``。

    Returns:
        0 一致(或生成成功);1 判定失败;2 判不出来。
    """
    parser = argparse.ArgumentParser(
        description="生成 web/src/api/schema.d.ts 并校验它的契约指纹"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="只比指纹,不生成(零依赖)")
    group.add_argument("--print", dest="print_only", action="store_true", help="打印当前契约指纹")
    parser.add_argument("--root", type=Path, default=ROOT, help="仓库根,默认本仓库")
    args = parser.parse_args(argv)

    if args.print_only:
        try:
            print(fingerprint(args.root))
        except CheckError as error:
            print(f"[指纹] 判不出来:{error}", file=sys.stderr)
            return 2
        return 0

    if not args.check:
        try:
            path = generate(args.root)
        except CheckError as error:
            print(f"[生成] 判不出来:{error}", file=sys.stderr)
            return 2
        print(f"已生成 {path} (指纹 {fingerprint(args.root)[:12]}…)")
        return 0

    try:
        result = check(args.root)
    except CheckError as error:
        print(f"[指纹] 判不出来:{error}", file=sys.stderr)
        return 2
    if result.ok:
        print(f"生成物与契约一致: {SCHEMA} (指纹 {result.expected[:12]}…)")
        return 0
    for problem in result.problems:
        print(f"[指纹] {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
