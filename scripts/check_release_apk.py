"""release APK 的装机前体检(权限 / 内嵌 URL / 版本号),一条命令十秒内出结论。

为什么需要它
------------
1.0.14 的 GitHub Release 包出过两次「装上就用不了」,两次都只能靠人肉验证:

1. **权限**:release 构建只合并 ``app/android/app/src/main/AndroidManifest.xml``,
   而 Flutter 模板把 ``android.permission.INTERNET`` 只写在 ``debug/`` 与 ``profile/``
   的清单里(那两份给热重载)。缺了它整包 socket 全 EPERM,Dio 统一翻成「网络不给力」,
   服务端 0 请求 —— 1.0.1–1.0.14 全部踩过(见 ``docs/pitfalls/android-emulator.md``);
2. **URL**:``API_BASE`` 是编译期 ``--dart-define`` 注入的,裸跑 ``flutter build apk``
   会落回默认值 ``http://127.0.0.1:8000/api/v1``,装到手机上必然连不上;而产物长得跟
   正常包一模一样,确认它得解包 ``lib/<abi>/libapp.so`` 扫字符串。

仓库侧的清单门禁(:mod:`scripts.check_app_manifest`)只能证明「源码里写了」,
证明不了「**这个 APK** 里真的带上了」:构建时漏 ``--dart-define``、拿错产物、装错包,
它都看不见。本脚本看的是产物本身。

判定口径
--------
1. **权限** —— ``aapt2 dump permissions`` 必须含 ``android.permission.INTERNET``;
2. **内嵌 API_BASE** —— 读 ``lib/arm64-v8a/libapp.so``(退回 ``armeabi-v7a`` / ``x86_64``),
   扫出全部 ``http(s)://`` 串:生产域名必须在,且**不许**出现 ``127.0.0.1`` / ``localhost`` /
   ``10.0.2.2``(安卓模拟器的宿主别名)/ 任何裸 IP;
3. **版本号** —— ``aapt2 dump badging`` 的 ``versionName`` 必须等于 ``app/pubspec.yaml``
   的版本名(忽略 ``+build``)。

缺 ``aapt2`` 时**不静默通过**:权限与版本号两项明说「跳过…(缺 aapt2)」,退出码 2 ——
与 ``scripts/gates.toml`` 的 ``requires`` 同一口径(fail-closed:判不出来不等于合规)。

用法(仓库根目录):

    python scripts/check_release_apk.py app/build/app/outputs/flutter-apk/app-release.apk
    python scripts/check_release_apk.py <apk> --aapt2 /path/to/aapt2      # SDK 不在默认位置
    python scripts/check_release_apk.py <apk> --expect-url https://.../api/v1

退出码:0 全部通过 / 1 有违例 / 2 环境不对(缺 aapt2、APK 读不出来、aapt2 跑不起来)。

备注信息:
    ``aapt2`` 的查找顺序是 ``--aapt2`` → ``ANDROID_HOME`` / ``ANDROID_SDK_ROOT`` /
    ``ANDROID_SDK_HOME`` → 常见安装位置 → ``PATH``。WSL 里能直接找到 Windows 的
    ``aapt2.exe``(release 包本来就在 Windows 上出),此时传给它的路径先用 ``wslpath -w``
    换成 Windows 形态 —— 否则它读不到 ``/mnt/...``。自测见
    ``scripts/test_check_release_apk.py``。
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

#: 仓库根目录(本文件在 ``scripts/`` 下)。
REPO_ROOT = Path(__file__).resolve().parent.parent

#: 版本号唯一事实来源(相对仓库根)。
PUBSPEC = Path("app") / "pubspec.yaml"

#: release 包能不能联网就看这一条。
INTERNET_PERMISSION = "android.permission.INTERNET"

#: 生产 API 基址 —— App 的 ``API_BASE`` 必须是它(默认期望值,``--expect-url`` 可覆盖)。
PRODUCTION_API_BASE = "https://chat.shiliu153.cn/api/v1"

#: 出现在包里就说明「构建时没注入 API_BASE」。后两个是模拟器/本机回环的别名。
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "0.0.0.0", "10.0.2.2", "10.0.3.2"})

#: 扫哪个 ABI 的 ``libapp.so``:按顺序取第一个存在的(Dart 代码三个 ABI 相同)。
ABI_PREFERENCE = ("arm64-v8a", "armeabi-v7a", "x86_64")

#: ``libapp.so`` 在包里的路径模板。
LIBAPP_TEMPLATE = "lib/{abi}/libapp.so"

#: 扫 ``http(s)://`` 串:只认可打印 ASCII,不含空格(二进制里最常见的情形)。
URL_PATTERN = re.compile(rb"https?://[!-~]+")

#: 从 URL 尾巴上剥掉的标点(快照里的字符串常以 ``.`` / ``)`` 收尾)。
TRAILING_JUNK = ".,;:!?)]}\"'"

#: SDK 根目录的环境变量,按优先级。
SDK_ENV_KEYS = ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_SDK_HOME")

#: 事故经过与排查手册(报错里指过去)。
PITFALL_DOC = "docs/pitfalls/android-emulator.md"

#: 退出码:判不出来(环境不对)与「有违例」要能分开,否则 CI 里看不出该修包还是该装 SDK。
EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_ENVIRONMENT = 2


class CheckError(RuntimeError):
    """环境不对或工具读不出东西 —— 判不出来,按 ``EXIT_ENVIRONMENT`` 处理(不冒充合规)。"""


@dataclass
class Report:
    """一次体检的结果。

    Attributes:
        problems: 违例描述;空表示三项都合规。
        skips: 跳过了哪些检查(缺 ``aapt2`` 时出现)。
        abi: 实际扫的是哪个 ABI 的 ``libapp.so``。
        url_count: 扫出多少个 ``http(s)://`` 串 —— 数量本身就是证据(0 个说明扫错了文件)。
    """

    problems: list[str] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)
    abi: str = ""
    url_count: int = 0

    @property
    def ok(self) -> bool:
        """三项都查过且都合规才算通过。

        返回参数:
            `True` 表示没有任何违例,也没有跳过任何检查。

        使用示例:
            ``if report.ok: ...``

        备注信息:
            「跳过了」不等于「通过」—— 缺 ``aapt2`` 时它必须是 `False`,
            否则发版前那 10 秒就是白跑。
        """
        return not self.problems and not self.skips


def _is_wsl() -> bool:
    """判断当前解释器是不是跑在 WSL 里。

    返回参数:
        `True` 表示跑在 WSL(内核串里带 ``microsoft``)。

    使用示例:
        ``if _is_wsl(): ...``

    备注信息:
        只用来决定「Windows 的 ``aapt2.exe`` 需不需要换路径形态」,别处不依赖它。
    """
    return os.name == "posix" and "microsoft" in platform.release().lower()


def _build_tools_version(name: str) -> tuple[int, ...]:
    """把 build-tools 目录名(如 ``36.0.0``)解析成可比较的数字元组。

    参数说明:
        name: ``<SDK>/build-tools`` 下的目录名。

    返回参数:
        数字元组;解析不出来的片段按 0 计(排序用,不抛异常)。

    使用示例:
        ``_build_tools_version("34.0.0")`` → ``(34, 0, 0)``

    备注信息:
        目录名可能带后缀(``36.0.0-rc1``),只取开头的数字,拿不到就返回空元组(排最后)。
    """
    parts: list[int] = []
    for chunk in name.split("."):
        match = re.match(r"\d+", chunk)
        if match is None:
            break
        parts.append(int(match.group(0)))
    return tuple(parts)


def _aapt2_in(sdk_root: Path) -> Path | None:
    """在一个 SDK 根目录里挑最新 build-tools 下的 ``aapt2``。

    参数说明:
        sdk_root: SDK 根目录(其下有 ``build-tools/<版本>/aapt2``)。

    返回参数:
        ``aapt2`` 路径;该目录不存在或下面没有 ``aapt2`` 时返回 `None`。

    使用示例:
        ``_aapt2_in(Path("/usr/local/lib/android/sdk"))``

    备注信息:
        同时认 ``aapt2`` 与 ``aapt2.exe``:WSL 里被找到的往往是 Windows 那份。
        多个版本并存时取版本号最大者 —— 老 build-tools 读新 APK 会报
        ``failed opening zip`` 之类看不出原因的错。
    """
    build_tools = sdk_root / "build-tools"
    if not build_tools.is_dir():
        return None
    candidates: list[tuple[tuple[int, ...], Path]] = []
    for child in build_tools.iterdir():
        if not child.is_dir():
            continue
        for name in ("aapt2", "aapt2.exe"):
            binary = child / name
            if binary.is_file():
                candidates.append((_build_tools_version(child.name), binary))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def sdk_roots(env: dict[str, str] | None = None) -> list[Path]:
    """列出可能的 Android SDK 根目录(按优先级)。

    参数说明:
        env: 环境变量表;``None`` 表示 ``os.environ``。

    返回参数:
        候选 SDK 根目录列表(不保证存在)。

    使用示例:
        ``sdk_roots()``

    备注信息:
        前三个来自环境变量,其余是各平台默认安装位置;WSL 里额外扫
        ``/mnt/c/Users/*/AppData/Local/Android/Sdk`` —— 本项目的 release 包在 Windows 上出,
        SDK 就装在那里,而 WSL 的 ``ANDROID_HOME`` 往往是空的。
    """
    environment = os.environ if env is None else env
    roots: list[Path] = []
    for key in SDK_ENV_KEYS:
        value = environment.get(key)
        if value:
            roots.append(Path(value))
    local_appdata = environment.get("LOCALAPPDATA")
    if local_appdata:
        roots.append(Path(local_appdata) / "Android" / "Sdk")
    roots.extend(
        [
            Path.home() / "Android" / "Sdk",
            Path.home() / "Library" / "Android" / "sdk",
            Path("/usr/local/lib/android/sdk"),
            Path("/usr/lib/android-sdk"),
            Path("/opt/android-sdk"),
        ]
    )
    users = Path("/mnt/c/Users")
    if _is_wsl() and users.is_dir():
        roots.extend(sorted(users.glob("*/AppData/Local/Android/Sdk")))
    return roots


