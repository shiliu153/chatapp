"""``scripts/check_release_apk.py`` 的自测(纯离线:临时目录里现造假 APK 与假 aapt2 输出)。

为什么两个方向都要钉
--------------------
这条体检的意义是「发版前 10 秒内拦住装上去就废的包」,而它自己坏掉的方式有两种,都很安静:

- **漏报**:缺 INTERNET / API_BASE 落回 ``127.0.0.1`` / 版本号还是旧的,脚本却说 OK ——
  1.0.1–1.0.14 的包就是这么一个个发出去的;
- **误报**:把 ``permission:``(本应用**定义**的权限)当成声明、把 ``.../api/v1/client-errors``
  这种正常端点当成错的、缺 ``aapt2`` 时把「没查」说成「通过」—— 人只会把脚本关掉。

需要真 ``aapt2`` 的用例在缺工具时 **skip**(不是红):CI 的 runner 不一定装 Android SDK,
而「装没装 SDK」不该决定这条门禁的值不值钱。判定逻辑本身跑在**假 dump 文本**上,
环境无关。
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts import check_release_apk as checker

#: 一份「合规」的 ``aapt2 dump permissions`` 输出(真机上的样子)。
PERMISSIONS_OK = """package: com.chatapp.chatapp_app
uses-permission: name='android.permission.INTERNET'
uses-permission: name='android.permission.RECORD_AUDIO'
permission: com.chatapp.chatapp_app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION
uses-permission: name='com.chatapp.chatapp_app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION'
permission: com.chatapp.chatapp_app.CUSTOM_DEFINED_PERMISSION
"""

#: 缺 INTERNET 的形态(1.0.1–1.0.14 全部如此)。
PERMISSIONS_MISSING = """package: com.chatapp.chatapp_app
uses-permission: name='android.permission.RECORD_AUDIO'
permission: com.chatapp.chatapp_app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION
"""

#: ``aapt2 dump badging`` 的第一行(版本号就在这行)。
BADGING = (
    "package: name='com.chatapp.chatapp_app' versionCode='16' versionName='1.0.15' "
    "platformBuildVersionName='16' platformBuildVersionCode='36'\n"
    "minSdkVersion:'24'\n"
    "targetSdkVersion:'36'\n"
)

#: 假 ``libapp.so`` 里的正常字符串(生产基址 + Flutter SDK 里那些文档链接)。
GOOD_STRINGS = (
    "https://chat.shiliu153.cn/api/v1\x00"
    "https://chat.shiliu153.cn/api/v1/client-errors\x00"
    "https://api.flutter.dev/flutter/material/Scaffold/of.html\x00"
    "https://github.com/flutter/flutter/issues/30701.\x00"
)


def build_apk(
    directory: Path,
    strings: str = GOOD_STRINGS,
    abis: tuple[str, ...] = ("arm64-v8a",),
    name: str = "fake.apk",
) -> Path:
    """在临时目录里造一个假 APK(只含假的 ``libapp.so``)。

    参数说明:
        directory: 放 APK 的目录。
        strings: ``libapp.so`` 的内容(以 ``\\x00`` 分隔的字符串池足够模拟快照)。
        abis: 造哪几个 ABI 的 ``libapp.so``。
        name: 文件名。

    返回参数:
        造出的 APK 路径。

    使用示例:
        ``apk = build_apk(self.tmp, strings="http://127.0.0.1:8000/api/v1")``

    备注信息:
        不需要真 APK:被测的三项里,URL 那项读的是 zip 里的 ``libapp.so`` 字节,
        权限与版本号那两项读的是 ``aapt2`` 的输出文本(由假 aapt2 提供)。
    """
    apk = directory / name
    with zipfile.ZipFile(apk, "w") as archive:
        for abi in abis:
            archive.writestr(checker.LIBAPP_TEMPLATE.format(abi=abi), strings.encode("utf-8"))
    return apk


def write_fake_aapt2(directory: Path, permissions: str = PERMISSIONS_OK) -> Path:
    """造一个假的 ``aapt2``(打印固定的 dump 文本)。

    参数说明:
        directory: 放脚本的目录。
        permissions: ``dump permissions`` 要打印的内容。

    返回参数:
        脚本路径(已 ``chmod +x``)。

    使用示例:
        ``aapt2 = write_fake_aapt2(self.tmp)``

    备注信息:
        只在 POSIX 上可用(用 ``/bin/sh``);调用方负责 skip。
        参数版式照真 ``aapt2``:``aapt2 dump <what> <apk>``。
    """
    script = directory / "fake-aapt2"
    body = "\n".join(
        [
            "#!/bin/sh",
            'case "$2" in',
            "  permissions) cat <<'EOF'",
            permissions.rstrip("\n"),
            "EOF",
            "    ;;",
            "  badging) cat <<'EOF'",
            BADGING.rstrip("\n"),
            "EOF",
            "    ;;",
            "  *) echo \"unsupported: $2\" >&2; exit 9 ;;",
            "esac",
            "",
        ]
    )
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


class TempDirTestCase(unittest.TestCase):
    """公共脚手架:一个临时目录。"""

    def setUp(self):
        """建临时目录,测试结束自动删。"""
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_obj.name)
        self.addCleanup(self.tmp_obj.cleanup)


class ScanUrlsTests(TempDirTestCase):
    """扫 ``lib/<abi>/libapp.so`` 这一半。"""

    def test_finds_production_base_and_flutter_links(self):
        """扫出的集合里既有生产基址,也有快照里自带的上游文档链接。"""
        abi, urls = checker.scan_urls(build_apk(self.tmp))
        self.assertEqual(abi, "arm64-v8a")
        self.assertIn(checker.PRODUCTION_API_BASE, urls)
        self.assertTrue(any("api.flutter.dev" in url for url in urls))

    def test_strips_trailing_punctuation(self):
        """快照里以 ``.`` 收尾的链接被剥成干净 URL(否则「裸 IP / 域名」判定会带尾巴)。"""
        _, urls = checker.scan_urls(build_apk(self.tmp))
        self.assertIn("https://github.com/flutter/flutter/issues/30701", urls)
        self.assertNotIn("https://github.com/flutter/flutter/issues/30701.", urls)

    def test_prefers_arm64_when_several_abis(self):
        """三个 ABI 都在时扫 arm64-v8a —— 只扫一份,不必解压二十多兆。"""
        abi, _ = checker.scan_urls(build_apk(self.tmp, abis=("x86_64", "armeabi-v7a", "arm64-v8a")))
        self.assertEqual(abi, "arm64-v8a")

    def test_falls_back_to_armeabi_v7a(self):
        """没有 arm64 时退回 armeabi-v7a。"""
        abi, urls = checker.scan_urls(build_apk(self.tmp, abis=("armeabi-v7a",)))
        self.assertEqual(abi, "armeabi-v7a")
        self.assertIn(checker.PRODUCTION_API_BASE, urls)

    def test_falls_back_to_x86_64(self):
        """只剩 x86_64 也要能扫(emu 包)。"""
        abi, _ = checker.scan_urls(build_apk(self.tmp, abis=("x86_64",)))
        self.assertEqual(abi, "x86_64")

    def test_no_libapp_is_an_environment_error(self):
        """包里没有 ``libapp.so`` → ``CheckError``(拿错产物,不能当成「没违例」)。"""
        apk = self.tmp / "empty.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("lib/arm64-v8a/libflutter.so", b"MZ")
        with self.assertRaises(checker.CheckError) as raised:
            checker.scan_urls(apk)
        self.assertIn("libapp.so", str(raised.exception))

    def test_non_zip_is_an_environment_error(self):
        """不是 zip 的文件 → ``CheckError``,不是 `False`。"""
        broken = self.tmp / "broken.apk"
        broken.write_bytes(b"not a zip at all")
        with self.assertRaises(checker.CheckError) as raised:
            checker.scan_urls(broken)
        self.assertIn("不是可读的 APK", str(raised.exception))


class CheckUrlsTests(unittest.TestCase):
    """「生产基址在」「本地地址不在」这一半。"""

    def test_good_bundle_passes(self):
        """生产基址 + 上游文档链接 → 无违例。"""
        urls = {
            checker.PRODUCTION_API_BASE,
            "https://chat.shiliu153.cn/api/v1/client-errors",
            "https://api.flutter.dev/flutter/material/Scaffold/of.html",
        }
        self.assertEqual(checker.check_urls(urls), [])

    def test_endpoint_under_base_counts_as_base(self):
        """只有 ``.../api/v1/client-errors`` 没有裸基址时,也算注入了(base 是前缀)。"""
        self.assertEqual(
            checker.check_urls({"https://chat.shiliu153.cn/api/v1/client-errors"}), []
        )

    def test_missing_production_base_is_reported_with_the_fix(self):
        """没有生产基址 → 违例里点名 ``--dart-define=API_BASE=`` 这条修法。"""
        problems = checker.check_urls({"https://pub.dev/"})
        self.assertEqual(len(problems), 1)
        self.assertIn("没有", problems[0])
        self.assertIn("--dart-define=API_BASE=", problems[0])

    def test_localhost_loopback_is_reported(self):
        """``127.0.0.1`` 在包里 → 违例(裸跑 ``flutter build apk`` 的默认值)。"""
        urls = {checker.PRODUCTION_API_BASE, "http://127.0.0.1:8000/api/v1"}
        problems = checker.check_urls(urls)
        self.assertEqual(len(problems), 1)
        self.assertIn("127.0.0.1", problems[0])

    def test_emulator_alias_is_reported(self):
        """``10.0.2.2``(安卓模拟器看到的宿主)→ 违例。"""
        urls = {checker.PRODUCTION_API_BASE, "http://10.0.2.2:8000/api/v1"}
        problems = checker.check_urls(urls)
        self.assertEqual(len(problems), 1)
        self.assertIn("10.0.2.2", problems[0])

    def test_bare_ip_is_reported(self):
        """任何裸 IP(哪怕不是回环)→ 违例:生产基址必须是域名。"""
        urls = {checker.PRODUCTION_API_BASE, "https://203.0.113.7/api/v1"}
        problems = checker.check_urls(urls)
        self.assertEqual(len(problems), 1)
        self.assertIn("裸 IP", problems[0])

    def test_localhost_name_is_reported(self):
        """``localhost`` 也算本地地址。"""
        problems = checker.check_urls({checker.PRODUCTION_API_BASE, "http://localhost:8000/api/v1"})
        self.assertIn("localhost", problems[0])

    def test_lookalike_domain_does_not_satisfy_the_base(self):
        """别的域名(前缀相近)不能冒充生产基址。"""
        problems = checker.check_urls({"https://chat.shiliu153.cn.evil.example/api/v1"})
        self.assertTrue(any("没有" in problem for problem in problems))


class PermissionsTests(unittest.TestCase):
    """权限那一半(纯文本判定)。"""

    def test_parses_uses_permission_lines(self):
        """``uses-permission:`` 行被取出来;只有 ``permission:`` 行(本应用**定义**的)不算。"""
        permissions = checker.parse_permissions(PERMISSIONS_OK)
        self.assertIn(checker.INTERNET_PERMISSION, permissions)
        self.assertIn("android.permission.RECORD_AUDIO", permissions)
        self.assertNotIn("com.chatapp.chatapp_app.CUSTOM_DEFINED_PERMISSION", permissions)

    def test_sdk_23_form_counts(self):
        """``uses-permission-sdk-23:`` 同样把权限打进包,要算声明。"""
        text = "uses-permission-sdk-23: name='android.permission.INTERNET'\n"
        self.assertIn(checker.INTERNET_PERMISSION, checker.parse_permissions(text))

    def test_missing_internet_is_reported_with_manifest_hint(self):
        """缺 INTERNET → 违例指向 ``main/AndroidManifest.xml`` 与踩坑手册。"""
        problems = checker.check_permissions(checker.parse_permissions(PERMISSIONS_MISSING))
        self.assertEqual(len(problems), 1)
        self.assertIn(checker.INTERNET_PERMISSION, problems[0])
        self.assertIn(checker.PITFALL_DOC, problems[0])

    def test_definition_line_alone_does_not_satisfy(self):
        """只有 ``permission:`` 行(定义)而无 ``uses-permission:`` → 仍然违例。"""
        text = "permission: android.permission.INTERNET\n"
        self.assertTrue(checker.check_permissions(checker.parse_permissions(text)))

    def test_internet_present_passes(self):
        """有 INTERNET → 无违例。"""
        self.assertEqual(checker.check_permissions({checker.INTERNET_PERMISSION}), [])


class VersionTests(unittest.TestCase):
    """版本号那一半。"""

    def test_parses_version_name(self):
        """从 ``package:`` 行取 ``versionName``。"""
        self.assertEqual(checker.parse_version_name(BADGING), "1.0.15")

    def test_missing_version_name_returns_none(self):
        """输出里没有这一项 → `None`(由判定侧单独报违例)。"""
        self.assertIsNone(checker.parse_version_name("package: name='x'\n"))

    def test_match_passes(self):
        """包里的版本名 == pubspec 版本名 → 无违例。"""
        self.assertEqual(checker.check_version("1.0.15", "1.0.15"), [])

    def test_mismatch_is_reported(self):
        """包里是旧版本号 → 违例里两个值都要出现。"""
        problems = checker.check_version("1.0.14", "1.0.15")
        self.assertEqual(len(problems), 1)
        self.assertIn("1.0.14", problems[0])
        self.assertIn("1.0.15", problems[0])

    def test_unreadable_version_is_a_violation_not_a_pass(self):
        """读不到版本名不能当成「没差异」。"""
        self.assertTrue(checker.check_version(None, "1.0.15"))


class PubspecTests(TempDirTestCase):
    """``app/pubspec.yaml`` 的版本名读取。"""

    def write_pubspec(self, text: str) -> Path:
        """写一份假 pubspec。

        参数说明:
            text: 文件内容。

        返回参数:
            写出的路径。

        使用示例:
            ``self.write_pubspec("version: 1.0.15+16\\n")``

        备注信息:
            只为读版本号,别的内容不解析。
        """
        path = self.tmp / "pubspec.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_strips_build_number(self):
        """``1.0.15+16`` → ``1.0.15``(构建号不进 APK 的 versionName 比对)。"""
        pubspec = self.write_pubspec("version: 1.0.15+16\n")
        self.assertEqual(checker.read_pubspec_version(pubspec), "1.0.15")

    def test_ignores_other_lines(self):
        """``environment:`` 之类的行不会干扰。"""
        text = "name: chatapp_app\nenvironment:\n  sdk: ^3.0.0\nversion: 1.2.3+4\n"
        self.assertEqual(checker.read_pubspec_version(self.write_pubspec(text)), "1.2.3")

    def test_missing_file_raises(self):
        """文件不存在 → ``CheckError``。"""
        with self.assertRaises(checker.CheckError):
            checker.read_pubspec_version(self.tmp / "nope.yaml")

    def test_garbage_raises(self):
        """没有版本号行 → ``CheckError``(判不出来不等于合规)。"""
        with self.assertRaises(checker.CheckError):
            checker.read_pubspec_version(self.write_pubspec("name: x\n"))

    def test_repository_pubspec_is_parseable(self):
        """真仓库的 ``app/pubspec.yaml`` 现在读得出版本号。"""
        self.assertRegex(checker.read_pubspec_version(), r"^\d+\.\d+\.\d+$")


class FindAapt2Tests(TempDirTestCase):
    """``aapt2`` 查找:显式参数 / ANDROID_HOME / 多版本取新 / 都没有。"""

    def make_sdk(self, versions: tuple[str, ...], suffix: str = "") -> Path:
        """造一个假 SDK 目录树。

        参数说明:
            versions: ``build-tools`` 下的版本目录名。
            suffix: ``aapt2`` 的后缀(用 ``.exe`` 模拟 Windows SDK)。

        返回参数:
            SDK 根目录。

        使用示例:
            ``sdk = self.make_sdk(("34.0.0", "36.0.0"), suffix=".exe")``

        备注信息:
            文件只要能 `is_file()` 即可,不要求可执行 —— 查找逻辑只看存在性。
        """
        sdk = self.tmp / "sdk"
        for version in versions:
            binary = sdk / "build-tools" / version / f"aapt2{suffix}"
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
        return sdk

    def test_explicit_path_wins(self):
        """``--aapt2`` 给了就用它,不去翻 SDK。"""
        explicit = self.tmp / "my-aapt2"
        explicit.write_text("#!/bin/sh\n", encoding="utf-8")
        self.assertEqual(checker.find_aapt2(str(explicit), env={"ANDROID_HOME": "/nope"}), explicit)

    def test_android_home_is_used(self):
        """``ANDROID_HOME/build-tools/<版本>/aapt2`` 会被找到。"""
        sdk = self.make_sdk(("36.0.0",))
        with mock.patch.object(checker, "sdk_roots", return_value=[sdk]):
            with mock.patch.object(checker.shutil, "which", return_value=None):
                found = checker.find_aapt2(None, env={})
        self.assertEqual(found, sdk / "build-tools" / "36.0.0" / "aapt2")

    def test_newest_build_tools_wins(self):
        """多版本并存取版本号最大的:老 aapt2 读新包会报``failed opening zip``。"""
        sdk = self.make_sdk(("33.0.1", "36.0.0", "34.0.0"))
        with mock.patch.object(checker, "sdk_roots", return_value=[sdk]):
            with mock.patch.object(checker.shutil, "which", return_value=None):
                found = checker.find_aapt2(None, env={})
        self.assertEqual(found, sdk / "build-tools" / "36.0.0" / "aapt2")

    def test_windows_exe_is_recognised(self):
        """Windows SDK 里的 ``aapt2.exe`` 也认(WSL 里常见的形态)。"""
        sdk = self.make_sdk(("36.0.0",), suffix=".exe")
        with mock.patch.object(checker, "sdk_roots", return_value=[sdk]):
            with mock.patch.object(checker.shutil, "which", return_value=None):
                found = checker.find_aapt2(None, env={})
        self.assertEqual(found, sdk / "build-tools" / "36.0.0" / "aapt2.exe")

    def test_nothing_found_returns_none(self):
        """哪儿都没有 → `None`(由 ``main`` 判成「跳过 + 退出码 2」,不在这里抛)。"""
        with mock.patch.object(checker, "sdk_roots", return_value=[]):
            with mock.patch.object(checker.shutil, "which", return_value=None):
                self.assertIsNone(checker.find_aapt2(None, env={}))

    def test_sdk_roots_reads_env(self):
        """环境变量里的 SDK 根目录排在前面。"""
        roots = checker.sdk_roots({"ANDROID_HOME": "/sdk-a", "ANDROID_SDK_ROOT": "/sdk-b"})
        self.assertEqual(roots[:2], [Path("/sdk-a"), Path("/sdk-b")])

    def test_missing_binary_raises_on_dump(self):
        """``--aapt2`` 指向不存在的文件时 ``dump`` 抛 ``CheckError``。"""
        with self.assertRaises(checker.CheckError):
            checker.dump(self.tmp / "nope", self.tmp / "x.apk", "permissions")


class HostParsingTests(unittest.TestCase):
    """URL → host 的两个小工具(裸 IP 判定全靠它们)。"""

    def test_host_is_lowercased_without_port(self):
        """带端口、带路径的 URL 取到干净的 host。"""
        self.assertEqual(checker._host_of("http://10.0.2.2:8000/api/v1"), "10.0.2.2")
        self.assertEqual(checker._host_of("HTTPS://Chat.ShiLiu153.cn/api/v1"), "chat.shiliu153.cn")

    def test_broken_url_has_empty_host(self):
        """截断的字符串不抛异常,返回空 host(它不是违例,只是没扫出东西)。"""
        self.assertEqual(checker._host_of("https://"), "")

    def test_ip_literal_detection(self):
        """IPv4/IPv6 字面量认得出,域名认不出。"""
        self.assertTrue(checker._is_ip_literal("127.0.0.1"))
        self.assertTrue(checker._is_ip_literal("::1"))
        self.assertFalse(checker._is_ip_literal("chat.shiliu153.cn"))
        self.assertFalse(checker._is_ip_literal(""))


@unittest.skipIf(
    os.name != "posix" or shutil.which("sh") is None,
    "假 aapt2 是 /bin/sh 脚本,只在 POSIX 上跑;真 SDK 的用例本来就靠 skip 兼容 CI",
)
class MainTests(TempDirTestCase):
    """端到端:假 APK + 假 aapt2 → 退出码 / 输出。"""

    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        """跑一次 ``main``,把标准输出与标准错误抓下来。

        参数说明:
            argv: 命令行参数。

        返回参数:
            ``(退出码, stdout, stderr)``。

        使用示例:
            ``code, out, err = self.run_main([str(apk)])``

        备注信息:
            用 ``contextlib.redirect_*`` 而不是起子进程:自测要断言的是判定结果,
            不是 ``python`` 的启动行为。
        """
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = checker.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_good_apk_passes(self):
        """合规的包 → 退出码 0,输出那一行 ``OK: … 权限/URL/版本号 全部通过``。"""
        apk = build_apk(self.tmp)
        aapt2 = write_fake_aapt2(self.tmp)
        code, out, _ = self.run_main(
            [str(apk), "--aapt2", str(aapt2), "--expect-version", "1.0.15"]
        )
        self.assertEqual(code, checker.EXIT_OK)
        self.assertIn("OK:", out)
        self.assertIn("权限/URL/版本号 全部通过", out)

    def test_local_api_base_fails(self):
        """``API_BASE`` 落回 ``127.0.0.1`` → 退出码 1,报错带修法。"""
        apk = build_apk(self.tmp, strings="http://127.0.0.1:8000/api/v1\x00")
        aapt2 = write_fake_aapt2(self.tmp)
        code, out, _ = self.run_main(
            [str(apk), "--aapt2", str(aapt2), "--expect-version", "1.0.15"]
        )
        self.assertEqual(code, checker.EXIT_VIOLATION)
        self.assertIn("FAIL:", out)
        self.assertIn("--dart-define=API_BASE=", out)

    def test_missing_internet_fails(self):
        """包缺 INTERNET → 退出码 1,报错指向 main 清单。"""
        apk = build_apk(self.tmp)
        aapt2 = write_fake_aapt2(self.tmp, permissions=PERMISSIONS_MISSING)
        code, out, _ = self.run_main(
            [str(apk), "--aapt2", str(aapt2), "--expect-version", "1.0.15"]
        )
        self.assertEqual(code, checker.EXIT_VIOLATION)
        self.assertIn("AndroidManifest.xml", out)

    def test_wrong_version_fails(self):
        """包里版本号与 pubspec 不一致 → 退出码 1。"""
        apk = build_apk(self.tmp)
        aapt2 = write_fake_aapt2(self.tmp)
        code, out, _ = self.run_main(
            [str(apk), "--aapt2", str(aapt2), "--expect-version", "1.0.16"]
        )
        self.assertEqual(code, checker.EXIT_VIOLATION)
        self.assertIn("1.0.15", out)

    def test_missing_aapt2_is_not_a_silent_pass(self):
        """缺 ``aapt2`` → 明说跳过、退出码 2(不能输出 OK)。"""
        apk = build_apk(self.tmp)
        with mock.patch.object(checker, "find_aapt2", return_value=None):
            code, out, _ = self.run_main([str(apk), "--expect-version", "1.0.15"])
        self.assertEqual(code, checker.EXIT_ENVIRONMENT)
        self.assertIn("跳过权限检查", out)
        self.assertIn("跳过版本号检查", out)
        self.assertNotIn("OK:", out)  # 没有 OK 行 = 没有冒充「全部通过」

    def test_missing_apk_file_exits_environment(self):
        """APK 路径不存在 → 退出码 2(环境不对,而不是「有违例」)。"""
        code, _, err = self.run_main([str(self.tmp / "nope.apk")])
        self.assertEqual(code, checker.EXIT_ENVIRONMENT)
        self.assertIn("找不到 APK", err)

    def test_unreadable_apk_exits_environment(self):
        """APK 不是 zip → 退出码 2 且说明「这不算通过」。"""
        broken = self.tmp / "broken.apk"
        broken.write_bytes(b"nope")
        code, _, err = self.run_main([str(broken), "--aapt2", str(write_fake_aapt2(self.tmp))])
        self.assertEqual(code, checker.EXIT_ENVIRONMENT)
        self.assertIn("判不出来", err)


class AuditTests(TempDirTestCase):
    """:func:`checker.audit` 的组合行为(假 aapt2,不需要真 SDK)。"""

    def test_report_records_abi_and_url_count(self):
        """报告里带上扫描的 ABI 与 URL 数量(0 个说明扫错了文件)。"""
        report = checker.audit(build_apk(self.tmp), None, expected_version="1.0.15")
        self.assertEqual(report.abi, "arm64-v8a")
        self.assertGreater(report.url_count, 0)
        self.assertFalse(report.ok)

    def test_all_three_checks_with_fake_aapt2(self):
        """三项都查、都过 → ``ok``;``problems`` 与 ``skips`` 都空。"""
        apk = build_apk(self.tmp)
        report = checker.audit(apk, write_fake_aapt2(self.tmp), expected_version="1.0.15")
        self.assertEqual(report.problems, [])
        self.assertEqual(report.skips, [])
        self.assertTrue(report.ok)

    def test_skip_is_not_ok(self):
        """缺 aapt2 时 URL 过了也不算 ok。"""
        report = checker.audit(build_apk(self.tmp), None, expected_version="1.0.15")
        self.assertEqual(len(report.skips), 2)
        self.assertFalse(report.ok)


class DocumentationTests(unittest.TestCase):
    """文档里那条构建命令必须与本脚本的期望基址一致(两处漂移 = 体检永远红或永远假绿)。"""

    def test_expected_url_matches_documented_build_command(self):
        """``docs/standards/dev-commands.md`` 的出包命令里带的就是这个基址。"""
        doc = checker.REPO_ROOT / "docs" / "standards" / "dev-commands.md"
        text = doc.read_text(encoding="utf-8")
        self.assertIn(f"--dart-define=API_BASE={checker.PRODUCTION_API_BASE}", text)

    def test_release_checklist_points_at_this_script(self):
        """发版清单 §3 步骤 3 的完成标志里有这条命令。"""
        text = (checker.REPO_ROOT / "docs" / "ops" / "release.md").read_text(encoding="utf-8")
        self.assertTrue(
            "python scripts/check_release_apk.py" in text,
            "docs/ops/release.md 的发版清单里没有这条命令 —— 清单是唯一的发版流程 owner",
        )


if __name__ == "__main__":
    unittest.main()
