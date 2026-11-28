"""``scripts/check_app_raw_values.py``(App 侧裸值门禁)的自测。

为什么要有它
------------
门禁本身坏了有两种方向,都不能静默:

- **漏报**:裸 hex / 裸字号 / 裸间距 / 裸圆角回到页面里,门禁却说合规 —— 这正是它存在的理由;
- **误报**:注释、字符串、生成物、``tokens.*`` 派生表达式被当成裸值判红,人只能把门禁关掉。

另外两个方向也钉住:白名单**只增不减**(条目失效却没红)与**工具自身出错**(找不到 token
生成物)不许伪装成绿。

全部用例用临时目录造样本,不依赖真实 ``app/lib`` 的内容(唯一例外是
``test_repository_baseline_is_clean``:它证明白名单与当前仓库仍然对得上)。

用法:
    python -m unittest scripts.test_check_app_raw_values -v
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts import check_app_raw_values as gate

#: 最小可用的 token 生成物样本(列名与 ``tokens.g.dart`` 的生成格式一致)。
TOKENS_SAMPLE = """\
// GENERATED CODE - DO NOT MODIFY BY HAND
const double fontSizeBody = 15;
const double fontSizeCaption = 13;
const double fontSizeDisplay = 32;
const double fontSizeMicro = 11;
const double fontSizeSubtitle = 17;
const double fontSizeTitle = 24;
const double radiusLg = 20;
const double radiusMd = 16;
const double radiusPill = 999;
const double radiusSm = 12;
const double radiusXl = 24;
const double radiusXs = 8;
const double space4 = 4;
const double space8 = 8;
const double space12 = 12;
const double space16 = 16;
const double space20 = 20;
const double space24 = 24;
const double space32 = 32;
const double space40 = 40;
"""


class GateTestCase(unittest.TestCase):
    """一个用例一个临时 ``app/lib`` 骨架。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.root = self.base / "lib"
        (self.root / "core" / "theme").mkdir(parents=True)
        (self.root / "core" / "theme" / "tokens.g.dart").write_text(TOKENS_SAMPLE, encoding="utf-8")

    def write(self, relative: str, text: str) -> None:
        """在扫描目录里写一个样本文件。"""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def scan(self, entries: tuple[gate.WhitelistEntry, ...] = ()) -> gate.Report:
        """扫临时目录(缺省不带白名单)。"""
        return gate.scan(self.root, entries=entries)


class NakedHexTests(GateTestCase):
    """裸 hex 的两个方向。"""

    def test_naked_hex_is_reported(self) -> None:
        self.write("features/x.dart", "const Color c = Color(0xFFB4610C);\n")
        problems = self.scan().violations
        self.assertEqual([item.rule for item in problems], ["hex"])
        self.assertIn("0xFFB4610C", problems[0].message)
        self.assertEqual(problems[0].line, 1)

    def test_hex_in_comment_and_string_is_not_code(self) -> None:
        self.write(
            "features/x.dart",
            "\n".join(
                [
                    "// 色值是 0xFFB4610C,只作说明",
                    "/* 块注释里写 0x1C1714 也不算 */",
                    "const String label = '取色 0xFFC93C22 记在这里';",
                    "const String raw = r'0xFF000000 原样字符串';",
                    "",
                ]
            ),
        )
        self.assertEqual(self.scan().violations, [])

    def test_generated_tokens_file_is_excluded(self) -> None:
        # 样本本身就是成片的 hex 常量:它必须被排除,否则门禁一上来就红成一片。
        self.write(
            "core/theme/tokens.g.dart",
            TOKENS_SAMPLE + "const Color brandDefaultLight = Color(0xFFC93C22);\n",
        )
        self.assertEqual(self.scan().violations, [])


class MaskingTests(GateTestCase):
    """抹码的边界:注释/字符串里的取值不是代码,但插值里的引号不许把后面的代码一起抹掉。"""

    def test_text_inside_string_is_not_code(self) -> None:
        self.write("features/x.dart", "final hint = 'padding: 16 / radius 12 见规范';\n")
        self.assertEqual(self.scan().violations, [])

    def test_quote_inside_interpolation_keeps_code_visible(self) -> None:
        # `'${data['k'] ?? ''}'` 在本仓库很常见:内层引号若让外层字符串提前收尾,下一行的
        # 裸值就会被当成字符串内容抹掉 —— 那是漏报,门禁最不该错的方向。
        self.write(
            "im/x.dart",
            "\n".join(
                [
                    "final label = 'k=${data['msg_id'] ?? ''}';",
                    "const Color c = Color(0xFFB4610C);",
                    "",
                ]
            ),
        )
        problems = self.scan().violations
        self.assertEqual([item.rule for item in problems], ["hex"])
        self.assertEqual(problems[0].line, 2)


