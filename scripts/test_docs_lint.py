"""``scripts/docs_lint.py`` 的自测(纯离线,临时目录里造样本)。

进 CI 的 `contract` 轨。三条规则各自的两个方向都不能静默:

- **structure**:漏报 = 脚本又躺回 `docs/`(本节刚搬走的东西会回来);误报 = 合规文件
  被拦,人会开始「关掉它」。
- **unindexed**:漏报 = 新文档永远进不了索引(这正是治理要消灭的那类漂移);
  误报 = 老老实实写了链接也被判红。
- **broken-link**:直接复用 ``check_docs_links``,这里只钉「确实接上了」这一件事。

另外钉住两个**判定器自身故障**的口径:目录不存在、一份 Markdown 都没扫到,
都必须是退出码 2 而不是「0 违例」。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import docs_lint


class StructureRuleTests(unittest.TestCase):
    """结构规则:`docs/` 下只允许文档与机器可读契约。"""

    def setUp(self):
        """建一个只有 docs/ 的临时仓库。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()

    def tearDown(self):
        """清理。"""
        self.tmp.cleanup()

    def _write(self, name: str, text: str = "# x\n") -> None:
        """写一个文件(父目录按需创建)。

        Args:
            name: 相对仓库根的路径。
            text: 文件内容。
        """
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_markdown_and_machine_readable_allowed(self):
        """`.md` / `.yml` / `.json` / 图片都在白名单里。"""
        for name in ("docs/a.md", "docs/api/openapi.yml", "docs/x.json", "docs/y.png", "docs/z.svg"):
            self._write(name)
        self.assertEqual(docs_lint.find_misplaced_files(self.root), [])

    def test_script_reported(self):
        """脚本躺在 docs/ 下要被报出来。

        这里刻意用治理第 2 节真实搬走的那个路径当样本:它是「漏报会复发」的具体形状,
        换成虚构路径就失去了「这条规则挡的就是它」的说明力。
        """
        self._write("docs/ops/stress/http_load.py", "print('x')\n")
        self.assertEqual(docs_lint.find_misplaced_files(self.root), ["docs/ops/stress/http_load.py"])

    def test_patch_and_conf_reported(self):
        """补丁与配置样本同属「不是文档」(同样用真实历史路径当样本)。"""
        self._write("docs/ops/patches/fix.patch", "diff --git a/x b/x\n")
        self._write("docs/ops/sample.conf", "server {}\n")
        self.assertEqual(
            docs_lint.find_misplaced_files(self.root),
            ["docs/ops/patches/fix.patch", "docs/ops/sample.conf"],
        )

    def test_archive_also_checked(self):
        """归档子树同样只放文档 —— 归档只 git mv,不新增别的类型。"""
        self._write("docs/superpowers/archive/plans/old.sh", "echo 1\n")
        self.assertEqual(
            docs_lint.find_misplaced_files(self.root),
            ["docs/superpowers/archive/plans/old.sh"],
        )

    def test_suffix_case_insensitive(self):
        """`.MD` / `.YML` 与 `.md` / `.yml` 同等对待。"""
        self._write("docs/A.MD")
        self._write("docs/api/openapi.YML")
        self.assertEqual(docs_lint.find_misplaced_files(self.root), [])

    def test_missing_docs_dir_raises(self):
        """没有 docs/ 是「判不出来」,必须抛错让上层 fail-closed。"""
        with self.assertRaises(FileNotFoundError):
            docs_lint.find_misplaced_files(self.root / "nope")


