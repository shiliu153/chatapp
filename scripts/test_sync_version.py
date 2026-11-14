"""``scripts/sync_version.py`` 的自测(标准库 unittest,不依赖 Django)。

2026-11-14(治理第 5 节)之后,这个脚本只剩**接线**:读 / 写 / 比对原语在
``scripts/lib/version.py``,发版记录在 ``scripts/lib/docs.py``,两者的正反用例都在
``scripts/test_lib.py``。这里守的是**它确实接上了 lib**,以及 ``--check`` 对当前仓库给 0 ——
如果哪天有人把常量或正则又抄回本文件,「同一条事实只有一份实现」就悄悄失效了。

设计要点:
    版本号门禁自己也可能坏(正则写错 → 永远返回一致 → 门禁静默失效),所以 ``test_lib``
    用临时目录造三份最小文件验证「读 / 写 / 比对」;本文件只验证接线与真实仓库的一致性。

文件信息:
    文件名称          scripts/test_sync_version.py
    项目名称          chat_app / 工程脚本
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11
    适用平台          Linux x86_64（本地与 CI）
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import unittest

from scripts import sync_version
from scripts.lib import docs, version


class WiringTests(unittest.TestCase):
    """``sync_version`` 必须只用共享实现,不许自带常量 / 正则。"""

    def test_imports_shared_lib(self):
        """版本号与发版记录都来自 ``scripts/lib/``(同一份实现,不反向 import)。

        参数说明:
            无。
        """
        self.assertIs(sync_version.version, version)
        self.assertIs(sync_version.docs, docs)

    def test_does_not_redefine_shared_constants(self):
        """常量 / 正则不许抄回本文件 —— 抄回来就又是两份实现(§4 C7 的复发形态)。

        参数说明:
            无。
        """
        for name in (
            "DEFAULT_REPO",
            "DEFAULT_TOKEN_FILE",
            "API",
            "PUBSPEC",
            "APP_INFO",
            "WEB_PACKAGE",
            "PUBSPEC_VERSION_RE",
            "PUBSPEC_VERSION_BUILD_RE",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(sync_version, name))


class CliTests(unittest.TestCase):
    """``--check`` 对当前仓库的口径。"""

    def test_main_check_returns_zero_when_consistent(self):
        """三处版本号一致 + 发版记录有当前版本这一条 → 退出码 0。

        参数说明:
            无。
        """
        self.assertEqual(sync_version.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