def find_aapt2(explicit: str | None = None, env: dict[str, str] | None = None) -> Path | None:
    """找 ``aapt2``。

    参数说明:
        explicit: ``--aapt2`` 给出的路径;给了就必须能用(不存在由调用方判错)。
        env: 环境变量表;``None`` 表示 ``os.environ``。

    返回参数:
        ``aapt2`` 路径;找不到返回 `None`。

    使用示例:
        ``aapt2 = find_aapt2()``

    备注信息:
        顺序:``--aapt2`` → :func:`sdk_roots` 里的 ``build-tools/*/aapt2`` → ``PATH``。
        返回 `None` 不是错误 —— 由 :func:`main` 决定「跳过并退出码 2」,
        这样自测可以把查找逻辑与环境解耦。
    """
    if explicit:
        return Path(explicit)
    for root in sdk_roots(env):
        found = _aapt2_in(root)
        if found is not None:
            return found
    for name in ("aapt2", "aapt2.exe"):
        on_path = shutil.which(name)
        if on_path:
            return Path(on_path)
    return None


def _aapt2_argument(path: Path, aapt2: Path) -> str:
    """把路径换成 ``aapt2`` 能读的形态。

    参数说明:
        path: 要传给 ``aapt2`` 的路径(通常是 APK)。
        aapt2: ``aapt2`` 可执行文件。

    返回参数:
        交给 ``aapt2`` 的路径字符串。

    使用示例:
        ``_aapt2_argument(apk, aapt2)``

    备注信息:
        Windows 的 ``aapt2.exe`` 在 WSL 里启动时看不到 WSL 原生路径(``/root/...``、``/tmp/...``),
        所以先用 ``wslpath -w`` 换成 ``D:\\...``;换不出来就抛 :class:`CheckError`,
        把「换个位置放 APK」这条修法说清楚,而不是让它报一个 ``Permission denied``。
    """
    resolved = path.resolve()
    if aapt2.suffix.lower() != ".exe" or not _is_wsl():
        return str(resolved)
    try:
        proc = subprocess.run(
            ["wslpath", "-w", str(resolved)],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CheckError(
            f"aapt2 是 Windows 程序({aapt2.as_posix()}),换不出 {resolved.as_posix()} 的 "
            f"Windows 路径({exc});把 APK 放到 /mnt/... 下再跑,或在 Windows 的 Python 里跑本脚本"
        ) from exc
    converted = proc.stdout.strip()
    if not converted:
        raise CheckError(f"wslpath 没换出 {resolved.as_posix()} 的 Windows 形态")
    return converted


def dump(aapt2: Path, apk: Path, what: str) -> str:
    """跑一次 ``aapt2 dump <what> <apk>``,返回标准输出。

    参数说明:
        aapt2: ``aapt2`` 可执行文件。
        apk: 要体检的 APK。
        what: ``permissions`` 或 ``badging``。

    返回参数:
        ``aapt2`` 的标准输出文本。

    使用示例:
        ``permissions = dump(aapt2, apk, "permissions")``

    备注信息:
        失败一律抛 :class:`CheckError`(退出码 2):``aapt2`` 读不出来就是判不出来,
        不能当成「没违例」。
    """
    if not aapt2.is_file():
        raise CheckError(f"找不到 aapt2:{aapt2.as_posix()}(用 --aapt2 指定,或设 ANDROID_HOME)")
    command = [str(aapt2), "dump", what, _aapt2_argument(apk, aapt2)]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CheckError(f"aapt2 跑不起来({aapt2.as_posix()}):{exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr.strip() or proc.stdout.strip()).splitlines()
        raise CheckError(
            f"aapt2 dump {what} 失败(退出码 {proc.returncode}):"
            f"{detail[-1] if detail else '没有输出'}"
        )
    return proc.stdout


def parse_permissions(permissions_dump: str) -> set[str]:
    """从 ``aapt2 dump permissions`` 的输出里取出权限名集合。

    参数说明:
        permissions_dump: ``aapt2 dump permissions`` 的标准输出。

    返回参数:
        权限名集合,如 ``{"android.permission.INTERNET", ...}``。

    使用示例:
        ``parse_permissions(dump(aapt2, apk, "permissions"))``

    备注信息:
        只认 ``uses-permission: name='...'`` 与 ``uses-permission-sdk-23: name='...'``
        —— ``permission:`` 行是本应用**定义**的权限,不是声明的,不能被当成 INTERNET。
    """
    found: set[str] = set()
    for line in permissions_dump.splitlines():
        stripped = line.strip()
        if not stripped.startswith("uses-permission"):
            continue
        match = re.search(r"name='([^']+)'", stripped)
        if match:
            found.add(match.group(1))
    return found


def check_permissions(permissions: set[str]) -> list[str]:
    """断言包里声明了 INTERNET。

    参数说明:
        permissions: :func:`parse_permissions` 的结果。

    返回参数:
        违例描述列表(空列表 = 合规)。

    使用示例:
        ``problems = check_permissions(permissions)``

    备注信息:
        违例里带上 ``docs/pitfalls/android-emulator.md``:这条权限的历史事故(1.0.1–1.0.14
        每个 release 包都没网)写在那一节里,读报错的人需要知道「为什么不能只在 debug 里写」。
    """
    if INTERNET_PERMISSION in permissions:
        return []
    return [
        f"权限:{INTERNET_PERMISSION} 不在包里 —— 装到手机上整包没网"
        f"(症状=登录页「网络不给力」而服务端 0 请求,见 {PITFALL_DOC})"
    ]


def parse_version_name(badging_dump: str) -> str | None:
    """从 ``aapt2 dump badging`` 的输出里取 ``versionName``。

    参数说明:
        badging_dump: ``aapt2 dump badging`` 的标准输出。

    返回参数:
        版本名(如 ``1.0.15``);输出里没有这一项时返回 `None`。

    使用示例:
        ``parse_version_name(dump(aapt2, apk, "badging"))``

    备注信息:
        只看 ``package:`` 那一行 —— ``minSdkVersion`` 等行里也有引号字段,
        全文搜 ``versionName=`` 容易吃到别的东西。
    """
    for line in badging_dump.splitlines():
        if not line.startswith("package:"):
            continue
        match = re.search(r"versionName='([^']*)'", line)
        if match:
            return match.group(1)
    return None


def check_version(version_name: str | None, expected: str) -> list[str]:
    """断言包里的 ``versionName`` 等于 ``pubspec.yaml`` 的版本名。

    参数说明:
        version_name: 包里读到的版本名(:func:`parse_version_name` 的结果,可为 `None`)。
        expected: 期望的版本名(``app/pubspec.yaml`` 的 ``version`` 去掉 ``+build``)。

    返回参数:
        违例描述列表(空列表 = 合规)。

    使用示例:
        ``problems = check_version(version_name, "1.0.15")``

    备注信息:
        ``None`` 单独成一条违例:读不到版本号时**不能**当成「没差异」。
    """
    if version_name is None:
        return ["版本号:包里读不到 versionName(拿错产物?还是 aapt2 太老?)"]
    if version_name == expected:
        return []
    return [
        f"版本号:包里是 {version_name},{PUBSPEC.as_posix()} 是 {expected} "
        "—— 产物是旧版本号时构建的,或构建后又改过版本号却没重新打包"
    ]


def read_pubspec_version(pubspec: Path | None = None) -> str:
    """读 ``app/pubspec.yaml`` 的版本名(去掉 ``+build``)。

    参数说明:
        pubspec: pubspec 路径;``None`` 表示本仓库的 ``app/pubspec.yaml``。

    返回参数:
        版本名,如 ``1.0.15``。

    使用示例:
        ``read_pubspec_version()``

    备注信息:
        抛 :class:`CheckError` 表示读不到或格式不认识 —— 版本号是唯一事实来源,
        它读不出来时整条「版本号」判定就不可信,应当退出码 2 而不是放过。
    """
    path = REPO_ROOT / PUBSPEC if pubspec is None else Path(pubspec)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckError(f"读不到 {PUBSPEC.as_posix()}:{exc}") from exc
    match = re.search(r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)", text, re.MULTILINE)
    if match is None:
        raise CheckError(f"{path.as_posix()} 里找不到形如 `version: 1.0.15+16` 的版本号")
    return match.group(1)


def libapp_member(apk: Path) -> str:
    """挑出要扫的 ``libapp.so`` 在包里的路径。

    参数说明:
        apk: APK 路径。

    返回参数:
        形如 ``lib/arm64-v8a/libapp.so`` 的包内路径。

    使用示例:
        ``member = libapp_member(apk)``

    备注信息:
        按 :data:`ABI_PREFERENCE` 取第一个存在的:三个 ABI 里是同一份 Dart 代码,
        扫一个就够,而全扫一遍要多解压二十多兆。
        抛 :class:`CheckError` 表示一个都没有(不是 Flutter APK,或拿错了产物)。
    """
    try:
        with zipfile.ZipFile(apk) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise CheckError(f"{apk.as_posix()} 不是可读的 APK(zip):{exc}") from exc
    for abi in ABI_PREFERENCE:
        member = LIBAPP_TEMPLATE.format(abi=abi)
        if member in names:
            return member
    raise CheckError(
        f"{apk.as_posix()} 里没有 lib/<abi>/libapp.so(找过 {'、'.join(ABI_PREFERENCE)})"
        " —— 不是 Flutter release 包,或者拿错了产物"
    )


def scan_urls(apk: Path, member: str | None = None) -> tuple[str, set[str]]:
    """扫 ``libapp.so`` 里的 ``http(s)://`` 串。

    参数说明:
        apk: APK 路径。
        member: 包内 ``libapp.so`` 路径;``None`` 表示按 :func:`libapp_member` 挑。

    返回参数:
        ``(ABI 名, URL 集合)``。

    使用示例:
        ``abi, urls = scan_urls(apk)``

    备注信息:
        扫的是**字符串字面量**:Dart 快照里 ``API_BASE`` 以原文出现,所以「包里有没有
        生产域名」「有没有 127.0.0.1」都能直接看见,不需要反编译。
        抛 :class:`CheckError` 表示解压不出来(退出码 2)。
    """
    target = libapp_member(apk) if member is None else member
    try:
        with zipfile.ZipFile(apk) as archive:
            data = archive.read(target)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise CheckError(f"读不出 {target}(在 {apk.as_posix()} 里):{exc}") from exc
    abi = target.split("/")[1] if target.count("/") >= 2 else "?"
    urls: set[str] = set()
    for match in URL_PATTERN.finditer(data):
        url = match.group(0).decode("ascii", "replace").rstrip(TRAILING_JUNK)
        if url:
            urls.add(url)
    return abi, urls


def _host_of(url: str) -> str:
    """取 URL 的 host(小写,去掉 userinfo 与端口)。

    参数说明:
        url: 完整 URL。

    返回参数:
        主机名;解析不出来时返回空串。

    使用示例:
        ``_host_of("https://chat.shiliu153.cn/api/v1")`` → ``chat.shiliu153.cn``

    备注信息:
        用 ``urlsplit`` 而不是手工切:快照里可能混进被截断的字符串,
        容忍解析失败比让整条 URL 检查抛异常重要。
    """
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_ip_literal(host: str) -> bool:
    """判断 host 是不是 IP 字面量。

    参数说明:
        host: 主机名。

    返回参数:
        `True` 表示是 IPv4 / IPv6 字面量。

    使用示例:
        ``_is_ip_literal("10.0.2.2")`` → ``True``

    备注信息:
        生产域名是 ``chat.shiliu153.cn``,任何裸 IP 都说明 ``API_BASE`` 没注入或注错了。
    """
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def check_urls(urls: set[str], expected: str = PRODUCTION_API_BASE) -> list[str]:
    """断言内嵌 URL 里「生产基址在」「本地地址不在」。

    参数说明:
        urls: :func:`scan_urls` 扫出的 URL 集合。
        expected: 期望的 API 基址。

    返回参数:
        违例描述列表(空列表 = 合规)。

    使用示例:
        ``problems = check_urls(urls)``

    备注信息:
        「在」判的是前缀而非全等:基址后面可能跟着完整端点
        (``.../api/v1/client-errors``),那也是正常形态;但只要基址本身在,就说明
        构建时注入了 ``--dart-define=API_BASE=<生产基址>``。
        「不在」判的是本地/裸 IP:出现即证伪 —— 那正是「裸跑 flutter build apk 落回默认值」
        的形态(``http://127.0.0.1:8000/api/v1``)。回环与模拟器别名已经按「本地地址」报过,
        不再重复计一条裸 IP(同一条 URL 挨两次骂只会让人把脚本关掉)。
    """
    problems: list[str] = []
    base_seen = any(url == expected or url.startswith(expected) for url in urls)
    if not base_seen:
        problems.append(
            f"内嵌 URL:包里没有 {expected} —— API_BASE 没注入,构建时漏了 "
            f"--dart-define=API_BASE={expected}(裸跑 flutter build apk 会落回 127.0.0.1)"
        )
    local_hits = sorted({url for url in urls if _host_of(url) in LOCAL_HOSTS})
    if local_hits:
        problems.append(
            "内嵌 URL:包里有本地/模拟器地址 " + "、".join(local_hits) + " —— 装机后必然连不上"
        )
    ip_hits = sorted(
        {
            url
            for url in urls
            if _is_ip_literal(_host_of(url)) and _host_of(url) not in LOCAL_HOSTS
        }
    )
    if ip_hits:
        problems.append(
            "内嵌 URL:包里有裸 IP 地址 " + "、".join(ip_hits) + " —— API_BASE 应当是域名 " + expected
        )
    return problems


def audit(
    apk: Path,
    aapt2: Path | None,
    expected_url: str = PRODUCTION_API_BASE,
    expected_version: str | None = None,
    pubspec: Path | None = None,
) -> Report:
    """对单个 APK 跑三项体检。

    参数说明:
        apk: 要体检的 APK。
        aapt2: ``aapt2`` 路径;``None`` 表示没找到 —— 权限与版本号两项跳过。
        expected_url: 期望的 API 基址。
        expected_version: 期望版本名;``None`` 表示读 ``pubspec``。
        pubspec: ``pubspec.yaml`` 路径;``None`` 表示本仓库那份。

    返回参数:
        :class:`Report`;``report.ok`` 为 `True` 才叫三项全过。

    使用示例:
        ``report = audit(apk, find_aapt2())``

    备注信息:
        先跑 URL(纯 ``zipfile``,不需要 SDK),再跑需要 ``aapt2`` 的两项:这样缺 SDK 的机器
        至少还能拿到 URL 结论。抛 :class:`CheckError` 表示判不出来(退出码 2)。
    """
    abi, urls = scan_urls(apk)
    report = Report(abi=abi, url_count=len(urls))
    report.problems.extend(check_urls(urls, expected_url))

    if aapt2 is None:
        report.skips.append("跳过权限检查(缺 aapt2):没法读这个包的 uses-permission")
        report.skips.append("跳过版本号检查(缺 aapt2):没法读这个包的 versionName")
        return report

    permissions = parse_permissions(dump(aapt2, apk, "permissions"))
    report.problems.extend(check_permissions(permissions))

    wanted = read_pubspec_version(pubspec) if expected_version is None else expected_version
    report.problems.extend(check_version(parse_version_name(dump(aapt2, apk, "badging")), wanted))
    return report


def _describe(apk: Path, aapt2: Path | None, report: Report) -> list[str]:
    """拼出「这次查了什么、用什么查的」摘要。

    参数说明:
        apk: 体检的 APK。
        aapt2: 用的 ``aapt2``(可为 `None`)。
        report: :func:`audit` 的结果。

    返回参数:
        待打印的文本行列表。

    使用示例:
        ``print("\\n".join(_describe(apk, aapt2, report)))``

    备注信息:
        打印 ``aapt2`` 的绝对路径与扫描用的 ABI/URL 数量:排查时最常见的两个疑问是
        「它到底用了哪个 aapt2」(多版本 SDK 并存,老版本会读不了新包)与
        「到底扫到东西没有」(0 个 URL 说明扫错了文件)。
    """
    lines = [
        f"检查 APK:{apk.as_posix()}",
        f"  aapt2:{aapt2.as_posix() if aapt2 is not None else '未找到'}",
        f"  内嵌 URL:扫 lib/{report.abi}/libapp.so,找到 {report.url_count} 个 http(s) 地址",
    ]
    lines.extend(f"  {skip}" for skip in report.skips)
    return lines


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 参数列表;``None`` 表示 ``sys.argv[1:]``。

    返回参数:
        进程退出码:0 通过 / 1 有违例 / 2 环境不对。

    使用示例:
        ``python scripts/check_release_apk.py app/build/app/outputs/flutter-apk/app-release.apk``

    备注信息:
        缺 ``aapt2`` 且 URL 检查也没问题时**仍然**返回 2:权限与版本号没查,
        「全部通过」这句话就不成立(与 ``gates.toml`` 的 ``requires`` 同口径)。
    """
    parser = argparse.ArgumentParser(
        description="release APK 体检:权限 / 内嵌 API_BASE / 版本号",
    )
    parser.add_argument("apk", help="已构建的 release APK")
    parser.add_argument("--aapt2", help="aapt2 路径(默认从 ANDROID_HOME / 常见位置 / PATH 找)")
    parser.add_argument(
        "--expect-url",
        default=PRODUCTION_API_BASE,
        help=f"期望的内嵌 API 基址(默认 {PRODUCTION_API_BASE})",
    )
    parser.add_argument("--expect-version", help="期望版本名(默认取 app/pubspec.yaml)")
    parser.add_argument("--pubspec", help="pubspec.yaml 路径(默认 app/pubspec.yaml)")
    args = parser.parse_args(argv)

    apk = Path(args.apk)
    if not apk.is_file():
        print(f"FAIL: 找不到 APK:{apk.as_posix()}", file=sys.stderr)
        return EXIT_ENVIRONMENT

    aapt2 = find_aapt2(args.aapt2)
    pubspec = Path(args.pubspec) if args.pubspec else None
    try:
        report = audit(
            apk,
            aapt2,
            expected_url=args.expect_url,
            expected_version=args.expect_version,
            pubspec=pubspec,
        )
    except CheckError as exc:
        print(f"FAIL: 判不出来 —— {exc}", file=sys.stderr)
        print(
            "这不算通过:体检读不到东西时退出码是 2。"
            f"装 SDK 或加 --aapt2;URL 那一项还可以单独看 {PITFALL_DOC}",
            file=sys.stderr,
        )
        return EXIT_ENVIRONMENT

    print("\n".join(_describe(apk, aapt2, report)))

    if report.problems:
        print(f"FAIL: {apk.as_posix()} 有 {len(report.problems)} 处不合规:")
        for problem in report.problems:
            print(f"  - {problem}")
        print(
            "修法:权限 → app/android/app/src/main/AndroidManifest.xml 补 "
            f'<uses-permission android:name="{INTERNET_PERMISSION}" />;'
            f"URL → 构建时带 --dart-define=API_BASE={args.expect_url};"
            "版本号 → 先 sync_version 再重新打包。改完必须重新构建 APK。"
        )
        return EXIT_VIOLATION

    if report.skips:
        print(
            "FAIL: 权限/版本号没查成(缺 aapt2),不能算「全部通过」。"
            "用 --aapt2 指定,或设 ANDROID_HOME 指向 Android SDK。"
        )
        return EXIT_ENVIRONMENT

    print(f"OK: {apk.as_posix()} 权限/URL/版本号 全部通过")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
