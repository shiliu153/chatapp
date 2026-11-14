"""``scripts/docs_lint.py`` 的自测(纯离线,临时目录里造样本)。

进 CI 的 `contract` 轨。六条规则各自的两个方向都不能静默:

- **structure**:漏报 = 脚本又躺回 `docs/`(本节刚搬走的东西会回来);误报 = 合规文件
  被拦,人会开始「关掉它」。
- **unindexed**:漏报 = 新文档永远进不了索引(这正是治理要消灭的那类漂移);
  误报 = 老老实实写了链接也被判红。
- **broken-link**:直接复用 ``check_docs_links``,这里只钉「确实接上了」这一件事。
- **metadata**:漏报 = 元信息规则形同虚设;误报 = 合规的 `复核` 写法被拦
  (尤其「日期不算」这条,写日期的人会觉得理所当然)。
- **term**:漏报 = C4 复发;误报 = 白名单文件或带行内豁免的行被拦,人就会去关整条规则。
- **number**:漏报 = 手写接口数继续漂移;误报 = 没写这句话的分册被逼着补。

另外钉住两个**判定器自身故障**的口径:目录不存在、一份 Markdown 都没扫到,
都必须是退出码 2 而不是「0 违例」。

文件信息:
    文件名称          scripts/test_docs_lint.py
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

from scripts import docs_lint

#: 一份合法的头部元信息(测试里到处用)。
GOOD_HEADER = "---\n状态: 生效中\n复核: 每次改动时\n---\n\n"


def write_doc(root: Path, name: str, body: str = "# x\n", header: str = "") -> None:
    """在临时仓库里写一份文档(父目录按需创建)。

    参数说明:
        root: 仓库根目录。
        name: 相对仓库根的路径。
        body: 正文(不含头部)。
        header: 头部元信息;空串表示不写(用来测「缺元信息」)。

    返回参数:
        无返回值。

    使用示例:
        ``write_doc(root, name, body, header)``

    备注信息:
        无特殊约束。
    """
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + body, encoding="utf-8")


class StructureRuleTests(unittest.TestCase):
    """结构规则:`docs/` 下只允许文档与机器可读契约。"""

    def setUp(self):
        """建一个只有 docs/ 的临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()

    def tearDown(self):
        """清理。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def _write(self, name: str, text: str = "# x\n") -> None:
        """写一个文件(父目录按需创建)。

        参数说明:
            name: 相对仓库根的路径。
            text: 文件内容。

        返回参数:
            无返回值。

        使用示例:
            ``obj._write(name, text)``

        备注信息:
            无特殊约束。
        """
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_markdown_and_machine_readable_allowed(self):
        """`.md` / `.yml` / `.json` / 图片都在白名单里。

        参数说明:
            无。
        """
        for name in ("docs/a.md", "docs/api/openapi.yml", "docs/x.json", "docs/y.png", "docs/z.svg"):
            self._write(name)
        self.assertEqual(docs_lint.find_misplaced_files(self.root), [])

    def test_script_reported(self):
        """脚本躺在 docs/ 下要被报出来。

        参数说明:
            无。

        备注信息:
            这里刻意用治理第 2 节真实搬走的那个路径当样本:它是「漏报会复发」的具体形状,
            换成虚构路径就失去了「这条规则挡的就是它」的说明力。
        """
        self._write("docs/ops/stress/http_load.py", "print('x')\n")
        self.assertEqual(docs_lint.find_misplaced_files(self.root), ["docs/ops/stress/http_load.py"])

    def test_patch_and_conf_reported(self):
        """补丁与配置样本同属「不是文档」(同样用真实历史路径当样本)。

        参数说明:
            无。
        """
        self._write("docs/ops/patches/fix.patch", "diff --git a/x b/x\n")
        self._write("docs/ops/sample.conf", "server {}\n")
        self.assertEqual(
            docs_lint.find_misplaced_files(self.root),
            ["docs/ops/patches/fix.patch", "docs/ops/sample.conf"],
        )

    def test_archive_also_checked(self):
        """归档子树同样只放文档 —— 归档只 git mv,不新增别的类型。

        参数说明:
            无。
        """
        self._write("docs/superpowers/archive/plans/old.sh", "echo 1\n")
        self.assertEqual(
            docs_lint.find_misplaced_files(self.root),
            ["docs/superpowers/archive/plans/old.sh"],
        )

    def test_suffix_case_insensitive(self):
        """`.MD` / `.YML` 与 `.md` / `.yml` 同等对待。

        参数说明:
            无。
        """
        self._write("docs/A.MD")
        self._write("docs/api/openapi.YML")
        self.assertEqual(docs_lint.find_misplaced_files(self.root), [])

    def test_missing_docs_dir_raises(self):
        """没有 docs/ 是「判不出来」,必须抛错让上层 fail-closed。

        参数说明:
            无。
        """
        with self.assertRaises(FileNotFoundError):
            docs_lint.find_misplaced_files(self.root / "nope")


class IndexCoverageRuleTests(unittest.TestCase):
    """索引覆盖规则:非归档文档必须被某个索引以相对链接指向。"""

    def setUp(self):
        """建一个带根 README 的临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "README.md").write_text("# 根\n", encoding="utf-8")

    def tearDown(self):
        """清理。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def _write(self, name: str, text: str = "# x\n") -> None:
        """写一个文件(父目录按需创建)。

        参数说明:
            name: 相对仓库根的路径。
            text: 文件内容。

        返回参数:
            无返回值。

        使用示例:
            ``obj._write(name, text)``

        备注信息:
            无特殊约束。
        """
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_root_readme_covers(self):
        """根 README 以相对链接指向即可覆盖。

        参数说明:
            无。
        """
        self._write("docs/ops/runbook.md")
        (self.root / "README.md").write_text("[runbook](docs/ops/runbook.md)\n", encoding="utf-8")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), [])

    def test_sub_readme_covers(self):
        """子 README 也是索引:根 → 子 README → 正文,链条只要直连就够。

        参数说明:
            无。
        """
        self._write("docs/ops/runbook.md")
        self._write("docs/ops/README.md", "[runbook](runbook.md)\n")
        (self.root / "README.md").write_text("[ops](docs/ops/README.md)\n", encoding="utf-8")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), [])

    def test_unindexed_reported(self):
        """没人指向的文档要被报出来。

        参数说明:
            无。
        """
        self._write("docs/ops/orphan.md")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), ["docs/ops/orphan.md"])

    def test_archive_exempt(self):
        """归档不参与:历史文档保持原样,不逼着人去补链接(spec §6)。

        参数说明:
            无。
        """
        self._write("docs/superpowers/archive/plans/old.md")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), [])

    def test_archive_readme_is_not_an_index(self):
        """归档里的 README 不算索引 —— 否则历史文档能替现役文档「担保」。

        参数说明:
            无。
        """
        self._write("docs/ops/orphan.md")
        self._write("docs/superpowers/archive/README.md", "[x](../../ops/orphan.md)\n")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), ["docs/ops/orphan.md"])

    def test_claude_and_agents_count_as_index(self):
        """`CLAUDE.md` / `AGENTS.md` 也是根入口。

        参数说明:
            无。
        """
        self._write("docs/ops/runbook.md")
        (self.root / "AGENTS.md").write_text("[x](docs/ops/runbook.md)\n", encoding="utf-8")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), [])

    def test_link_inside_code_block_does_not_cover(self):
        """代码块里的「链接」不是链接,不能拿来当覆盖证据。

        参数说明:
            无。
        """
        self._write("docs/ops/orphan.md")
        (self.root / "README.md").write_text(
            "```\n[x](docs/ops/orphan.md)\n```\n", encoding="utf-8"
        )
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), ["docs/ops/orphan.md"])

    def test_external_link_does_not_cover(self):
        """外链不是仓库内路径,不构成覆盖。

        参数说明:
            无。
        """
        self._write("docs/ops/orphan.md")
        (self.root / "README.md").write_text(
            "[x](https://example.com/docs/ops/orphan.md)\n", encoding="utf-8"
        )
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), ["docs/ops/orphan.md"])

    def test_sub_readme_itself_needs_coverage(self):
        """子 README 是索引,但它自己也要被上一级指向。

        参数说明:
            无。
        """
        self._write("docs/ops/README.md", "# ops\n")
        self.assertEqual(docs_lint.find_unindexed_docs(self.root), ["docs/ops/README.md"])


class CombinedLintTests(unittest.TestCase):
    """六条规则合并后的形状:rule 名、排序、断链字段。"""

    def setUp(self):
        """建一个同时踩多条规则的临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "README.md").write_text("[ok](docs/ok.md)\n", encoding="utf-8")
        (self.root / "docs/ok.md").write_text("[坏](missing.md)\n", encoding="utf-8")
        (self.root / "docs/orphan.md").write_text("# 没人指向我\n", encoding="utf-8")
        (self.root / "docs/run.sh").write_text("echo 1\n", encoding="utf-8")

    def tearDown(self):
        """清理。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def test_rules_are_independent(self):
        """各条规则各报各的,不会因为一条命中就跳过其余。

        参数说明:
            无。
        """
        rules = {item["rule"] for item in docs_lint.lint(self.root)}
        self.assertEqual(rules, {"broken-link", "structure", "unindexed", "metadata"})

    def test_broken_link_keeps_upstream_fields(self):
        """断链项保留 ``check_docs_links`` 的 line / target / resolved / suggestion。

        参数说明:
            无。
        """
        item = next(i for i in docs_lint.lint(self.root) if i["rule"] == "broken-link")
        self.assertEqual(item["file"], "docs/ok.md")
        self.assertEqual(item["line"], 1)
        self.assertEqual(item["target"], "missing.md")
        self.assertIn("resolved", item)
        self.assertIn("suggestion", item)

    def test_output_is_stable(self):
        """同样输入两次跑出同样顺序(否则 CI 日志没法对比)。

        参数说明:
            无。
        """
        self.assertEqual(docs_lint.lint(self.root), docs_lint.lint(self.root))


class MetadataRuleTests(unittest.TestCase):
    """元信息规则:非归档文档要有 状态 / 复核,取值合法,`superpowers/` 豁免。"""

    def setUp(self):
        """建一个只有 docs/ 的临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()

    def tearDown(self):
        """清理。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def _messages(self) -> list:
        """跑一次元信息规则,返回 message 列表。

        备注信息:
            无特殊约束。
        """
        return [item["message"] for item in docs_lint.find_metadata_violations(self.root)]

    def test_valid_header_passes(self):
        """状态 + 周期短语的复核 → 合规。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/ops/runbook.md", header=GOOD_HEADER)
        self.assertEqual(self._messages(), [])

    def test_command_and_one_shot_reviews_pass(self):
        """反引号命令与 无(一次性) 都是合法形态。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/a.md", header="---\n状态: 常驻\n复核: `python scripts/docs_lint.py`\n---\n\n")
        write_doc(self.root, "docs/b.md", header="---\n状态: 一次性\n复核: 无(一次性)\n---\n\n")
        self.assertEqual(self._messages(), [])

    def test_missing_header_reported(self):
        """没有头部 → 报出来(这是最容易漏的一类:新文档直接写标题)。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/new.md")
        messages = self._messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("缺少头部元信息", messages[0])

    def test_missing_field_reported(self):
        """只写状态、没写复核 → 报出缺哪个字段。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/a.md", header="---\n状态: 生效中\n---\n\n")
        messages = self._messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("复核", messages[0])

    def test_bad_state_reported(self):
        """状态不在词表里 → 报出来(否则词表形同虚设)。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/a.md", header="---\n状态: 进行中\n复核: 每次改动时\n---\n\n")
        messages = self._messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("不合法", messages[0])

    def test_date_review_reported(self):
        """`复核: 2026-11-14` 不是合法形态 —— 写日期等于造数据。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/a.md", header="---\n状态: 生效中\n复核: 2026-11-14\n---\n\n")
        messages = self._messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("不写日期", messages[0])

    def test_superpowers_exempt(self):
        """`docs/superpowers/` 豁免 —— 它的状态 owner 是该目录 README §2。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/superpowers/specs/2026-01-01-x-design.md")
        self.assertEqual(self._messages(), [])

    def test_archive_exempt(self):
        """归档不改写,元信息规则不碰它。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/superpowers/archive/specs/2026-01-01-x-design.md")
        self.assertEqual(self._messages(), [])


class TermRuleTests(unittest.TestCase):
    """术语规则:作用域、白名单、行内豁免三个方向都要钉住。"""

    def setUp(self):
        """建一个带根 README 的临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "README.md").write_text("# 根\n", encoding="utf-8")

    def tearDown(self):
        """清理。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def _terms(self) -> list:
        """跑一次术语规则,返回 (file, line, term) 三元组列表。

        备注信息:
            无特殊约束。
        """
        return [(i["file"], i["line"], i["term"]) for i in docs_lint.find_term_violations(self.root)]

    def test_term_in_root_file_reported(self):
        """根入口三份在作用域内。

        参数说明:
            无。
        """
        (self.root / "AGENTS.md").write_text("只动 docs/** 的 PR 六轨都不触发\n", encoding="utf-8")
        self.assertEqual(self._terms(), [("AGENTS.md", 1, "六轨")])

    def test_term_in_live_doc_dir_reported(self):
        """`docs/ops/` 是活文档,要扫。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/ops/release.md", "六轨全绿后合并\n", header=GOOD_HEADER)
        self.assertEqual(self._terms(), [("docs/ops/release.md", 6, "六轨")])

    def test_one_shot_report_exempt(self):
        """一次性报告 / 审计 / 教学材料不在作用域内(历史不改写)。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/reports/x.md", "六轨全绿\n", header=GOOD_HEADER)
        write_doc(self.root, "docs/security/round4.md", "三轮安全审计\n", header=GOOD_HEADER)
        self.assertEqual(self._terms(), [])

    def test_whitelist_file_exempt(self):
        """口径页本身在**定义**禁用词,整文件白名单。

        参数说明:
            无。
        """
        write_doc(
            self.root,
            "docs/standards/sources-of-truth.md",
            "| 「六轨」「CI 四轨」 | 禁用 |\n",
            header=GOOD_HEADER,
        )
        self.assertEqual(self._terms(), [])

    def test_inline_marker_exempts_only_its_line(self):
        """行内标记只豁免它所在的那一行,不能顺手关掉整份文档。

        参数说明:
            无。
        """
        write_doc(
            self.root,
            "docs/ops/x.md",
            "这句引用「六轨」以说明它被禁 <!-- lint:allow:term -->\n这句没标记六轨\n",
            header=GOOD_HEADER,
        )
        self.assertEqual(self._terms(), [("docs/ops/x.md", 7, "六轨")])

    def test_all_banned_terms_detected(self):
        """三条禁用词都在表里(漏一条就是漏一个复发口子)。

        参数说明:
            无。
        """
        (self.root / "CLAUDE.md").write_text("CI 四轨\n三轮安全审计\n", encoding="utf-8")
        self.assertEqual(
            sorted(self._terms()),
            [("CLAUDE.md", 1, "CI 四轨"), ("CLAUDE.md", 2, "三轮安全审计")],
        )


class NumberRuleTests(unittest.TestCase):
    """数字规则:分册首句的接口数必须等于接口一览表里指向该分册的行数。"""

    def setUp(self):
        """建一个带接口一览表的临时仓库(表里 2 行指向 x.md)。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs/api").mkdir(parents=True)
        (self.root / "docs/api/README.md").write_text(
            "# 接口\n\n## 接口一览\n\n"
            "| 方法 | 路径 | 说明 | 分册 |\n|---|---|---|---|\n"
            "| GET | `/api/v1/a` | A | [x](x.md) |\n"
            "| POST | `/api/v1/b` | B | [x](x.md) |\n",
            encoding="utf-8",
        )

    def tearDown(self):
        """清理。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def _messages(self) -> list:
        """跑一次数字规则,返回 message 列表。

        备注信息:
            无特殊约束。
        """
        return [item["message"] for item in docs_lint.find_number_violations(self.root)]

    def test_matching_count_passes(self):
        """写 2、表里也是 2 行 → 合规。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/api/x.md", "本分册含 2 个接口:A、B。\n", header=GOOD_HEADER)
        self.assertEqual(self._messages(), [])

    def test_mismatch_reported(self):
        """写 3、表里只有 2 行 → 报出来(这就是 im.md 当年那处漂移)。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/api/x.md", "本分册含 3 个接口:A、B、C。\n", header=GOOD_HEADER)
        messages = self._messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("本分册含 3 个接口", messages[0])
        self.assertIn("2 行", messages[0])

    def test_volume_without_sentence_passes(self):
        """没写这句话的分册不判(可选句式:写了就必须对)。

        参数说明:
            无。
        """
        write_doc(self.root, "docs/api/y.md", "本分册没有计数句。\n", header=GOOD_HEADER)
        self.assertEqual(self._messages(), [])

    def test_missing_api_readme_is_not_a_crash(self):
        """没有接口一览表时不报错也不误报(临时仓库 / 还没建 api 目录)。

        参数说明:
            无。
        """
        (self.root / "docs/api/README.md").unlink()
        write_doc(self.root, "docs/api/x.md", "本分册含 9 个接口。\n", header=GOOD_HEADER)
        self.assertEqual(self._messages(), [])


class CommandLineTests(unittest.TestCase):
    """CLI:退出码与 JSON 形状(L4 判定器消费 JSON)。"""

    def setUp(self):
        """建一个合规的临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "README.md").write_text("[a](docs/a.md)\n", encoding="utf-8")
        (self.root / "docs/a.md").write_text(GOOD_HEADER + "# a\n", encoding="utf-8")

    def tearDown(self):
        """清理。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def _run_json(self, argv: list) -> tuple:
        """跑一次 CLI 并接住 stdout。

        参数说明:
            argv: 传给 ``main`` 的参数列表。

        返回参数:
            ``(退出码, 解析后的 JSON 字典)`` 二元组。

        使用示例:
            ``obj._run_json(argv)``

        备注信息:
            无特殊约束。
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
        """0 违例 → 退出码 0(本节的验收口径就是它)。

        参数说明:
            无。
        """
        self.assertEqual(docs_lint.main(["--root", str(self.root)]), 0)

    def test_exit_code_one_when_violated(self):
        """有违例 → 退出码 1。

        参数说明:
            无。
        """
        (self.root / "docs/bad.sh").write_text("echo 1\n", encoding="utf-8")
        self.assertEqual(docs_lint.main(["--root", str(self.root)]), 1)

    def test_exit_code_two_when_docs_missing(self):
        """没有 docs/ → 退出码 2(既不是绿也不是红)。

        参数说明:
            无。
        """
        self.assertEqual(docs_lint.main(["--root", str(self.root / "nope")]), 2)

    def test_exit_code_two_when_nothing_scanned(self):
        """扫到 0 份 Markdown 是真故障,不能当成「0 违例」放行。

        参数说明:
            无。
        """
        empty = self.root / "empty"
        (empty / "docs").mkdir(parents=True)
        self.assertEqual(docs_lint.main(["--root", str(empty)]), 2)

    def test_json_output_shape(self):
        """`--json` 输出 `{violations, count, by_rule, scanned}`。

        参数说明:
            无。
        """
        (self.root / "docs/bad.sh").write_text("echo 1\n", encoding="utf-8")
        code, payload = self._run_json(["--root", str(self.root), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["by_rule"], {"structure": 1})
        self.assertEqual(payload["violations"][0]["file"], "docs/bad.sh")
        self.assertEqual(payload["scanned"], 1)


if __name__ == "__main__":
    unittest.main()