class NakedFontSizeTests(GateTestCase):
    """裸字号与字号下限。"""

    def test_naked_font_size_is_reported_with_suggestion(self) -> None:
        self.write("features/x.dart", "final style = base.copyWith(fontSize: 17);\n")
        problems = self.scan().violations
        self.assertEqual([item.rule for item in problems], ["font-size"])
        self.assertIn("tokens.fontSizeSubtitle", problems[0].message)

    def test_font_size_below_floor_is_called_out(self) -> None:
        self.write("features/x.dart", "const style = TextStyle(fontSize: 9);\n")
        message = self.scan().violations[0].message
        self.assertIn("低于任意字号下限 11", message)

    def test_font_size_below_body_floor_is_called_out(self) -> None:
        self.write("features/x.dart", "const style = TextStyle(fontSize: 12);\n")
        message = self.scan().violations[0].message
        self.assertIn("低于正文下限 13", message)

    def test_token_font_size_passes(self) -> None:
        self.write("features/x.dart", "final style = base.copyWith(fontSize: tokens.fontSizeBody);\n")
        self.assertEqual(self.scan().violations, [])


class NakedSpacingAndRadiusTests(GateTestCase):
    """裸间距 / 裸圆角,以及 ``0`` 与 token 派生表达式的边界。"""

    def test_naked_edge_insets_are_reported(self) -> None:
        self.write(
            "features/x.dart",
            "final pad = const EdgeInsets.fromLTRB(16, 16, 16, 16);\n",
        )
        problems = self.scan().violations
        self.assertEqual([item.rule for item in problems], ["space"])
        self.assertIn("tokens.space16", problems[0].message)

    def test_naked_radius_is_reported(self) -> None:
        self.write("features/x.dart", "final r = BorderRadius.circular(12);\n")
        problems = self.scan().violations
        self.assertEqual([item.rule for item in problems], ["radius"])
        self.assertIn("tokens.radiusSm", problems[0].message)

    def test_zero_is_not_a_naked_value(self) -> None:
        # token 源里没有 0 档,0 表达「没有间距 / 没有圆角」,判红只会把刻意写法逼进白名单。
        self.write(
            "features/x.dart",
            "\n".join(
                [
                    "final a = const EdgeInsets.all(0);",
                    "final b = const EdgeInsets.only(left: 0, top: 0);",
                    "final c = BorderRadius.circular(0);",
                    "",
                ]
            ),
        )
        self.assertEqual(self.scan().violations, [])

    def test_token_derived_expression_passes(self) -> None:
        self.write(
            "features/x.dart",
            "\n".join(
                [
                    "final a = EdgeInsets.symmetric(horizontal: tokens.space4 / 2);",
                    "final b = const EdgeInsets.all(tokens.space16);",
                    "final c = BorderRadius.circular(tokens.radiusSm);",
                    "",
                ]
            ),
        )
        self.assertEqual(self.scan().violations, [])

    def test_naked_value_inside_multiline_call_is_reported(self) -> None:
        self.write(
            "features/x.dart",
            "\n".join(
                [
                    "final pad = EdgeInsets.symmetric(",
                    "  horizontal: tokens.space4,",
                    "  vertical: 1,",
                    ");",
                    "",
                ]
            ),
        )
        problems = self.scan().violations
        self.assertEqual(len(problems), 1)
        # 跨行调用的片段要覆盖整段调用,否则白名单里只剩一句认不出是谁的 `padding: ...(`。
        self.assertIn("vertical: 1", problems[0].snippet)


