"""``scripts/docs_index.py`` 的自测(纯离线,临时目录里造样本)。

进 CI 的 `contract` 轨。它钉住三类事,每一类的两个方向都不能静默:

- **生成**:清单里少了谁(漏报 = 新文档永远进不了索引)、多了谁(把生成物自己列进去)、
  标题取错(误报),都会被看见;
- **完整性**:归档文件漏登 / 重复登记 / 索引里指向不存在的文件 —— 这三条是本节存在的理由
  (手写归档表当年就漏了 7 份),必须能独立于「生成器恰好写对了」而响;
- **接口一览表 ≡ openapi.yml**:缺一行 / 多一行 / 重复一行,以及 `openapi.yml` 解析不出来
  (格式变了)必须报错而不是静默通过。
- **分册计数与业务码覆盖**:一览表的分册列能派生出「每个分册几行」(供 `docs_lint` 的数字规则
  比对);`error_codes.py` 里每个码至少在 `docs/api/` 的一份分册里出现(总表已删除)。

另外钉住两个**判定器自身故障**的口径:文档目录不存在、生成标记缺失,都必须是退出码 2
而不是「0 违例」。

文件信息:
    文件名称          scripts/test_docs_index.py
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

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts import docs_index

#: 一份最小但结构完整的 `openapi.yml`(缩进与 spectacular 生成的一致)。
OPENAPI = """openapi: 3.0.3
info:
  title: 测试契约
  version: 1.0.0
paths:
  /api/v1/a:
    get:
      operationId: a_retrieve
      tags:
      - x
  /api/v1/b:
    post:
      operationId: b_create
      tags:
      - x
components:
  schemas: {}
"""

#: 一份带生成标记的接口文档入口;表里默认与 `openapi.yml` 的两个操作一致。
API_README = """# 接口文档

## 接口一览

<!-- BEGIN generated:api-summary -->
<!-- END generated:api-summary -->

