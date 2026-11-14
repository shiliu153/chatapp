"""版本号的读 / 写 / 比对(唯一一份实现)。

事实来源
--------
``app/pubspec.yaml`` 的 ``version:`` 行(形如 ``1.0.4+5``,``+5`` 是构建号)。另外两处必须与它的
**版本名**部分一致:``app/lib/core/app_info.dart`` 的 ``appVersion`` 与 ``web/package.json`` 的
``version``。这条规则本身在 ``docs/ops/release.md`` §2,owner 见 ``sources-of-truth.md`` §2.2。

收的是什么
----------
2026-11-14 实测:``PUBSPEC`` 路径在 ``create_release`` / ``release_prep`` / ``sync_version``
各拼一次;``PUBSPEC_VERSION_RE`` 有 **2 种变体**(只要版本名 / 版本名 + 构建号)共 3 份;
写回函数 ``write_app_info_version`` / ``write_web_version`` 与比对函数
``collect_mismatches`` 住在 ``sync_version`` 里,却被 ``release_prep`` 当 lib 反向 import ——
那条依赖是隐式的。现在两边都从本模块 import,「写」只有一份实现(D4 拍板:保留 ``--write``)。

错误处理口径
------------
本模块**不 print、不 exit**,只抛 :class:`VersionError`。``sync_version`` 把它翻成退出码 1,
``release_prep`` 把它翻成自己的 :class:`ReleasePrepError` —— 两者的退出码语义不同,
lib 不该替它们决定。
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.lib import REPO_ROOT

#: 版本号的唯一事实来源(``version: 1.0.4+5``)。
PUBSPEC = REPO_ROOT / "app" / "pubspec.yaml"

#: App 侧展示常量(``const appVersion = '1.0.4';``)。
APP_INFO = REPO_ROOT / "app" / "lib" / "core" / "app_info.dart"

#: 网页端 ``package.json``(顶层 ``"version": "1.0.4"``)。
WEB_PACKAGE = REPO_ROOT / "web" / "package.json"

#: pubspec 的版本名(丢掉构建号):``version: 1.0.4+5`` → ``1.0.4``。
PUBSPEC_VERSION_RE = re.compile(r"^version:\s*([0-9][^\s+]*)", re.MULTILINE)

#: pubspec 的版本名 + 可选构建号:``version: 1.0.4+5`` → ``("1.0.4", "5")``。
PUBSPEC_VERSION_BUILD_RE = re.compile(r"^version:\s*([0-9][^\s+]*)(?:\+(\d+))?", re.MULTILINE)

#: app_info.dart 的版本常量。
APP_INFO_VERSION_RE = re.compile(r"const appVersion = '([^']*)';")

#: package.json 的顶层 ``version`` 字段。
WEB_VERSION_RE = re.compile(r'^(\s*)"version":\s*"([^"]*)"', re.MULTILINE)


class VersionError(RuntimeError):
    """读不到版本号(文件缺失 / 找不到版本行),或写回时找不到目标声明。

    调用方负责把它翻成自己的退出码(见模块 docstring)。
    """


def read_pubspec_version(path: Path = PUBSPEC) -> str:
    """读取 ``app/pubspec.yaml`` 的版本名(不含构建号)。

    Args:
        path: pubspec 文件路径;默认仓库里的那一份。

    Returns:
        版本名,如 ``1.0.4``。

    Raises:
        VersionError: 文件不存在、读不出来,或找不到 ``version:`` 行(没有可信来源,必须停)。
    """
    return _match_pubspec(path).group(1)


def read_pubspec_version_and_build(path: Path = PUBSPEC) -> tuple[str, int]:
    """读取版本名与构建号(``+N`` 里的 N)。

    Args:
        path: pubspec 文件路径;默认仓库里的那一份。

    Returns:
        ``(版本名, 构建号)``;没有 ``+N`` 时构建号为 ``0``。

    Raises:
        VersionError: 文件不存在、读不出来,或找不到 ``version:`` 行。
    """
    match = _match_pubspec(path)
    return match.group(1), int(match.group(2) or 0)


def read_app_info_version(path: Path = APP_INFO) -> str:
    """读取 ``app/lib/core/app_info.dart`` 里的 ``appVersion``。

    Args:
        path: app_info.dart 路径;默认仓库里的那一份。

    Returns:
        版本名;找不到时返回空串(交给 :func:`collect_mismatches` 报出来,而不是在这里抛)。
    """
    match = APP_INFO_VERSION_RE.search(_read(path))
    return match.group(1) if match else ""


def read_web_version(path: Path = WEB_PACKAGE) -> str:
    """读取 ``web/package.json`` 的顶层 ``version``。

    Args:
        path: package.json 路径;默认仓库里的那一份。

    Returns:
        版本名;找不到时返回空串。
    """
    match = WEB_VERSION_RE.search(_read(path))
    return match.group(2) if match else ""


def write_app_info_version(version: str, path: Path = APP_INFO) -> bool:
    """把 ``appVersion`` 写成指定版本(其余内容与换行风格不动)。

    Args:
        version: 目标版本名,如 ``1.0.4``。
        path: app_info.dart 路径。

    Returns:
        ``True`` 表示文件被改动,``False`` 表示本来就是目标值。

    Raises:
        VersionError: 文件里找不到 ``const appVersion`` 声明。
    """
    text = _read(path)
    if not APP_INFO_VERSION_RE.search(text):
        raise VersionError(f"{path} 里找不到 const appVersion 声明")
    updated = APP_INFO_VERSION_RE.sub(f"const appVersion = '{version}';", text, count=1)
    return _write_if_changed(path, text, updated)


def write_web_version(version: str, path: Path = WEB_PACKAGE) -> bool:
    """把 ``web/package.json`` 的 ``version`` 写成指定版本(其余字段不动)。

    Args:
        version: 目标版本名,如 ``1.0.4``。
        path: package.json 路径。

    Returns:
        ``True`` 表示文件被改动,``False`` 表示本来就是目标值。

    Raises:
        VersionError: 文件里找不到顶层 ``version`` 字段。
    """
    text = _read(path)
    if not WEB_VERSION_RE.search(text):
        raise VersionError(f"{path} 里找不到顶层 version 字段")
    updated = WEB_VERSION_RE.sub(lambda m: f'{m.group(1)}"version": "{version}"', text, count=1)
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

    Raises:
        VersionError: ``pubspec`` 读不到或没有 ``version:`` 行。
    """
    expected = read_pubspec_version(pubspec)
    problems = []
    for label, actual in (
        ("app/lib/core/app_info.dart", read_app_info_version(app_info)),
        ("web/package.json", read_web_version(web_package)),
    ):
        if actual != expected:
            problems.append(f"{label} 是 {actual or '(缺失)'},应为 {expected}")
    if problems:
        problems.insert(0, f"事实来源 app/pubspec.yaml = {expected}")
        problems.append("修复:python scripts/sync_version.py --write")
    return problems


def _match_pubspec(path: Path) -> re.Match[str]:
    """在 pubspec 文本里定位 ``version:`` 行。

    Args:
        path: pubspec 文件路径。

    Returns:
        命中的正则对象(``group(1)`` 是版本名,``group(2)`` 可能为空)。

    Raises:
        VersionError: 文件读不到或找不到 ``version:`` 行。
    """
    match = PUBSPEC_VERSION_BUILD_RE.search(_read(path))
    if not match:
        raise VersionError(f"{path} 里找不到 version: 行")
    return match


def _read(path: Path) -> str:
    """读文本文件(UTF-8)。

    Args:
        path: 文件路径。

    Returns:
        文件内容。

    Raises:
        VersionError: 文件不存在或读不出来。
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise VersionError(f"读不到 {path}:{error}") from error


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
