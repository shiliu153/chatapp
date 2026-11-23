"""``scripts/design_contrast.py`` 的自测(纯离线,真实源头 + 临时样本)。

进 CI 的 `contract` 轨。对比度门禁最危险的失效形态不是「算了但算错」,而是
**「没算,却绿了」** —— 所以自测的重点在两个 fail-closed 面:

- **口径读不出来**:规范被挪走、§3.4 标题改名、表被改坏(只剩一两行),都必须判红,
  绝不允许「解析出 0 条规则 → 0 条违例 → 通过」;
- **配对表引用不存在的档**:``rule = "正文"`` 在规范里找不到对应行时必须报错,
  否则阈值无从判定,门禁变成空转。

另外钉住两条算法的已知答案(而不是「跑一遍看它不报错」):

- WCAG 的锚点:**黑/白 = 21:1**;
- APCA 的语序:深字浅底与浅字深底**符号相反**、量级都在 100 上下;
- **自然序与分级映射**:``三级`` 必须命中 ``三级（时间戳）``,``强调文字`` 命中
  ``强调文字 / 链接``。

以及一个真实仓库断言:当前双模式的全部配对都必须过线(= 门禁在主仓库为绿)。
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts import design_contrast, design_tokens

SPEC_WITH_TABLE = """# 假规范

### 3.4 对比度口径（分级，且是门禁）

| 用途 | 字号/字重 | WCAG 下限 | APCA Lc 下限 |
|---|---|---|---|
| 正文 | 15–17px / w400 | 4.5 | 75 |
| 次级 | 13–15px | 4.5 | 60 |
| 三级（时间戳） | 11–13px | 3.0 | 45 |

正文到此结束。
"""

SPEC_TRUNCATED = """# 假规范

### 3.4 对比度口径（分级，且是门禁）

| 用途 | 字号/字重 | WCAG 下限 | APCA Lc 下限 |
|---|---|---|---|
| 正文 | 15–17px / w400 | 4.5 | 75 |
"""

SPEC_NO_SECTION = """# 假规范

## 3. 色彩系统

