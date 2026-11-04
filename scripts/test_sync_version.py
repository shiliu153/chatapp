"""``scripts/sync_version.py`` 的自测(标准库 unittest,不依赖 Django)。

设计要点:
    版本号门禁自己也可能坏(正则写错 → 永远返回一致 → 门禁静默失效),所以这里用
    临时目录造三份最小文件来验证「读 / 写 / 比对」三件事,而不是直接读仓库真文件。
"""

import tempfile
import unittest
from pathlib import Path

from scripts import sync_version

PUBSPEC_BODY = """name: chatapp_app
description: 演示
version: 1.0.4+5
environment:
  sdk: '>=3.0.0 <4.0.0'
"""

APP_INFO_BODY = """/// 应用展示信息。
const appDisplayName = '心跳';
const appVersion = '1.0.4';
const appIcpNumber = '';
"""

WEB_PACKAGE_BODY = """{
  "name": "chatapp-web",
  "version": "1.0.4",
  "scripts": {}
}
"""


class SyncVersionTests(unittest.TestCase):
    """三处版本号的读取、写回与比对。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.pubspec = root / "pubspec.yaml"
        self.app_info = root / "app_info.dart"
        self.web_package = root / "package.json"
        self.pubspec.write_text(PUBSPEC_BODY, encoding="utf-8")
        self.app_info.write_text(APP_INFO_BODY, encoding="utf-8")
        self.web_package.write_text(WEB_PACKAGE_BODY, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_reads_version_name_without_build_number(self):
        self.assertEqual(sync_version.read_pubspec_version(self.pubspec), "1.0.4")

    def test_reads_both_client_versions(self):
        self.assertEqual(sync_version.read_app_info_version(self.app_info), "1.0.4")
        self.assertEqual(sync_version.read_web_version(self.web_package), "1.0.4")

    def test_consistent_files_have_no_mismatch(self):
        self.assertEqual(sync_version.collect_mismatches(
            self.pubspec, self.app_info, self.web_package), [])

    def test_mismatch_is_reported(self):
        self.app_info.write_text(APP_INFO_BODY.replace("1.0.4", "1.0.3"), encoding="utf-8")
        problems = sync_version.collect_mismatches(
            self.pubspec, self.app_info, self.web_package)
        self.assertTrue(any("app_info.dart" in problem for problem in problems), problems)
        self.assertTrue(any("sync_version.py --write" in problem for problem in problems))

    def test_write_updates_both_files_and_keeps_rest(self):
        self.pubspec.write_text(PUBSPEC_BODY.replace("1.0.4", "1.1.0"), encoding="utf-8")
        self.assertTrue(sync_version.write_app_info_version("1.1.0", self.app_info))
        self.assertTrue(sync_version.write_web_version("1.1.0", self.web_package))

        self.assertEqual(sync_version.collect_mismatches(
            self.pubspec, self.app_info, self.web_package), [])
        # 只改版本号那一行,其余内容(含构建号、脚本)原样保留
        self.assertIn("const appDisplayName = '心跳';", self.app_info.read_text(encoding="utf-8"))
        self.assertIn('"scripts": {}', self.web_package.read_text(encoding="utf-8"))
        self.assertIn("version: 1.1.0+5", self.pubspec.read_text(encoding="utf-8"))

    def test_write_is_noop_when_already_matching(self):
        self.assertFalse(sync_version.write_app_info_version("1.0.4", self.app_info))
        self.assertFalse(sync_version.write_web_version("1.0.4", self.web_package))

    def test_main_check_returns_zero_when_consistent(self):
        self.assertEqual(sync_version.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
