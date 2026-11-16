#!/usr/bin/env python3
"""``scripts/gen_web_schema.py``(契约指纹门禁)的自测。

两个方向都不能静默:

- **漏报** = 改了 openapi.yml 却没重生成 schema.d.ts 仍然绿 —— 那正是本门禁存在的理由
  (2026-11-16 PR #376 红在 ``web`` 轨上的那个缝);
- **误报** = 内容没变却因为行尾(CRLF / LF)或无关字节被判红 —— 误报会把人逼着把门禁关掉,
  所以「同一份契约的 CRLF 版本与 LF 版本指纹相同」单独钉一条。

生成器本身(``npx openapi-typescript``)要 Node 与网络,不在自测里跑:``--check`` 是纯 Python,
门禁跑的也只是 ``--check``;生成路径的正确性由 ``scripts/stacks/web.sh`` 在真机上验证。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import gen_web_schema as gen


class TempRepo:
    """最小临时仓库:只有契约与生成物两个文件。

    用上下文管理器而不是 ``setUp``/``tearDown``,是因为每个用例要造不同的组合
    (契约缺失 / 生成物缺失 / 指纹过期),共用一个 fixture 反而要来回清理。
    """

    def __init__(self, openapi: str | None = "openapi: 3.0.0\n", stamp: str | None = None):
        """建目录并写入给定的契约与指纹。

        参数说明:
            openapi: 契约内容;``None`` 表示不建这个文件(测「判不出来」)。
            stamp: 生成物第一行的指纹;``None`` 表示不建生成物。

        返回参数:
            无(构造即准备好)。
        """
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        if openapi is not None:
            (self.root / gen.OPENAPI).parent.mkdir(parents=True, exist_ok=True)
            # 用 write_bytes 而不是 write_text:后者在 Windows 上会把 "\n" 翻成 "\r\n",
            # 于是「CRLF 版」用例实际写入的是 "\r\r\n",测的就不是行尾了。
            (self.root / gen.OPENAPI).write_bytes(openapi.encode("utf-8"))
        if stamp is not None:
            schema = self.root / gen.SCHEMA
            schema.parent.mkdir(parents=True, exist_ok=True)
            schema.write_bytes(
                f"{gen.STAMP_PREFIX}{stamp}\nexport interface paths {{}}\n".encode("utf-8")
            )

    def __enter__(self) -> "TempRepo":
        """进入上下文。

        返回参数:
            自身。
        """
        return self

    def __exit__(self, *_exc) -> None:
        """清理临时目录。

        参数说明:
            *_exc: 异常三元组(未使用)。

        返回参数:
            无返回值。
        """
        self._tmp.cleanup()


class FingerprintTests(unittest.TestCase):
    """指纹的稳定性:同一份内容,不同行尾必须算出同一个哈希。"""

    def test_crlf_and_lf_share_one_fingerprint(self):
        """CRLF 与 LF 是同一份契约 —— 指纹必须相同(否则 Windows 检出永远红)。"""
        with TempRepo("a: 1\nb: 2\n") as lf, TempRepo("a: 1\r\nb: 2\r\n") as crlf:
            self.assertEqual(gen.fingerprint(lf.root), gen.fingerprint(crlf.root))

    def test_content_change_changes_fingerprint(self):
        """内容变一个字节,指纹必须变(否则门禁形同虚设)。"""
        with TempRepo("a: 1\n") as one, TempRepo("a: 2\n") as two:
            self.assertNotEqual(gen.fingerprint(one.root), gen.fingerprint(two.root))

    def test_missing_openapi_is_undecidable(self):
        """契约文件缺失 = 判不出来(退出码 2),不能冒充「一致」。"""
        with TempRepo(openapi=None) as repo:
            with self.assertRaises(gen.CheckError):
                gen.fingerprint(repo.root)


class CheckTests(unittest.TestCase):
    """``check()`` 的四种结论:一致 / 指纹过期 / 没有指纹 / 生成物缺失。"""

    def test_matching_stamp_passes(self):
        """指纹一致时通过,并把两边的指纹都带回来。"""
        with TempRepo() as repo:
            expected = gen.fingerprint(repo.root)
        with TempRepo(stamp=expected) as repo:
            result = gen.check(repo.root)
            self.assertTrue(result.ok)
            self.assertEqual(result.expected, expected)
            self.assertEqual(result.actual, expected)
            self.assertEqual(result.problems, ())

    def test_stale_stamp_fails_with_actionable_message(self):
        """指纹过期(改了契约没重生成)必须判红,且提示里给出该跑哪条命令。"""
        with TempRepo(stamp="0" * 64) as repo:
            result = gen.check(repo.root)
            self.assertFalse(result.ok)
            joined = "\n".join(result.problems)
            self.assertIn(gen.SCHEMA, joined)
            self.assertIn("python scripts/gen_web_schema.py", joined)
            self.assertEqual(result.actual, "0" * 64)
            self.assertNotEqual(result.expected, result.actual)

    def test_missing_stamp_line_fails(self):
        """第一行没有指纹(旧生成物 / 用 npm run gen:api 生成)必须判红。"""
        with TempRepo() as repo:
            schema = repo.root / gen.SCHEMA
            schema.parent.mkdir(parents=True, exist_ok=True)
            schema.write_text("export interface paths {}\n", encoding="utf-8")
            result = gen.check(repo.root)
            self.assertFalse(result.ok)
            self.assertEqual(result.actual, "")
            self.assertIn("指纹", "\n".join(result.problems))

    def test_missing_schema_fails(self):
        """生成物不存在也必须判红(而不是判不出来)—— 补一条命令就能修好。"""
        with TempRepo() as repo:
            result = gen.check(repo.root)
            self.assertFalse(result.ok)
            self.assertIn(gen.SCHEMA, "\n".join(result.problems))

    def test_exit_codes(self):
        """命令行退出码:0 一致 / 1 判定失败 / 2 判不出来(与 artifacts.py 同口径)。"""
        with TempRepo() as repo:
            expected = gen.fingerprint(repo.root)
        with TempRepo(stamp=expected) as repo:
            self.assertEqual(gen.main(["--check", "--root", str(repo.root)]), 0)
            self.assertEqual(gen.main(["--print", "--root", str(repo.root)]), 0)
        with TempRepo(stamp="0" * 64) as repo:
            self.assertEqual(gen.main(["--check", "--root", str(repo.root)]), 1)
        with TempRepo(openapi=None) as repo:
            self.assertEqual(gen.main(["--check", "--root", str(repo.root)]), 2)

    def test_generate_rejects_missing_contract(self):
        """没有契约时生成要报「判不出来」,而不是写一个空文件。"""
        with TempRepo(openapi=None) as repo:
            with self.assertRaises(gen.CheckError):
                gen.generate(repo.root)


class LiveRepoTests(unittest.TestCase):
    """当前仓库自己的生成物:提交进 HEAD 的那份必须与契约一致。"""

    def test_repo_schema_is_in_sync(self):
        """本仓库的 schema.d.ts 与 openapi.yml 一致(门禁 ``contract-openapi-web-stamp`` 的同一判定)。"""
        result = gen.check(gen.ROOT)
        self.assertTrue(result.ok, "\n".join(result.problems))


if __name__ == "__main__":
    unittest.main()