| 方法 | 路径 | 说明 | 分册 |
|---|---|---|---|
| GET | `/api/v1/a` | A 接口 | [x](x.md) |
| POST | `/api/v1/b` | B 接口 | [x](x.md) |
"""


#: 业务码目录(错误码的唯一 owner)在测试仓库里的路径。
ERROR_CODES = "chatapp/config/error_codes.py"


def write_file(root: Path, name: str, text: str = "# 标题\n", newline: str = "\n") -> None:
    """在临时仓库里写一个文件(父目录按需创建)。

    参数说明:
        root: 仓库根目录。
        name: 相对仓库根的路径。
        text: 文件内容,``\n`` 会被替换成 `newline`。
        newline: 目标换行风格;测 CRLF 时传 ``"\r\n"``。

    返回参数:
        无返回值。

    使用示例:
        ``write_file(root, name, text, newline)``

    备注信息:
        无特殊约束。
    """
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


class DocsIndexTestCase(unittest.TestCase):
    """公共脚手架:一个最小的「仓库」,包含 docs/、归档目录、接口文档入口与业务码目录。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``obj = DocsIndexTestCase(...)``

    备注信息:
        无特殊约束。
    """

    def setUp(self):
        """建临时仓库并写入最小骨架。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_file(self.root, "docs/milestones.md", "# 里程碑时间线\n")
        write_file(self.root, "docs/superpowers/archive/specs/2026-09-09-x-design.md", "# X 设计\n")
        write_file(self.root, "docs/superpowers/archive/plans/2026-09-09-x.md", "# X 计划\n")
        write_file(self.root, "docs/api/README.md", API_README)
        write_file(self.root, "docs/api/x.md", "# 分册 x\n\n会出现的业务码:`40001` / `40101`。\n")
        write_file(self.root, "docs/api/openapi.yml", OPENAPI)
        write_file(self.root, ERROR_CODES, "A = 40001  # 甲\nB = 40101  # 乙\n")

    def tearDown(self):
        """清理临时目录。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def run_main(self, *argv: str) -> int:
        """跑一次命令行入口,吞掉输出只留退出码。

        参数说明:
            *argv: 追加的命令行参数(会自动补 ``--root``)。

        返回参数:
            退出码。

        使用示例:
            ``obj.run_main(*argv)``

        备注信息:
            无特殊约束。
        """
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return docs_index.main(["--root", str(self.root), *argv])


class RenderDocsIndexTests(DocsIndexTestCase):
    """`docs/README.md` 的渲染:列全、不列自己、标题回退、归档只报数。"""

    def test_lists_every_non_archive_doc_with_relative_link(self):
        """每份非归档文档都出现,链接是相对 `docs/` 的路径。

        参数说明:
            无。
        """
        write_file(self.root, "docs/ops/runbook.md", "# 运维手册\n")
        text = docs_index.render_docs_index(self.root)
        self.assertIn("[milestones.md](milestones.md)", text)
        self.assertIn("[runbook.md](ops/runbook.md)", text)
        self.assertIn("运维手册", text)

    def test_excludes_generated_index_itself(self):
        """生成物自己不列进自己(否则每次生成都多一行)。

        参数说明:
            无。
        """
        write_file(self.root, "docs/README.md", "# 旧索引\n")
        text = docs_index.render_docs_index(self.root)
        self.assertNotIn("[README.md](README.md)", text)
        self.assertIn("共 **3** 份", text)  # milestones + api/README + api/x

    def test_title_falls_back_to_filename(self):
        """没有 H1 的文档用文件名当标题,而不是留空。

        参数说明:
            无。
        """
        write_file(self.root, "docs/ops/no-heading.md", "没有标题的一段话\n")
        text = docs_index.render_docs_index(self.root)
        self.assertIn("| [no-heading.md](ops/no-heading.md) | no-heading |", text)

    def test_archive_section_reports_counts_but_no_links(self):
        """归档只报数并指向 INDEX.md,不把 105 行再抄一遍。

        参数说明:
            无。
        """
        write_file(self.root, "docs/superpowers/archive/plans/2026-09-10-y.md", "# Y 计划\n")
        text = docs_index.render_docs_index(self.root)
        self.assertIn("共 **3** 份 = **1** spec + **2** plan", text)
        self.assertIn("superpowers/archive/INDEX.md", text)
        self.assertNotIn("archive/plans/2026-09-10-y.md", text)

    def test_directory_counts(self):
        """每个目录分组都带份数,总数等于各组之和。

        参数说明:
            无。
        """
        write_file(self.root, "docs/ops/a.md", "# A\n")
        write_file(self.root, "docs/ops/b.md", "# B\n")
        text = docs_index.render_docs_index(self.root)
        self.assertIn("### `docs/ops/`(2 份)", text)

    def test_order_is_platform_independent(self):
        """同目录内按 POSIX 字符串排序:`README.md` 排在 `app.md` 之前。

        参数说明:
            无。

        备注信息:
            这条钉的是**跨平台一致性** —— Windows 的 `Path` 比较大小写不敏感,会把。
            `README.md` 排到 `app.md` 后面;生成物两边不一致,CI 就会红在「本地明明是绿的」上。
        """
        write_file(self.root, "docs/ops/app.md", "# App\n")
        write_file(self.root, "docs/ops/README.md", "# 索引\n")
        text = docs_index.render_docs_index(self.root)
        self.assertLess(text.index("(ops/README.md)"), text.index("(ops/app.md)"))


class RenderArchiveIndexTests(DocsIndexTestCase):
    """归档清单的渲染:日期/主题派生、spec 按同名配对、不把自己算进去。"""

    def test_date_and_topic_derived_from_filename(self):
        """`YYYY-MM-DD-<主题>.md` 拆成日期与主题。

        参数说明:
            无。
        """
        text = docs_index.render_archive_index(self.root)
        self.assertIn("| 2026-09-09 | x | [2026-09-09-x.md](plans/2026-09-09-x.md) |", text)
        self.assertIn("| 2026-09-09 | x-design | [2026-09-09-x-design.md](specs/2026-09-09-x-design.md) |", text)

    def test_spec_paired_by_exact_name_only(self):
        """plan 的同名 `-design` 存在就写文件名;不存在写 `—`,不做猜测。

        参数说明:
            无。
        """
        write_file(self.root, "docs/superpowers/archive/plans/2026-09-10-y.md", "# Y\n")
        text = docs_index.render_archive_index(self.root)
        self.assertIn("| `2026-09-09-x-design.md` |", text)
        self.assertIn("| 2026-09-10 | y | [2026-09-10-y.md](plans/2026-09-10-y.md) | — |", text)

    def test_counts_exclude_index_itself(self):
        """INDEX.md 自己在 archive/ 下,但不能被算成一份归档。

        参数说明:
            无。
        """
        write_file(self.root, "docs/superpowers/archive/INDEX.md", "# 旧清单\n")
        counts = docs_index.count_archive(self.root)
        self.assertEqual(counts, {"total": 2, "specs": 1, "plans": 1})

    def test_sorted_by_date(self):
        """清单按文件名(日期前缀)升序,输出稳定。

        参数说明:
            无。
        """
        write_file(self.root, "docs/superpowers/archive/specs/2026-10-01-z-design.md", "# Z\n")
        text = docs_index.render_archive_index(self.root)
        self.assertLess(text.index("2026-09-09-x-design.md"), text.index("2026-10-01-z-design.md"))


class ArchiveCompletenessTests(DocsIndexTestCase):
    """归档完整性:每份文件在 INDEX.md 里出现且仅出现一次。"""

    def _write_index(self, body: str) -> None:
        """把一段手写的归档清单塞进临时仓库。

        参数说明:
            body: INDEX.md 的正文(不含标题)。

        返回参数:
            无返回值。

        使用示例:
            ``obj._write_index(body)``

        备注信息:
            无特殊约束。
        """
        write_file(self.root, "docs/superpowers/archive/INDEX.md", f"# 归档清单\n\n{body}\n")

    def test_clean_index_has_no_problem(self):
        """两份文件各登记一次 → 无问题。

        参数说明:
            无。
        """
        self._write_index(
            "- [x-design](specs/2026-09-09-x-design.md)\n- [x](plans/2026-09-09-x.md)\n"
        )
        self.assertEqual(docs_index.check_archive_completeness(self.root), [])

    def test_missing_file_reported(self):
        """漏登一份 → 报出来(手写归档表当年就漏了 7 份)。

        参数说明:
            无。
        """
        self._write_index("- [x-design](specs/2026-09-09-x-design.md)\n")
        problems = docs_index.check_archive_completeness(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("plans/2026-09-09-x.md", problems[0])

    def test_duplicate_file_reported(self):
        """同一份登记两次 → 报出来(重复登记同样是索引失真)。

        参数说明:
            无。
        """
        self._write_index(
            "- [x](plans/2026-09-09-x.md)\n- [x2](plans/2026-09-09-x.md)\n"
            "- [x-design](specs/2026-09-09-x-design.md)\n"
        )
        problems = docs_index.check_archive_completeness(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("重复出现 2 次", problems[0])

    def test_dangling_link_inside_archive_reported(self):
        """索引里指向归档内不存在的文件 → 报出来。

        参数说明:
            无。
        """
        self._write_index(
            "- [x-design](specs/2026-09-09-x-design.md)\n"
            "- [x](plans/2026-09-09-x.md)\n"
            "- [幽灵](plans/2026-01-01-ghost.md)\n"
        )
        problems = docs_index.check_archive_completeness(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("ghost", problems[0])

    def test_links_outside_archive_ignored(self):
        """指向归档外的链接(如 `../../milestones.md`)不算悬空登记。

        参数说明:
            无。
        """
        write_file(self.root, "docs/milestones.md", "# 里程碑时间线\n")
        self._write_index(
            "- [x-design](specs/2026-09-09-x-design.md)\n"
            "- [x](plans/2026-09-09-x.md)\n"
            "- [里程碑](../../milestones.md)\n"
        )
        self.assertEqual(docs_index.check_archive_completeness(self.root), [])

    def test_missing_index_reported(self):
        """INDEX.md 不存在时给出「先跑 --write」,而不是静默通过。

        参数说明:
            无。
        """
        problems = docs_index.check_archive_completeness(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("--write", problems[0])


class EntryCompletenessTests(DocsIndexTestCase):
    """入口完整性:每份非归档文档都在 `docs/README.md` 里出现。"""

    def test_missing_entry_reported(self):
        """入口漏了一份 → 报出来。

        参数说明:
            无。
        """
        write_file(self.root, "docs/ops/runbook.md", "# 运维手册\n")
        write_file(self.root, "docs/README.md", "# 索引\n\n- [里程碑](milestones.md)\n")
        problems = docs_index.check_entry_completeness(self.root)
        # 骨架里还有 api/README.md 与 api/x.md 也没被这份手写入口覆盖。
        self.assertEqual(len(problems), 3)
        self.assertTrue(any("ops/runbook.md" in item for item in problems))

    def test_full_entry_has_no_problem(self):
        """生成出来的入口天然覆盖全部非归档文档。

        参数说明:
            无。
        """
        self.assertEqual(self.run_main("--write"), 0)
        self.assertEqual(docs_index.check_entry_completeness(self.root), [])


class ApiTableTests(DocsIndexTestCase):
    """接口一览表与 `openapi.yml` 的操作集合必须完全相等。"""

    def test_matching_table_has_no_problem(self):
        """表与契约一致 → 无问题。

        参数说明:
            无。
        """
        self.assertEqual(docs_index.check_api_table(self.root), [])

    def test_missing_row_reported(self):
        """契约有、表里没有 → 报出来(第 1 节修的就是这种缺行)。

        参数说明:
            无。
        """
        write_file(self.root, "docs/api/README.md", API_README.replace("| POST | `/api/v1/b` | B 接口 | [x](x.md) |\n", ""))
        problems = docs_index.check_api_table(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("缺 POST /api/v1/b", problems[0])

    def test_extra_row_reported(self):
        """表里有、契约没有 → 报出来(接口删了但表没删)。

        参数说明:
            无。
        """
        extra = API_README + "| GET | `/api/v1/gone` | 已删接口 | [x](x.md) |\n"
        write_file(self.root, "docs/api/README.md", extra)
        problems = docs_index.check_api_table(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("多出 GET /api/v1/gone", problems[0])

    def test_duplicate_row_reported(self):
        """同一行写两遍 → 报出来。

        参数说明:
            无。
        """
        duplicated = API_README + "| GET | `/api/v1/a` | A 接口(重复) | [x](x.md) |\n"
        write_file(self.root, "docs/api/README.md", duplicated)
        problems = docs_index.check_api_table(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("重复出现 2 次", problems[0])

    def test_openapi_parse_failure_is_error(self):
        """`openapi.yml` 解析不出操作 → 抛错(fail-closed),不是「0 个操作 = 合规」。

        参数说明:
            无。
        """
        write_file(self.root, "docs/api/openapi.yml", "openapi: 3.0.3\n")
        with self.assertRaises(ValueError):
            docs_index.parse_openapi_operations(self.root)

    def test_summary_counts(self):
        """生成区间里的份数来自扫描:分册数 / 路径数 / 操作数 / 表行数。

        参数说明:
            无。
        """
        body = docs_index.render_api_summary(self.root)
        self.assertIn("**1** 份人读分册", body)
        self.assertIn("**2** paths / **2** operations", body)
        self.assertIn("下表 **2** 行", body)


class ApiBlockSpliceTests(DocsIndexTestCase):
    """接口文档入口:只替换标记区间,区间外一字不动,换行风格跟随原文件。"""

    def test_splice_keeps_surrounding_text(self):
        """区间外的内容(标题、表、维护规则)原样保留。

        参数说明:
            无。
        """
        text = docs_index.render_api_readme(self.root)
        self.assertIn("# 接口文档", text)
        self.assertIn("| GET | `/api/v1/a` | A 接口 | [x](x.md) |", text)
        self.assertIn(docs_index.API_BLOCK_BEGIN, text)
        self.assertIn(docs_index.API_BLOCK_END, text)

    def test_splice_preserves_crlf(self):
        """CRLF 文件写完仍是 CRLF —— 否则「只改区间」会变成整文件换行重写。

        参数说明:
            无。
        """
        write_file(self.root, "docs/api/README.md", API_README, newline="\r\n")
        text = docs_index.render_api_readme(self.root)
        self.assertNotIn("\n", text.replace("\r\n", ""))

    def test_splice_is_idempotent(self):
        """同一份输入渲染两次结果相同(否则 --check 永远红)。

        参数说明:
            无。
        """
        write_file(self.root, "docs/api/README.md", docs_index.render_api_readme(self.root))
        self.assertEqual(docs_index.render_api_readme(self.root), docs_index._read_text(self.root / "docs/api/README.md"))

    def test_missing_marker_is_error(self):
        """标记缺失 → 抛错,交给上层判 2。

        参数说明:
            无。
        """
        write_file(self.root, "docs/api/README.md", "# 接口文档\n\n## 接口一览\n\n无标记\n")
        with self.assertRaises(ValueError):
            docs_index.render_api_readme(self.root)


class ApiVolumeCountTests(DocsIndexTestCase):
    """接口一览表的分册列:派生「每个分册几行」,供 `docs_lint` 的数字规则比对。"""

    def test_rows_carry_volume(self):
        """每行带上它指向的分册文件名(表最后一格的相对链接)。

        参数说明:
            无。
        """
        rows = docs_index.parse_api_table_rows(self.root)
        self.assertEqual(rows, [("GET", "/api/v1/a", "x.md"), ("POST", "/api/v1/b", "x.md")])

    def test_volume_counts(self):
        """按分册汇总行数。

        参数说明:
            无。
        """
        self.assertEqual(docs_index.api_volume_counts(self.root), {"x.md": 2})

    def test_row_without_volume_ignored(self):
        """没有分册格的行不计入任何分册(表结构被改坏时不至于张冠李戴)。

        参数说明:
            无。
        """
        write_file(
            self.root,
            "docs/api/README.md",
            API_README + "| GET | `/api/v1/c` | C 接口 | — |\n",
        )
        self.assertEqual(docs_index.api_volume_counts(self.root), {"x.md": 2})


class ErrorCodeDocumentationTests(DocsIndexTestCase):
    """业务码覆盖:`error_codes.py` 的每个码至少在一份分册里出现(总表已删除)。"""

    def test_all_codes_documented(self):
        """两个码都在 x.md 里出现 → 无问题。

        参数说明:
            无。
        """
        self.assertEqual(docs_index.check_error_codes_documented(self.root), [])

    def test_undocumented_code_reported(self):
        """新增一个码却没有任何分册提到它 → 报出来(客户端就查不到含义)。

        参数说明:
            无。
        """
        write_file(self.root, ERROR_CODES, "A = 40001  # 甲\nB = 40101  # 乙\nC = 40301  # 丙\n")
        problems = docs_index.check_error_codes_documented(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("40301", problems[0])

    def test_errors_md_does_not_count_as_coverage(self):
        """`errors.md` 自己不算覆盖 —— 它的手写总表正是第 6 节删掉的东西。

        参数说明:
            无。
        """
        write_file(self.root, "docs/api/errors.md", "# 错误码\n\n| 40001 | 甲 |\n")
        write_file(self.root, "docs/api/x.md", "# 分册 x\n")
        problems = docs_index.check_error_codes_documented(self.root)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("errors.md" not in item for item in problems))

    def test_unparseable_codes_is_error(self):
        """一个码都读不到 → 抛错(fail-closed),不是「没有码 = 全覆盖」。

        参数说明:
            无。
        """
        write_file(self.root, ERROR_CODES, "没有码\n")
        with self.assertRaises(ValueError):
            docs_index.read_error_codes(self.root)


class CommandLineTests(DocsIndexTestCase):
    """命令行:--check / --write / 退出码。"""

    def test_check_fails_when_generated_files_missing(self):
        """生成物不存在 → 退出码 1,并指出该跑 --write。

        参数说明:
            无。
        """
        self.assertEqual(self.run_main("--check"), 1)

    def test_write_then_check_is_green(self):
        """--write 之后 --check 绿,且三个生成物都落盘。

        参数说明:
            无。
        """
        self.assertEqual(self.run_main("--write"), 0)
        for rel in (docs_index.INDEX_REL, docs_index.ARCHIVE_INDEX_REL, docs_index.API_README_REL):
            self.assertTrue((self.root / rel).is_file(), rel)
        self.assertEqual(self.run_main("--check"), 0)

    def test_check_catches_hand_edit(self):
        """手改生成物 → 退出码 1。

        参数说明:
            无。
        """
        self.assertEqual(self.run_main("--write"), 0)
        path = self.root / docs_index.INDEX_REL
        path.write_bytes(path.read_bytes() + "\n手改一行\n".encode("utf-8"))
        self.assertEqual(self.run_main("--check"), 1)

    def test_check_and_write_conflict(self):
        """--check 与 --write 同时给 → 退出码 2。

        参数说明:
            无。
        """
        self.assertEqual(self.run_main("--check", "--write"), 2)

    def test_missing_docs_dir_is_error(self):
        """文档目录不存在 → 退出码 2(判不出来 ≠ 合规)。

        参数说明:
            无。
        """
        (self.root / "docs").rename(self.root / "docs-away")
        self.assertEqual(self.run_main("--check"), 2)

    def test_json_output_is_machine_readable(self):
        """--json 给出 ok / problems / counts,L4 判定器可直接读。

        参数说明:
            无。
        """
        self.assertEqual(self.run_main("--write"), 0)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = docs_index.main(["--root", str(self.root), "--check", "--json"])
        self.assertEqual(code, 0)
        payload = __import__("json").loads(buffer.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["counts"]["archive"], 2)


if __name__ == "__main__":
    unittest.main()
