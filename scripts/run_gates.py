#!/usr/bin/env python3
"""门禁执行器:一份清单(`scripts/gates.toml`)驱动本地与 CI。

为什么需要它
------------
治理方案(``docs/superpowers/specs/2026-11-14-docs-and-scripts-governance-design.md``)
第 4 节要解决的是 ``sources-of-truth.md`` §4 **C5**:``verify.sh`` 自称「CI 的镜像」,
但两边门禁集不同(本地 15 条 / CI 19 条),且**没有一条命令是逐字相同的**。
手抄的镜像不是镜像 —— 只要有人加一道门禁而忘了另一边,差额就会长回来。

所以命令只写在 ``scripts/gates.toml``,本地与 CI 都调**这个**执行器:

    scripts/verify.sh contract            # 本地
    python scripts/run_gates.py --scope contract   # CI(contract.yml 唯一一个 step)

判定口径(全部机械)
------------------
- **清单一致**:``--list`` 的输出顺序 = ``gates.toml`` 的声明顺序 = id 的 POSIX 字节序。
  顺序必须跨平台稳定:第 3 节踩过 ``sorted(Path)`` 在 Windows 大小写不敏感、在 Linux
  敏感的坑,同一个道理。``scripts/test_gates.py`` 会断言这一点。
- **两边同源**:``scripts/test_gates.py`` 断言任何一条门禁命令都**不再以字面量**出现在
  ``contract.yml`` / ``verify.sh`` / ``scripts/stacks/*.sh`` 里,并断言 workflow 里
  只有一处调用本执行器。少了这条,「收成一行」可以靠手抄同义命令骗过验收。
- **缺工具 fail-closed**:``requires`` 里的外部工具缺失时该门禁判**红**,并给出安装命令。
  跳过 + WARN 会让「本地少跑一条还以为绿」,那正是 C5 的复发形态。
- **生成物校验是独立 kind**:``kind = "artifact"`` 的 ``command`` 是**生成物的仓库相对路径**
  (不是命令),执行器按 ``python scripts/lib/artifacts.py <路径>`` 跑它 —— 于是
  「生成物 == HEAD」的语义只有一份实现(C9),而它照样是注册表里的一道门禁
  (第 4 节之后「新增一道门禁的改动点 = 1 处」对所有门禁成立)。

解释器
------
命令里一律写 ``python``;本执行器把它换成 ``$CHATAPP_PY``(缺省 ``python3``):
本地 ``scripts/stacks/env.sh`` 导出 venv 的解释器,CI 用 setup-python 的 python。
不写两套表 —— 那是另一种手抄。

退出码
------
- ``0``:本组门禁全绿(``skipped`` 不算红);
- ``1``:有门禁红;
- ``2``:执行器自己出错(注册表不是合法 TOML / 字段缺失 / 命令为空 / scope 不存在 /
  解释器不可用)。**执行器坏了不能冒充门禁红**,否则人会去修错的东西。
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: 仓库根目录(本文件在 ``scripts/`` 下)。所有门禁的相对路径与 cwd 都以它为基准。
ROOT = Path(__file__).resolve().parent.parent
#: 默认注册表位置。``--config`` 只给自测用(临时目录造样本),生产路径不参数化。
DEFAULT_CONFIG = Path(__file__).resolve().parent / "gates.toml"
#: 允许的 scope。顺序 = POSIX 字节序(与 id 前缀一致)。
SCOPES = ("app", "backend", "contract", "imserver", "web")
#: 允许的 kind。python 走解释器替换,shell 整条交给 ``bash -c``,
#: artifact 的 command 是**生成物路径**(由 ``scripts/lib/artifacts.py`` 比对,见 C9)。
KINDS = ("artifact", "python", "shell")
#: 命令型门禁允许的解释器前缀(kind = "python" 时会被替换成 ``$CHATAPP_PY``)。
PYTHON_PREFIXES = ("python", "python3")
#: 生成物比对器(kind = "artifact" 时执行器的固定入口;语义与原 shell 实现一致,见 C9)。
ARTIFACT_CHECKER = "scripts/lib/artifacts.py"

EXIT_OK = 0
EXIT_GATE = 1
EXIT_USAGE = 2


class RegistryError(RuntimeError):
    """注册表或调用方式有问题 —— 执行器自己出错(退出码 2),不是门禁红。"""


@dataclass(frozen=True)
class Gate:
    """一道门禁的不可变描述(每个字段的含义见 ``scripts/gates.toml`` 头部注释)。

    Attributes:
        id: 唯一标识,形如 ``<scope>-<slug>``,也是失败时日志里被点名的东西。
        scope: 归属的栈,决定 ``--scope`` 过滤。
        kind: ``python`` 或 ``shell``。
        command: 真正执行的命令(``python`` 前缀会被换成 ``$CHATAPP_PY``)。
        reason: 一句话「为什么需要它」。
        requires: 外部工具名;缺任何一个即判红(fail-closed)。
        cwd: 相对仓库根的执行目录。
        env: 该门禁专用的环境变量(只影响子进程)。
    """

    id: str
    scope: str
    kind: str
    command: str
    reason: str
    requires: tuple[str, ...] = ()
    cwd: str = "."
    env: dict[str, str] = field(default_factory=dict)


def _text(entry: dict, key: str, where: str) -> str:
    """取一个必填的字符串字段。

    Args:
        entry: 一个 ``[[gate]]`` 表。
        key: 字段名。
        where: 出错时用来定位的说明(如「第 3 个 [[gate]]」)。

    Returns:
        去掉首尾空白的字段值。

    Raises:
        RegistryError: 字段缺失、不是字符串,或去空白后为空。
    """
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{where} 的 {key} 必须是非空字符串")
    return value.strip()


def _optional_cwd(entry: dict, where: str) -> str:
    """取可选的 ``cwd`` 并校验它指向仓库内一个真实存在的目录。

    Args:
        entry: 一个 ``[[gate]]`` 表。
        where: 出错时用来定位的说明。

    Returns:
        相对仓库根的目录(缺省 ``.``)。

    Raises:
        RegistryError: 不是字符串、是绝对路径、含 ``..``,或目录不存在。
    """
    value = entry.get("cwd", ".")
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{where} 的 cwd 必须是非空字符串")
    cwd = value.strip()
    if Path(cwd).is_absolute() or ".." in Path(cwd).parts:
        raise RegistryError(f"{where} 的 cwd 必须是仓库内的相对路径:{cwd}")
    if not (ROOT / cwd).is_dir():
        raise RegistryError(f"{where} 的 cwd 不存在:{cwd}")
    return cwd


def _optional_requires(entry: dict, where: str) -> tuple[str, ...]:
    """取可选的 ``requires``(外部工具名列表)。

    Args:
        entry: 一个 ``[[gate]]`` 表。
        where: 出错时用来定位的说明。

    Returns:
        工具名元组(保持声明顺序)。

    Raises:
        RegistryError: 不是字符串列表,或含空项。
    """
    value = entry.get("requires", [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise RegistryError(f"{where} 的 requires 必须是字符串列表")
    return tuple(item.strip() for item in value)


def _optional_env(entry: dict, where: str) -> dict[str, str]:
    """取可选的 ``env``(门禁专用环境变量)。

    Args:
        entry: 一个 ``[[gate]]`` 表。
        where: 出错时用来定位的说明。

    Returns:
        键值都是字符串的字典(缺省空)。

    Raises:
        RegistryError: 不是表,或值不是字符串。
    """
    value = entry.get("env", {})
    if not isinstance(value, dict) or any(
        not isinstance(item, str) for item in value.values()
    ):
        raise RegistryError(f"{where} 的 env 必须是「字符串 → 字符串」的表")
    return dict(value)


def load_registry(path: Path) -> list[Gate]:
    """读取并校验注册表,返回**按 id 的 POSIX 字节序**排好序的门禁列表。

    排序不依赖文件系统,也不依赖 locale:Windows 大小写不敏感、Linux 敏感,
    用 ``str.lower()`` 或 ``sorted(Path)`` 会让两边顺序不同,而 ``--list`` 的输出
    会被 lint 比对。

    Args:
        path: 注册表路径(生产用 ``scripts/gates.toml``,自测用临时文件)。

    Returns:
        校验通过的门禁列表。

    Raises:
        RegistryError: 文件读不到、不是合法 TOML、条目字段不合法、id 重复或命令为空。
    """
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as exc:
        raise RegistryError(f"读不到注册表 {path}:{exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise RegistryError(f"注册表不是合法 TOML {path}:{exc}") from exc

    entries = raw.get("gate")
    if not isinstance(entries, list) or not entries:
        raise RegistryError(f"{path} 里没有任何 [[gate]] 条目")

    gates: list[Gate] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        where = f"第 {index} 个 [[gate]]"
        if not isinstance(entry, dict):
            raise RegistryError(f"{where} 不是表")
        gate = Gate(
            id=_text(entry, "id", where),
            scope=_text(entry, "scope", where),
            kind=_text(entry, "kind", where),
            # 换行归一化:Windows 检出是 CRLF,而 ``bash -c`` 会把 ``\r`` 当成命令的一部分
            # (报 ``set: pipefail\r: invalid option name``)。.gitattributes 已把本文件钉成
            # LF,这里再兜一层 —— 执行器不能因为检出方式不同而红。
            command=_text(entry, "command", where).replace("\r\n", "\n").replace("\r", "\n"),
            reason=_text(entry, "reason", where),
            requires=_optional_requires(entry, where),
            cwd=_optional_cwd(entry, where),
            env=_optional_env(entry, where),
        )
        if gate.scope not in SCOPES:
            raise RegistryError(
                f"{where} 的 scope 不合法:{gate.scope}(可选:{' / '.join(SCOPES)})"
            )
        if gate.kind not in KINDS:
            raise RegistryError(
                f"{where} 的 kind 不合法:{gate.kind}(可选:{' / '.join(KINDS)})"
            )
        if gate.kind == "python":
            first = gate.command.split(maxsplit=1)[0]
            if first not in PYTHON_PREFIXES:
                raise RegistryError(
                    f"{where} 是 kind = \"python\",命令必须以 python 开头,实际是:{first}"
                )
        if gate.kind == "artifact":
            # command 是生成物的仓库相对路径:绝对路径或 `..` 会让 CI 与本地比到不同文件。
            # 这里按 **POSIX 形式**判一次(`/etc/x` 在 Windows 上 `Path.is_absolute()` 为假,
            # 而注册表是跨平台的,不能只信宿主机的语义)。
            posix = gate.command.replace("\\", "/")
            if (Path(gate.command).is_absolute() or posix.startswith("/")
                    or ".." in posix.split("/")
                    or (len(posix) > 1 and posix[1] == ":")):
                raise RegistryError(
                    f"{where} 是 kind = \"artifact\",command 必须是仓库内的生成物相对路径:"
                    f"{gate.command}"
                )
        if gate.id in seen:
            raise RegistryError(f"{where} 的 id 重复:{gate.id}")
        seen.add(gate.id)
        gates.append(gate)

    gates.sort(key=lambda gate: gate.id.encode("utf-8"))
    return gates


def interpreter() -> str:
    """返回 ``python`` 门禁要用的解释器:``$CHATAPP_PY``,缺省 ``python3``。

    Returns:
        解释器命令(可能是绝对路径,也可能是 PATH 里的名字)。
    """
    return os.environ.get("CHATAPP_PY") or "python3"


def build_argv(gate: Gate, python: str) -> list[str]:
    """把门禁命令变成可执行的参数向量。

    ``kind = "python"`` 用 ``shlex`` 切分(保留引号语义,如 ``-p 'test_*.py'``),
    并把开头的 ``python`` 换成解释器;``kind = "shell"`` 整条交给 ``bash -c``,
    这样多行脚本与 ``< <(...)`` 之类的 bash 语法都能用;``kind = "artifact"`` 的 command
    是生成物路径,执行器把它拼成 ``python scripts/lib/artifacts.py <路径>``。

    Args:
        gate: 门禁。
        python: 解释器(kind = "python" / "artifact" 时生效)。

    Returns:
        传给 ``subprocess.run`` 的参数列表。

    Raises:
        RegistryError: 命令里的引号不配对(shlex 切不开)。
    """
    if gate.kind == "artifact":
        return [python, ARTIFACT_CHECKER, gate.command]
    if gate.kind == "python":
        try:
            argv = shlex.split(gate.command)
        except ValueError as exc:
            raise RegistryError(f"{gate.id} 的命令切不开:{exc}") from exc
        argv[0] = python
        return argv
    return ["bash", "-c", gate.command]


def _is_ci() -> bool:
    """当前是否跑在 GitHub Actions 里(决定用注解还是人读的分隔线)。"""
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _stream(json_mode: bool):
    """人读输出该走哪一路:``--json`` 时走 stderr,保证 stdout 只有 JSON。"""
    return sys.stderr if json_mode else sys.stdout


def _first_line(command: str) -> str:
    """取命令的第一行,多行时补省略号(日志标题用)。"""
    lines = command.strip().splitlines()
    return lines[0] + ("  …" if len(lines) > 1 else "")


def render_list(gates: list[Gate], json_mode: bool) -> None:
    """打印清单(``--list``)。

    Args:
        gates: 已过滤的门禁。
        json_mode: 为真时向 stdout 打 JSON 数组(供 L4 与 lint 比对),否则打人读的两行式。
    """
    if json_mode:
        payload = [
            {
                "id": gate.id,
                "scope": gate.scope,
                "kind": gate.kind,
                "command": gate.command,
                "reason": gate.reason,
                "cwd": gate.cwd,
                "requires": list(gate.requires),
                "env": dict(gate.env),
            }
            for gate in gates
        ]
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    for gate in gates:
        print(
            f"{gate.id:<38} {gate.scope:<9} {gate.kind:<6} {gate.reason}",
            file=sys.stdout,
        )
        print(f"    + {_first_line(gate.command)}", file=sys.stdout)

    counts = {scope: sum(1 for gate in gates if gate.scope == scope) for scope in SCOPES}
    summary = " / ".join(f"{scope} {counts[scope]}" for scope in SCOPES if counts[scope])
    print(f"\n共 {len(gates)} 道门禁:{summary}", file=sys.stderr)


def render_dry_run(gates: list[Gate], python: str, stream) -> None:
    """逐条打印将要执行的命令,不执行(``--dry-run``)。

    每道门禁的第一行以 ``+ `` 开头、续行缩进两格 —— ``scripts/test_verify.sh`` 用
    ``grep -c '^+ '`` 数条数,与 ``--list`` 的条数对齐(第 4 节验收口径)。

    Args:
        gates: 已过滤的门禁。
        python: 解释器(``kind = "python"`` 的命令按它渲染)。
        stream: 输出流(``--json`` 时为 stderr)。
    """
    for gate in gates:
        print(f"[{gate.id}] {gate.reason}", file=stream)
        if gate.kind in ("python", "artifact"):
            print(f"+ {shlex.join(build_argv(gate, python))}", file=stream)
        else:
            for index, line in enumerate(gate.command.strip().splitlines()):
                print(("+ " if index == 0 else "  ") + line, file=stream)
        print("", file=stream)
    print(f"共 {len(gates)} 道门禁(仅打印,未执行)", file=stream)


def _announce(stream, gate: Gate, argv: list[str]) -> None:
    """打印一道门禁的开始标记(GitHub Actions 里用 ``::group::``,本地用分隔线)。

    Args:
        stream: 输出流。
        gate: 门禁。
        argv: 实际执行的参数向量(仅用于展示)。
    """
    title = f"[{gate.id}] {gate.reason}"
    if _is_ci():
        print(f"::group::{title}", file=stream)
        print(f"+ {shlex.join(argv)}", file=stream)
    else:
        print(f"\n=== {title} ===", file=stream)
        print(f"+ {shlex.join(argv)}", file=stream)


def _report_failure(stream, gate: Gate, code: int, message: str) -> None:
    """报一道门禁失败:CI 用 ``::error title=<id>::`` 注解,本地打人读的一行。

    Args:
        stream: 输出流。
        gate: 门禁。
        code: 退出码。
        message: 失败原因(缺工具时带安装命令)。
    """
    if _is_ci():
        print(f"::error title={gate.id}::{message}(退出码 {code})", file=stream)
    else:
        print(f"失败:{gate.id} —— {message}(退出码 {code})", file=stream)


def run_scope(
    gates: list[Gate], python: str, skipped: set[str], json_mode: bool
) -> list[dict]:
    """按顺序执行一组门禁,返回结果汇总。

    门禁输出不捕获(直接继承 stdout/stderr),这样 CI 日志是实时的;只有 ``--json``
    时才捕获并转写到 stderr,保证 stdout 上只有那一段 JSON。

    Args:
        gates: 已过滤的门禁(顺序即执行顺序)。
        python: 解释器。
        skipped: ``--skip`` 指定的 id 集合(本地排障用,CI 不使用)。
        json_mode: 为真时把门禁输出转写到 stderr。

    Returns:
        每道门禁一条 ``{"id", "scope", "status", "exit_code"}``;status 为
        ``ok`` / ``failed`` / ``skipped``。**不带耗时与时间戳** —— 输出要可逐字比对。
    """
    stream = _stream(json_mode)
    results: list[dict] = []
    for gate in gates:
        if gate.id in skipped:
            print(f"跳过 {gate.id}(--skip)", file=stream)
            results.append(
                {"id": gate.id, "scope": gate.scope, "status": "skipped", "exit_code": 0}
            )
            continue

        missing = [tool for tool in gate.requires if shutil.which(tool) is None]
        if missing:
            hint = f"缺少外部工具:{', '.join(missing)}(安装:sudo apt-get install -y {' '.join(missing)})"
            _report_failure(stream, gate, 127, hint)
            results.append(
                {"id": gate.id, "scope": gate.scope, "status": "failed", "exit_code": 127}
            )
            continue

        argv = build_argv(gate, python)
        env = os.environ.copy()
        env.update(gate.env)
        env["CHATAPP_PY"] = python
        _announce(stream, gate, argv)
        if json_mode:
            completed = subprocess.run(
                argv, cwd=str(ROOT / gate.cwd), env=env, capture_output=True, text=True
            )
            if completed.stdout:
                print(completed.stdout, end="", file=sys.stderr)
            if completed.stderr:
                print(completed.stderr, end="", file=sys.stderr)
            code = completed.returncode
        else:
            code = subprocess.run(argv, cwd=str(ROOT / gate.cwd), env=env).returncode
        if _is_ci():
            print("::endgroup::", file=stream)

        if code == 0:
            results.append(
                {"id": gate.id, "scope": gate.scope, "status": "ok", "exit_code": 0}
            )
        else:
            _report_failure(stream, gate, code, "门禁失败")
            results.append(
                {
                    "id": gate.id,
                    "scope": gate.scope,
                    "status": "failed",
                    "exit_code": code,
                }
            )
    return results


def _print_summary(results: list[dict], stream) -> None:
    """打印末尾汇总(通过 / 失败 / 跳过),失败时点名到 id。

    Args:
        results: ``run_scope`` 的返回值。
        stream: 输出流。
    """
    failed = [item["id"] for item in results if item["status"] == "failed"]
    passed = sum(1 for item in results if item["status"] == "ok")
    skipped = sum(1 for item in results if item["status"] == "skipped")
    print(
        f"\n门禁汇总:通过 {passed} / 失败 {len(failed)} / 跳过 {skipped}(共 {len(results)} 道)",
        file=stream,
    )
    if failed:
        print("失败的门禁:" + ", ".join(failed), file=stream)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表;``None`` 表示读 ``sys.argv[1:]``。

    Returns:
        进程退出码:0 全绿 / 1 有门禁红 / 2 执行器自己出错。
    """
    parser = argparse.ArgumentParser(
        prog="run_gates.py",
        description="按 scripts/gates.toml 执行门禁(本地与 CI 同一份清单、同一个执行器)。",
    )
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="注册表路径(仅自测用)"
    )
    parser.add_argument("--scope", choices=SCOPES, help="只处理某一组门禁")
    parser.add_argument("--list", action="store_true", help="列出清单,不执行")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令,不执行")
    parser.add_argument("--json", action="store_true", help="机器读输出")
    parser.add_argument(
        "--skip", action="append", default=[], metavar="ID", help="跳过某道门禁(本地排障用)"
    )
    args = parser.parse_args(argv)

    try:
        gates = load_registry(args.config)
        if args.scope:
            gates = [gate for gate in gates if gate.scope == args.scope]

        if args.list:
            render_list(gates, json_mode=args.json)
            return EXIT_OK

        if args.dry_run:
            render_dry_run(gates, interpreter(), _stream(args.json))
            return EXIT_OK

        if not args.scope:
            raise RegistryError(
                "执行时必须用 --scope 指定一组门禁(可选:"
                + " / ".join(SCOPES)
                + ");只打印用 --dry-run"
            )

        known = {gate.id for gate in gates}
        unknown = [item for item in args.skip if item not in known]
        if unknown:
            raise RegistryError("--skip 里有不存在的门禁:" + ", ".join(unknown))

        python = interpreter()
        if not (Path(python).is_file() or shutil.which(python)):
            raise RegistryError(
                f"解释器不可用:{python}(设 CHATAPP_PY,或先跑 scripts/verify.sh bootstrap)"
            )

        results = run_scope(gates, python, set(args.skip), args.json)
        if args.json:
            json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            _print_summary(results, sys.stdout)
        return EXIT_GATE if any(item["status"] == "failed" for item in results) else EXIT_OK
    except RegistryError as exc:
        print(f"错误:{exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
