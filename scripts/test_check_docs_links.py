"""``scripts/check_docs_links.py`` 的自测(纯离线,临时目录里造 Markdown)。

进 CI 的 `contract` 轨。它是 L4「机械一致性」信号唯一的实现,而这类信号的特点是
**错了没人当场知道**:多报会把假活派给 worker(污染待办),少报会让断链永远沉在文档里。
两边都由下面钉住。

文件信息:
    文件名称          scripts/test_check_docs_links.py
    项目名称          chat_app / 工程脚本
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11
    适用平台          Linux x86_64（本地与 CI）
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import check_docs_links


class FindBrokenLinksTests(unittest.TestCase):
    """判定口径:什么算链接、什么不算、行号是否准。"""

    def setUp(self):
        """建一个临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs/specs").mkdir(parents=True)
        (self.root / "docs/real.md").write_text("# 真的\n", encoding="utf-8")

    def tearDown(self):
        """清理。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def _write(self, name: str, text: str) -> None:
        """写一个 Markdown 文件。

        参数说明:
            name: 相对 `docs/` 的路径。
            text: 文件内容。

        返回参数:
            无返回值。

        使用示例:
            ``obj._write(name, text)``

        备注信息:
            无特殊约束。
        """
        path = self.root / "docs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_existing_link_is_fine(self):
        """指向存在文件的链接不算断链。

        参数说明:
            无。
        """
        self._write("specs/a.md", "[好](../real.md)\n")
        self.assertEqual(check_docs_links.find_broken_links(self.root), [])

    def test_missing_target_reported(self):
        """指向不存在文件的链接被报出,行号与解析路径都要对。

        参数说明:
            无。
        """
        self._write("specs/a.md", "# 标题\n\n[坏](../../missing.md)\n")
        broken = check_docs_links.find_broken_links(self.root)
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0]["file"], "docs/specs/a.md")
        self.assertEqual(broken[0]["line"], 3)
        self.assertEqual(broken[0]["target"], "../../missing.md")

    def test_external_and_anchor_ignored(self):
        """外链、纯锚点、站点根路径都不判(需要联网或是另一种语义)。

        参数说明:
            无。
        """
        self._write(
            "a.md",
            "[外](https://example.com) [锚](#标题) [邮件](mailto:a@b.c) [根](/ops/x)\n",
        )
        self.assertEqual(check_docs_links.find_broken_links(self.root), [])

    def test_code_blocks_ignored_but_line_numbers_kept(self):
        """代码块里的方括号不是链接;抹掉代码不能挪动后面报错的行号。

        参数说明:
            无。
        """
        self._write(
            "a.md",
            "```bash\n[not](a-link.md)\n```\n\n[坏](missing.md)\n",
        )
        broken = check_docs_links.find_broken_links(self.root)
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0]["line"], 5)

    def test_inline_code_ignored(self):
        """行内代码里的东西不判。

        参数说明:
            无。
        """
        self._write("a.md", "写 `[x](missing.md)` 这种不算链接\n")
        self.assertEqual(check_docs_links.find_broken_links(self.root), [])

    def test_image_and_reference_definition(self):
        """图片与引用式定义同样要判。

        参数说明:
            无。
        """
        self._write("a.md", "![图](nope.png)\n\n[ref]: ../gone.md\n")
        targets = {item["target"] for item in check_docs_links.find_broken_links(self.root)}
        self.assertEqual(targets, {"nope.png", "../gone.md"})

    def test_anchor_in_target_stripped(self):
        """目标带 `#anchor` 时按文件部分判。

        参数说明:
            无。
        """
        self._write("specs/a.md", "[好](../real.md#第二节)\n")
        self.assertEqual(check_docs_links.find_broken_links(self.root), [])

    def test_percent_encoding_decoded(self):
        """`%20` 要解码后再判,否则会误报。

        参数说明:
            无。
        """
        (self.root / "docs/有 空格.md").write_text("# x\n", encoding="utf-8")
        self._write("a.md", "[x](有%20空格.md)\n")
        self.assertEqual(check_docs_links.find_broken_links(self.root), [])

    def test_suggestion_only_when_unique(self):
        """同名文件唯一时给出候选(机器可得的改法);有多个就不猜。

        参数说明:
            无。
        """
        (self.root / "AGENTS.md").write_text("# x\n", encoding="utf-8")
        # 相对深度写错一级:真实情形(2026-11-12 实测的 6 处断链都是这一类)
        self._write("specs/a.md", "[x](../../../AGENTS.md)\n")
        broken = check_docs_links.find_broken_links(self.root)
        self.assertEqual(broken[0]["suggestion"], "AGENTS.md")

    def test_no_suggestion_when_ambiguous(self):
        """两个同名文件 → 不给候选(选哪个是人的判断)。

        参数说明:
            无。
        """
        (self.root / "one").mkdir()
        (self.root / "two").mkdir()
        (self.root / "one/same.md").write_text("# a\n", encoding="utf-8")
        (self.root / "two/same.md").write_text("# b\n", encoding="utf-8")
        self._write("a.md", "[x](same.md)\n")
        broken = check_docs_links.find_broken_links(self.root)
        self.assertEqual(broken[0]["suggestion"], "")

    def test_missing_docs_dir_raises(self):
        """没有 docs/ 属于「判不出来」,必须抛错让上层 fail-closed。

        参数说明:
            无。
        """
        with self.assertRaises(FileNotFoundError):
            check_docs_links.find_broken_links(self.root / "nope")


class CommandLineTests(unittest.TestCase):
    """CLI:退出码与 JSON 形状(L4 判定器消费 JSON)。"""

    def setUp(self):
        """建一个含一处断链的临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs/a.md").write_text("[坏](missing.md)\n", encoding="utf-8")

    def tearDown(self):
        """清理。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def test_exit_code_one_when_broken(self):
        """有断链 → 退出码 1。

        参数说明:
            无。
        """
        self.assertEqual(check_docs_links.main(["--root", str(self.root)]), 1)

    def test_exit_code_zero_when_clean(self):
        """没有断链 → 退出码 0(工单的验收口径就是它)。

        参数说明:
            无。
        """
        (self.root / "docs/a.md").write_text("[好](a.md)\n", encoding="utf-8")
        self.assertEqual(check_docs_links.main(["--root", str(self.root)]), 0)

    def test_exit_code_two_when_undecidable(self):
        """判不出来 → 退出码 2(既不是「绿」也不是「有断链」)。

        参数说明:
            无。
        """
        self.assertEqual(check_docs_links.main(["--root", str(self.root / "nope")]), 2)

    def test_json_output_shape(self):
        """`--json` 输出 `{broken: [...], count: n}`。

        参数说明:
            无。
        """
        argv = ["--root", str(self.root), "--json"]
        buffer: list = []
        original = check_docs_links.sys.stdout
        check_docs_links.sys.stdout = type("Sink", (), {"write": staticmethod(buffer.append)})()
        try:
            code = check_docs_links.main(argv)
        finally:
            check_docs_links.sys.stdout = original
        self.assertEqual(code, 1)
        payload = json.loads("".join(buffer))
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["broken"][0]["file"], "docs/a.md")


if __name__ == "__main__":
    unittest.main()
