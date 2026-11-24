"""``scripts/check_app_manifest.py`` 的自测(纯离线,临时目录里造三份清单)。

进 CI 的 `contract` 轨。它守的是「release 包必须声明 INTERNET」这一条,而这类门禁
两个方向都会坏:

- **少报**:权限又被挪回 ``debug/`` 或合并冲突时丢掉,门禁却说合规 —— 发版后整包没网,
  症状要到手机上才看见(1.0.1–1.0.14 全部踩过);
- **多报**:被 ``<!-- -->`` 注释掉的声明被当成声明、别的权限被误认、debug/profile 缺文件
  被当成违例 —— 人只能把门禁关掉。

两边都由下面钉住。
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts import check_app_manifest

#: 一份最小的合法 main 清单,`internet=True` 时带 INTERNET 声明。
MANIFEST = """<manifest xmlns:android="http://schemas.android.com/apk/res/android">
{comment}    {internet}<uses-permission android:name="android.permission.RECORD_AUDIO" />
    <application android:label="demo" />
</manifest>
"""

INTERNET_LINE = '<uses-permission android:name="android.permission.INTERNET" />'


def manifest_text(internet: bool = True, comment: str = "") -> str:
    """拼一份清单文本。

    参数说明:
        internet: 是否声明 INTERNET。
        comment: 前置注释文本(用来造「注释掉的声明」样本)。

    返回参数:
        清单 XML 文本。

    使用示例:
        ``manifest_text(internet=False, comment="<!-- ")``

    备注信息:
        永远带一条**别的**权限(RECORD_AUDIO),这样「把别的 uses-permission 当成 INTERNET」
        这类误判才会被测到。
    """
    return MANIFEST.format(comment=comment, internet=INTERNET_LINE + "\n    " if internet else "")


class ManifestTestCase(unittest.TestCase):
    """公共脚手架:临时目录 + 按需写清单。"""

    def setUp(self):
        """建一个临时仓库根,并接管模块里的仓库根常量(让 ``main()`` 也看临时目录)。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._saved = check_app_manifest.REPO_ROOT
        check_app_manifest.REPO_ROOT = self.root
        self.addCleanup(setattr, check_app_manifest, "REPO_ROOT", self._saved)
        self.addCleanup(self.tmp.cleanup)

    def write(self, relative: str, text: str) -> Path:
        """把一份清单写进临时仓库。

        参数说明:
            relative: 相对 ``app/android/app/src`` 的路径。
            text: 文件内容。

        返回参数:
            写出的文件路径。

        使用示例:
            ``self.write("main/AndroidManifest.xml", manifest_text())``

        备注信息:
            父目录不存在时自动创建;debug/profile 不写就不会出现在判定里。
        """
        path = check_app_manifest.manifest_path(relative, self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def call_main(self, argv: list[str]) -> tuple[int, str]:
        """跑一次 ``main()`` 并收集退出码与 stdout。

        参数说明:
            argv: 命令行参数(不含程序名)。

        返回参数:
            ``(退出码, stdout)``。

        使用示例:
            ``self.call_main(["--check"])``

        备注信息:
            stderr 不收集 —— 本脚本的判定全在 stdout 上,stderr 只留给 argparse。
        """
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_app_manifest.main(argv)
        return code, out.getvalue()


class GreenTests(ManifestTestCase):
    """合规的清单必须通过 —— 误报会把人逼着把门禁关掉。"""

    def test_main_declaring_internet_passes(self):
        """main 声明了 INTERNET 就够,debug/profile 有没有都不影响。"""
        self.write("main/AndroidManifest.xml", manifest_text())
        self.assertEqual(check_app_manifest.audit(self.root), [])
        self.assertEqual(self.call_main([])[0], 0)

    def test_sdk23_variant_counts(self):
        """``uses-permission-sdk-23`` 同样把权限落进包里,必须算声明。"""
        self.write(
            "main/AndroidManifest.xml",
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '  <uses-permission-sdk-23 android:name="android.permission.INTERNET" />\n'
            "</manifest>\n",
        )
        self.assertEqual(check_app_manifest.audit(self.root), [])

    def test_success_message_names_the_file(self):
        """通过时要点名 main 清单与「debug/profile 不代替 main」,否则日志看不出守的是什么。"""
        self.write("main/AndroidManifest.xml", manifest_text())
        code, out = self.call_main([])
        self.assertEqual(code, 0)
        self.assertIn("main/AndroidManifest.xml", out)
        self.assertIn("热重载", out)


class RedTests(ManifestTestCase):
    """缺权限必须判红,且红得能照着修。"""

    def test_missing_internet_in_main_is_red(self):
        """main 没有 INTERNET → 退出码 1,提示里有「缺 INTERNET」与踩坑手册。"""
        self.write("main/AndroidManifest.xml", manifest_text(internet=False))
        code, out = self.call_main([])
        self.assertEqual(code, 1)
        self.assertIn("缺 INTERNET", out)
        self.assertIn(check_app_manifest.PITFALL_DOC, out)
        self.assertIn("release 包会完全没网", out)

    def test_other_permission_is_not_internet(self):
        """别的 uses-permission 不能顶替 INTERNET(每份样本都带 RECORD_AUDIO)。"""
        self.write("main/AndroidManifest.xml", manifest_text(internet=False))
        problems = check_app_manifest.audit(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("android.permission.INTERNET", problems[0])

    def test_commented_out_declaration_does_not_count(self):
        """被注释掉的声明不算声明 —— 正则扫文本会在这里骗过门禁。"""
        self.write(
            "main/AndroidManifest.xml",
            manifest_text(
                internet=False,
                comment="<!-- 挪回 debug 时把这一行注释掉了:\n    " + INTERNET_LINE + "\n    -->\n    ",
            ),
        )
        self.assertEqual(self.call_main([])[0], 1)

    def test_debug_only_declaration_is_named(self):
        """main 缺、debug/profile 有时:判红并说明那两份只服务热重载。"""
        self.write("main/AndroidManifest.xml", manifest_text(internet=False))
        self.write("debug/AndroidManifest.xml", manifest_text())
        self.write("profile/AndroidManifest.xml", manifest_text())
        problems = check_app_manifest.audit(self.root)
        self.assertEqual(len(problems), 2)
        self.assertIn("debug/AndroidManifest.xml", problems[1])
        self.assertIn("profile/AndroidManifest.xml", problems[1])
        self.assertIn("热重载", problems[1])

    def test_missing_main_manifest_is_red(self):
        """main 清单不存在(路径改了 / 被删了)必须判红,不能当成合规。"""
        problems = check_app_manifest.audit(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("找不到清单", problems[0])
        self.assertEqual(self.call_main([])[0], 1)

    def test_broken_xml_is_red(self):
        """清单不是合法 XML:判不出来就是违例(fail-closed)。"""
        self.write("main/AndroidManifest.xml", "<manifest><uses-permission")
        problems = check_app_manifest.audit(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("不是合法 XML", problems[0])
        self.assertEqual(self.call_main([])[0], 1)


class ListTests(ManifestTestCase):
    """``--list`` 只打印、不判红。"""

    def test_list_prints_every_manifest(self):
        """三份清单各一行,缺权限也只标 NONE,退出码仍为 0。"""
        self.write("main/AndroidManifest.xml", manifest_text(internet=False))
        self.write("debug/AndroidManifest.xml", manifest_text())
        code, out = self.call_main(["--list"])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 3)
        self.assertIn("NONE", out)
        self.assertIn("OK", out)

    def test_list_survives_broken_manifest(self):
        """有一份读不出来时 ``--list`` 标 MISS 并继续打完剩下两份。"""
        self.write("main/AndroidManifest.xml", "<manifest>")
        self.write("profile/AndroidManifest.xml", manifest_text())
        code, out = self.call_main(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("MISS", out)
        lines = check_app_manifest.render_list(self.root)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("MISS"))


class RealManifestTests(unittest.TestCase):
    """真实仓库的清单必须过 —— 这条防的是「脚本对了但仓库里又丢了」。"""

    def test_repository_main_manifest_declares_internet(self):
        """``app/android/app/src/main/AndroidManifest.xml`` 当前合规。"""
        problems = check_app_manifest.audit(Path(check_app_manifest.REPO_ROOT))
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