没有对比度小节。
"""

BAD_PAIRS = """[[pair]]
name = "自己撞自己"
rule = "正文"
fg = "color.text.primary"
bg = "color.text.primary"
"""


def _quiet() -> contextlib.AbstractContextManager:
    """吞掉 stdout(失败行是预期内的)。

    返回参数:
        contextlib.AbstractContextManager: 重定向上下文。

    使用示例:
        ``with _quiet(): design_contrast.check()``

    备注信息:
        只吞 stdout;真正要看的异常仍会抛出。
    """
    return contextlib.redirect_stdout(io.StringIO())


class TestAlgorithms(unittest.TestCase):
    """两条曲线的已知答案。"""

    def test_wcag_black_on_white_is_21(self) -> None:
        self.assertAlmostEqual(design_contrast.wcag_ratio("#000000", "#FFFFFF"), 21.0, places=2)

    def test_wcag_is_symmetric(self) -> None:
        self.assertAlmostEqual(design_contrast.wcag_ratio("#1C1714", "#FBF7F3"),
                               design_contrast.wcag_ratio("#FBF7F3", "#1C1714"), places=6)

    def test_apca_dark_on_light_is_positive(self) -> None:
        self.assertGreater(design_contrast.apca_lc("#1C1714", "#FBF7F3"), 90)

    def test_apca_light_on_dark_is_negative(self) -> None:
        self.assertLess(design_contrast.apca_lc("#F6F1EB", "#14110F"), -90)

    def test_apca_identical_colors_is_zero(self) -> None:
        self.assertEqual(design_contrast.apca_lc("#C93C22", "#C93C22"), 0.0)

    def test_hex_with_alpha_is_parsed_by_rgb_only(self) -> None:
        self.assertEqual(design_contrast.parse_hex("#1C1714EB"), (0x1C, 0x17, 0x14))

    def test_short_hex_expands(self) -> None:
        self.assertEqual(design_contrast.parse_hex("#FFF"), (255, 255, 255))


class TestSpecParsing(unittest.TestCase):
    """§3.4 分级表的解析与 fail-closed。"""

    def _write(self, text: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        return Path(handle.name)

    def test_real_spec_exposes_five_bands(self) -> None:
        rules = design_contrast.parse_rules(design_contrast.find_spec())
        # 规则键是整行标签(``三级（时间戳）``),比对走前缀解析,与门禁同一路径。
        for label, expected in (
            ("正文", (4.5, 75.0)),
            ("次级", (4.5, 60.0)),
            ("三级", (3.0, 45.0)),
            ("按钮文字", (4.5, 60.0)),
            ("强调文字", (4.5, 60.0)),
        ):
            self.assertEqual(design_contrast.rule_for(label, rules), expected,
                             f"规范 §3.4 的「{label}」档阈值与预期不符")

    def test_missing_section_fails_closed(self) -> None:
        path = self._write(SPEC_NO_SECTION)
        with self.assertRaises(design_tokens.TokenError):
            design_contrast.parse_rules(path)

    def test_truncated_table_fails_closed(self) -> None:
        path = self._write(SPEC_TRUNCATED)
        with self.assertRaises(design_tokens.TokenError):
            design_contrast.parse_rules(path)

    def test_table_parses_to_expected_values(self) -> None:
        path = self._write(SPEC_WITH_TABLE)
        rules = design_contrast.parse_rules(path)
        self.assertEqual(rules["次级"], (4.5, 60.0))
        self.assertEqual(len(rules), 3)

    def test_rule_lookup_uses_prefix(self) -> None:
        rules = {"三级（时间戳）": (3.0, 45.0), "强调文字 / 链接": (4.5, 60.0)}
        self.assertEqual(design_contrast.rule_for("三级", rules), (3.0, 45.0))
        self.assertEqual(design_contrast.rule_for("强调文字", rules), (4.5, 60.0))

    def test_unknown_rule_raises(self) -> None:
        with self.assertRaises(design_tokens.TokenError):
            design_contrast.rule_for("正文", {"次级": (4.5, 60.0)})


class TestPairs(unittest.TestCase):
    """配对表读取与缺文件的口径。"""

    def test_repo_pairs_all_have_required_fields(self) -> None:
        pairs = design_contrast.load_pairs()
        self.assertGreater(len(pairs), 0)
        for pair in pairs:
            self.assertTrue({"name", "rule", "fg", "bg"} <= set(pair))

    def test_missing_pairs_file_raises(self) -> None:
        with self.assertRaises(design_tokens.TokenError):
            design_contrast.load_pairs(Path(tempfile.gettempdir()) / "no-such-pairs.toml")


class TestEvaluation(unittest.TestCase):
    """端到端:真实源头 + 人造失败。"""

    def test_repository_is_all_green(self) -> None:
        results = design_contrast.evaluate()
        self.assertTrue(results, "一条配对都没算出来")
        failures = [row for row in results if not row["ok"]]
        self.assertEqual(failures, [], f"对比度不过线:{failures}")

    def test_both_modes_are_covered(self) -> None:
        modes = {row["mode"] for row in design_contrast.evaluate()}
        self.assertEqual(modes, {"light", "dark"})

    def test_identity_pair_is_detected_as_failure(self) -> None:
        handle = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8")
        handle.write(BAD_PAIRS)
        handle.close()
        with _quiet():
            self.assertEqual(design_contrast.check(pairs_path=Path(handle.name)), 1)

    def test_missing_spec_turns_gate_red(self) -> None:
        with _quiet():
            self.assertEqual(
                design_contrast.check(spec_path=Path(tempfile.gettempdir()) / "no-such-spec.md"), 1)


if __name__ == "__main__":
    unittest.main()