class WhitelistTests(GateTestCase):
    """白名单:逐处放行、只抵扣一处、失效即红。"""

    def test_whitelisted_bitmask_passes(self) -> None:
        self.write(
            "im/upload_idempotency.dart",
            "\n".join(
                [
                    "String key(int sequence) {",
                    "  final seq = (_keySequence = (_keySequence + 1) & 0xffffff).toRadixString(36);",
                    "  return seq;",
                    "}",
                    "",
                ]
            ),
        )
        self.assertEqual(len(self.scan(gate.WHITELIST).violations), 0)
        self.assertEqual(len(self.scan().violations), 1)

    def test_entry_only_covers_one_occurrence(self) -> None:
        snippet = "final r = BorderRadius.circular(2);"
        self.write("features/x.dart", f"{snippet}\n{snippet}\n")
        entry = gate.WhitelistEntry(
            path="features/x.dart",
            line=1,
            snippet=snippet,
            reason="自测样本",
            expiry="自测样本",
        )
        report = self.scan((entry,))
        # 一处片段对一处违规:同一文件里两处相同片段必须写两条,否则其中一处仍判红。
        self.assertEqual(len(report.violations), 1)
        self.assertEqual(len(report.justified), 1)

    def test_entry_matching_by_snippet_survives_line_shift(self) -> None:
        snippet = "final r = BorderRadius.circular(2);"
        self.write("features/x.dart", f"// 顶部多一行注释\n\n{snippet}\n")
        entry = gate.WhitelistEntry(
            path="features/x.dart",
            line=1,
            snippet=snippet,
            reason="自测样本",
            expiry="自测样本",
        )
        report = self.scan((entry,))
        self.assertEqual(report.violations, [])
        self.assertEqual(len(report.drift), 1)
        self.assertEqual(report.drift[0][1], 3)

    def test_stale_entry_fails_check(self) -> None:
        # 存量清掉之后条目还在:必须判红,否则白名单只增不减,门禁迟早被它关掉。
        self.write("features/x.dart", "final r = BorderRadius.circular(tokens.radiusSm);\n")
        entry = gate.WhitelistEntry(
            path="features/x.dart",
            line=1,
            snippet="final r = BorderRadius.circular(2);",
            reason="自测样本",
            expiry="自测样本",
        )
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            status = gate.check(self.root, entries=(entry,))
        self.assertEqual(status, gate.EXIT_FINDINGS)
        self.assertIn("白名单条目失效", buffer.getvalue())


class ToolingAndExitCodeTests(GateTestCase):
    """退出码口径:合规 0、违规 1、工具出错 2。"""

    def test_clean_tree_exits_zero(self) -> None:
        self.write("features/x.dart", "final pad = const EdgeInsets.all(tokens.space16);\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.check(self.root, entries=()), gate.EXIT_OK)

    def test_violation_exits_one(self) -> None:
        self.write("features/x.dart", "const Color c = Color(0xFFB4610C);\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.check(self.root, entries=()), gate.EXIT_FINDINGS)

    def test_missing_tokens_file_exits_two(self) -> None:
        (self.root / "core" / "theme" / "tokens.g.dart").unlink()
        self.write("features/x.dart", "final pad = const EdgeInsets.all(tokens.space16);\n")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(gate.check(self.root, entries=()), gate.EXIT_TOOLING)

    def test_main_check_mode_reports_findings(self) -> None:
        self.write("features/x.dart", "final r = BorderRadius.circular(12);\n")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            status = gate.main(["--check", "--root", str(self.root)])
        self.assertEqual(status, gate.EXIT_FINDINGS)
        self.assertIn("裸圆角", buffer.getvalue())

    def test_main_report_mode_is_not_a_gate(self) -> None:
        self.write("features/x.dart", "final r = BorderRadius.circular(12);\n")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            status = gate.main(["--root", str(self.root)])
        self.assertEqual(status, gate.EXIT_OK)
        self.assertIn("违规 1 处", buffer.getvalue())


class RepositoryBaselineTests(unittest.TestCase):
    """当前仓库的基线:白名单与代码仍然对得上(防止「条目失效却没人发现」)。"""

    def test_repository_baseline_is_clean(self) -> None:
        report = gate.scan(gate.DEFAULT_ROOT)
        self.assertEqual(
            [(item.display, item.line, item.message) for item in report.violations],
            [],
            "app/lib 里出现了新的裸值:改用 tokens,或按 scripts/check_app_raw_values.py 的白名单逐条登记",
        )
        self.assertEqual(
            [(entry.path, entry.line, entry.snippet) for entry in report.stale],
            [],
            "白名单条目已经对不上代码了:存量清掉就删条目,代码改过就重新核对",
        )


if __name__ == "__main__":
    unittest.main()