class IndexCoverageRuleTests(unittest.TestCase):
    """索引覆盖规则:非归档文档必须被某个索引以相对链接指向。"""

    def setUp(self):
        """建一个带根 README 的临时仓库。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "README.md").write_text("# 根\n", encoding="utf-8")

    def tearDown(self):
        """清理。"""
        self.tmp.cleanup()

    def _write(self, name: str, text: str = "# x\n") -> None:
        """写一个文件(父目录按需创建)。

        Args:
            name: 相对仓库根的路径。
            text: 文件内容。
        """
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_root_readme_covers(self):
        """根 README 以相对链接指向即可覆盖。"""
        self._write("docs/ops/runbook.md")
        (self.root / "README.md").write_text("[runbook](docs/ops/runbook.md)\n", encoding="utf-8")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), [])

    def test_sub_readme_covers(self):
        """子 README 也是索引:根 → 子 README → 正文,链条只要直连就够。"""
        self._write("docs/ops/runbook.md")
        self._write("docs/ops/README.md", "[runbook](runbook.md)\n")
        (self.root / "README.md").write_text("[ops](docs/ops/README.md)\n", encoding="utf-8")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), [])

    def test_unindexed_reported(self):
        """没人指向的文档要被报出来。"""
        self._write("docs/ops/orphan.md")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), ["docs/ops/orphan.md"])

    def test_archive_exempt(self):
        """归档不参与:历史文档保持原样,不逼着人去补链接(spec §6)。"""
        self._write("docs/superpowers/archive/plans/old.md")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), [])

    def test_archive_readme_is_not_an_index(self):
        """归档里的 README 不算索引 —— 否则历史文档能替现役文档「担保」。"""
        self._write("docs/ops/orphan.md")
        self._write("docs/superpowers/archive/README.md", "[x](../../ops/orphan.md)\n")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), ["docs/ops/orphan.md"])

    def test_claude_and_agents_count_as_index(self):
        """`CLAUDE.md` / `AGENTS.md` 也是根入口。"""
        self._write("docs/ops/runbook.md")
        (self.root / "AGENTS.md").write_text("[x](docs/ops/runbook.md)\n", encoding="utf-8")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), [])

    def test_link_inside_code_block_does_not_cover(self):
        """代码块里的「链接」不是链接,不能拿来当覆盖证据。"""
        self._write("docs/ops/orphan.md")
        (self.root / "README.md").write_text(
            "```\n[x](docs/ops/orphan.md)\n```\n", encoding="utf-8"
        )
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), ["docs/ops/orphan.md"])

    def test_external_link_does_not_cover(self):
        """外链不是仓库内路径,不构成覆盖。"""
        self._write("docs/ops/orphan.md")
        (self.root / "README.md").write_text(
            "[x](https://example.com/docs/ops/orphan.md)\n", encoding="utf-8"
        )
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), ["docs/ops/orphan.md"])

    def test_sub_readme_itself_needs_coverage(self):
        """子 README 是索引,但它自己也要被上一级指向。"""
        self._write("docs/ops/README.md", "# ops\n")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), ["docs/ops/README.md"])


class CombinedLintTests(unittest.TestCase):
    """三条规则合并后的形状:rule 名、排序、断链字段。"""

    def setUp(self):
        """建一个同时踩三条规则的临时仓库。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "README.md").write_text("[ok](docs/ok.md)\n", encoding="utf-8")
        (self.root / "docs/ok.md").write_text("[坏](missing.md)\n", encoding="utf-8")
        (self.root / "docs/orphan.md").write_text("# 没人指向我\n", encoding="utf-8")
        (self.root / "docs/run.sh").write_text("echo 1\n", encoding="utf-8")

    def tearDown(self):
        """清理。"""
        self.tmp.cleanup()

    def test_rules_are_independent(self):
        """三条规则各报各的,不会因为一条命中就跳过其余。"""
        rules = [item["rule"] for item in docs_lint.lint(self.root)]
        self.assertEqual(rules, ["broken-link", "structure", "unindexed"])

    def test_broken_link_keeps_upstream_fields(self):
        """断链项保留 ``check_docs_links`` 的 line / target / resolved / suggestion。"""
        item = next(i for i in docs_lint.lint(self.root) if i["rule"] == "broken-link")
        self.assertEqual(item["file"], "docs/ok.md")
        self.assertEqual(item["line"], 1)
        self.assertEqual(item["target"], "missing.md")
        self.assertIn("resolved", item)
        self.assertIn("suggestion", item)

    def test_output_is_stable(self):
        """同样输入两次跑出同样顺序(否则 CI 日志没法对比)。"""
        self.assertEqual(docs_lint.lint(self.root), docs_lint.lint(self.root))


class CommandLineTests(unittest.TestCase):
    """CLI:退出码与 JSON 形状(L4 判定器消费 JSON)。"""

    def setUp(self):
        """建一个合规的临时仓库。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "README.md").write_text("[a](docs/a.md)\n", encoding="utf-8")
        (self.root / "docs/a.md").write_text("# a\n", encoding="utf-8")

    def tearDown(self):
        """清理。"""
        self.tmp.cleanup()

    def _run_json(self, argv: list) -> tuple:
        """跑一次 CLI 并接住 stdout。

        Args:
            argv: 传给 ``main`` 的参数列表。

        Returns:
            ``(退出码, 解析后的 JSON 字典)`` 二元组。
        """
        buffer: list = []
        original = docs_lint.sys.stdout
        docs_lint.sys.stdout = type("Sink", (), {"write": staticmethod(buffer.append)})()
        try:
            code = docs_lint.main(argv)
        finally:
            docs_lint.sys.stdout = original
        return code, json.loads("".join(buffer))

    def test_exit_code_zero_when_clean(self):
        """0 违例 → 退出码 0(本节的验收口径就是它)。"""
        self.assertEqual(docs_lint.main(["--root", str(self.root)]), 0)

    def test_exit_code_one_when_violated(self):
        """有违例 → 退出码 1。"""
        (self.root / "docs/bad.sh").write_text("echo 1\n", encoding="utf-8")
        self.assertEqual(docs_lint.main(["--root", str(self.root)]), 1)

    def test_exit_code_two_when_docs_missing(self):
        """没有 docs/ → 退出码 2(既不是绿也不是红)。"""
        self.assertEqual(docs_lint.main(["--root", str(self.root / "nope")]), 2)

    def test_exit_code_two_when_nothing_scanned(self):
        """扫到 0 份 Markdown 是真故障,不能当成「0 违例」放行。"""
        empty = self.root / "empty"
        (empty / "docs").mkdir(parents=True)
        self.assertEqual(docs_lint.main(["--root", str(empty)]), 2)

    def test_json_output_shape(self):
        """`--json` 输出 `{violations, count, by_rule, scanned}`。"""
        (self.root / "docs/bad.sh").write_text("echo 1\n", encoding="utf-8")
        code, payload = self._run_json(["--root", str(self.root), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["by_rule"], {"structure": 1})
        self.assertEqual(payload["violations"][0]["file"], "docs/bad.sh")
        self.assertEqual(payload["scanned"], 1)


if __name__ == "__main__":
    unittest.main()
