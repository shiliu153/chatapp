"""发版版本号的单一来源同步器(D-5 第 3 步)。

设计要点:
    版本号的事实来源**只有一个**:``app/pubspec.yaml`` 的 ``version:`` 行(形如
    ``1.0.4+5``,``+5`` 是构建号)。另外两处必须与它的**版本名**部分一致:

    - ``app/lib/core/app_info.dart`` 的 ``appVersion``(App 关于页展示 + 测试守卫);
    - ``web/package.json`` 的 ``version``(网页端关于页与发版)。

    以前这三处靠人手改,漏改的表现很隐蔽(关于页显示旧版本 / 网页端版本号对不上),
    所以这里收敛成一个脚本 + CI 的 ``--check``:

        python scripts/sync_version.py --check   # 只校验,CI 用;不一致退出码 1
        python scripts/sync_version.py --write   # 以 pubspec.yaml 为准写回另外两处

注意事项:
    只同步「版本名」(``1.0.4``),不同步构建号(``+5``):构建号只在 App 侧有意义。
    脚本只做**字符串替换**,不改动文件其余内容与换行风格。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBSPEC = REPO_ROOT / "app" / "pubspec.yaml"
APP_INFO = REPO_ROOT / "app" / "lib" / "core" / "app_info.dart"
WEB_PACKAGE = REPO_ROOT / "web" / "package.json"

# pubspec 里 ``version: 1.0.4+5`` 的版本名部分
PUBSPEC_VERSION_RE = re.compile(r"^version:\s*([0-9][^\s+]*)", re.MULTILINE)
# app_info.dart 里 ``const appVersion = '1.0.4';``
APP_INFO_VERSION_RE = re.compile(r"const appVersion = '([^']*)';")
# package.json 顶层 ``"version": "1.0.4",``
WEB_VERSION_RE = re.compile(r'^(\s*)"version":\s*"([^"]*)"', re.MULTILINE)


def read_pubspec_version(path: Path = PUBSPEC) -> str:
    """读取 ``app/pubspec.yaml`` 里的版本名(不含构建号)。

    Args:
        path: pubspec 文件路径,默认仓库里的 ``app/pubspec.yaml``。

    Returns:
        版本名,如 ``1.0.4``。

    Raises:
        SystemExit: 文件不存在或找不到 ``version:`` 行(脚本没有可信来源,必须停)。
    """
    text = _read(path)
    match = PUBSPEC_VERSION_RE.search(text)
    if not match:
        _fail(f"{path} 里找不到 version: 行")
    return match.group(1)


def read_app_info_version(path: Path = APP_INFO) -> str:
    """读取 ``app/lib/core/app_info.dart`` 里的 ``appVersion``。

    Args:
        path: app_info.dart 路径,默认仓库里的那一份。

    Returns:
        版本名;找不到时返回空串(交给 ``collect_mismatches`` 报出来)。
    """
    match = APP_INFO_VERSION_RE.search(_read(path))
    return match.group(1) if match else ""


def read_web_version(path: Path = WEB_PACKAGE) -> str:
    """读取 ``web/package.json`` 的顶层 ``version``。

    Args:
        path: package.json 路径,默认仓库里的那一份。

    Returns:
        版本名;找不到时返回空串。
    """
    match = WEB_VERSION_RE.search(_read(path))
    return match.group(2) if match else ""


def write_app_info_version(version: str, path: Path = APP_INFO) -> bool:
    """把 ``appVersion`` 写成指定版本。

    Args:
        version: 目标版本名,如 ``1.0.4``。
        path: app_info.dart 路径。

    Returns:
        ``True`` 表示文件被改动,``False`` 表示本来就是目标值。

    Raises:
        SystemExit: 文件里找不到 ``const appVersion`` 声明。
    """
    text = _read(path)
    if not APP_INFO_VERSION_RE.search(text):
        _fail(f"{path} 里找不到 const appVersion 声明")
    updated = APP_INFO_VERSION_RE.sub(f"const appVersion = '{version}';", text, count=1)
    return _write_if_changed(path, text, updated)


def write_web_version(version: str, path: Path = WEB_PACKAGE) -> bool:
    """把 ``web/package.json`` 的 ``version`` 写成指定版本。

    Args:
        version: 目标版本名,如 ``1.0.4``。
        path: package.json 路径。

    Returns:
        ``True`` 表示文件被改动,``False`` 表示本来就是目标值。

    Raises:
        SystemExit: 文件里找不到顶层 version 字段。
    """
    text = _read(path)
    if not WEB_VERSION_RE.search(text):
        _fail(f"{path} 里找不到顶层 version 字段")
    updated = WEB_VERSION_RE.sub(lambda m: f'{m.group(1)}"version": "{version}"',
                                 text, count=1)
    return _write_if_changed(path, text, updated)


def collect_mismatches(pubspec: Path = PUBSPEC, app_info: Path = APP_INFO,
                       web_package: Path = WEB_PACKAGE) -> list[str]:
    """对比三处版本号,返回不一致描述(空列表表示完全一致)。

    Args:
        pubspec: 事实来源文件。
        app_info: App 侧常量文件。
        web_package: 网页端 package.json。

    Returns:
        逐条中文描述;空列表表示三处一致。
    """
    expected = read_pubspec_version(pubspec)
    problems = []
    for label, actual, path in (
        ("app/lib/core/app_info.dart", read_app_info_version(app_info), app_info),
        ("web/package.json", read_web_version(web_package), web_package),
    ):
        if actual != expected:
            problems.append(f"{label} 是 {actual or '(缺失)'},应为 {expected}")
    if problems:
        problems.insert(0, f"事实来源 app/pubspec.yaml = {expected}")
        problems.append("修复:python scripts/sync_version.py --write")
    return problems


def _read(path: Path) -> str:
    """读文本文件(UTF-8)。

    Args:
        path: 文件路径。

    Returns:
        文件内容。

    Raises:
        SystemExit: 文件不存在或读不出来。
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        _fail(f"读不到 {path}:{error}")


def _write_if_changed(path: Path, original: str, updated: str) -> bool:
    """内容不同才落盘(避免无意义的 mtime 变化与 diff 噪音)。

    Args:
        path: 目标文件。
        original: 原内容。
        updated: 新内容。

    Returns:
        ``True`` 表示写了文件。
    """
    if original == updated:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def _fail(message: str) -> None:
    """打印错误并以退出码 1 结束。

    Args:
        message: 错误描述。

    Raises:
        SystemExit: 总是抛出,退出码 1。
    """
    print(f"[版本号] {message}", file=sys.stderr)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 命令行参数;``None`` 表示取 ``sys.argv[1:]``。

    Returns:
        退出码:0 一致(或已写回),1 不一致(``--check`` 模式)。
    """
    parser = argparse.ArgumentParser(description="发版版本号同步(app/pubspec.yaml 为准)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只校验,不一致时退出码 1(默认)")
    mode.add_argument("--write", action="store_true", help="以 pubspec.yaml 为准写回另外两处")
    args = parser.parse_args(argv)

    expected = read_pubspec_version()
    if args.write:
        changed = [write_app_info_version(expected), write_web_version(expected)]
        print(f"[版本号] 已按 {expected} 同步;改动 {sum(changed)} 个文件")
        return 0

    problems = collect_mismatches()
    if problems:
        for problem in problems:
            print(f"[版本号] {problem}", file=sys.stderr)
        return 1
    print(f"[版本号] 三处一致:{expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
