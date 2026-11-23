"""``scripts/design_tokens.py`` 的自测(纯离线,临时目录里造样本)。

进 CI 的 `contract` 轨。它钉住四类事,每一类的两个方向都不能静默:

- **别名解析**:``{color.paper.5}`` 要能展开到字面量;悬空引用、循环引用必须**报错**
  而不是产出空值 —— 空值会一路跑到客户端渲染成透明,比门禁红难查得多;
- **标识符生成**:点分路径转 Dart / CSS 名的规则(首段小写、后续段大写、数字段直拼),
  以及色阶的**自然序**(``ember.50`` 必须排在 ``ember.100`` 前面);
- **颜色转换**:8 位 CSS(``RRGGBBAA``)转 Dart(``AARRGGBB``)时分量顺序要换 ——
  这条错了会让所有半透明遮罩的 alpha 落到红通道上,肉眼以为是「颜色偏了」;
- **漂移判定**:源头改了但生成物没重生成必须红(漏报 = 门禁白装);
  生成物与源头一致时必须绿(误报 = 人被逼着把门禁关掉)。

另外钉住一个**判定器自身故障**的口径:``--check`` / ``--write`` 不显式二选一必须是
退出码 2,不能默认干某件事。
"""

from __future__ import annotations

import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from scripts import design_tokens


def _quiet() -> contextlib.AbstractContextManager:
    """把 stdout 吞掉,避免用例输出污染 CI 日志。

    返回参数:
        contextlib.AbstractContextManager: 重定向到 ``io.StringIO`` 的上下文。

    使用示例:
        ``with _quiet(): design_tokens.check()``

    备注信息:
        门禁脚本会打印 ``::error`` 行,自测里那些行是预期内的,不该出现在通过日志里。
    """
    return contextlib.redirect_stdout(io.StringIO())


class TestFlatten(unittest.TestCase):
    """压平与原始值读取。"""

    def test_nested_groups_become_dotted_paths(self) -> None:
        flat = design_tokens.flatten({"color": {"brand": {"default": {"$value": "#C93C22", "$type": "color"}}}})
        self.assertEqual(list(flat), ["color.brand.default"])

    def test_dollar_keys_are_not_path_segments(self) -> None:
        flat = design_tokens.flatten({"space": {"4": {"$value": "4px", "$type": "dimension", "$description": "x"}}})
        self.assertIn("space.4", flat)
        self.assertNotIn("space.4.$description", flat)

    def test_scalar_leaf_is_rejected(self) -> None:
        with self.assertRaises(design_tokens.TokenError):
            design_tokens.flatten({"color": {"brand": "#C93C22"}})

    def test_tokens_studio_classic_value_key_is_accepted(self) -> None:
        self.assertEqual(design_tokens.raw_value({"value": "#FFFFFF"}), "#FFFFFF")


class TestResolve(unittest.TestCase):
    """别名展开。"""

    def setUp(self) -> None:
        self.flat = design_tokens.flatten({
            "color": {
                "paper": {"5": {"$value": "#FBF7F3", "$type": "color"}},
                "surface": {"page": {"$value": "{color.paper.5}", "$type": "color"}},
                "alias": {"page": {"$value": "{color.surface.page}", "$type": "color"}},
            }
        })

    def test_alias_chain_resolves_to_literal(self) -> None:
        self.assertEqual(design_tokens.resolve("color.alias.page", self.flat), "#FBF7F3")

    def test_dangling_alias_raises(self) -> None:
        flat = design_tokens.flatten({"a": {"b": {"$value": "{not.there}", "$type": "color"}}})
        with self.assertRaises(design_tokens.TokenError):
            design_tokens.resolve("a.b", flat)

    def test_cycle_raises(self) -> None:
        flat = design_tokens.flatten({
            "a": {"$value": "{b}", "$type": "color"},
            "b": {"$value": "{a}", "$type": "color"},
        })
        with self.assertRaises(design_tokens.TokenError):
            design_tokens.resolve("a", flat)

    def test_literal_value_passes_through(self) -> None:
        self.assertEqual(design_tokens.resolve("color.paper.5", self.flat), "#FBF7F3")


class TestNaming(unittest.TestCase):
    """Dart 与 CSS 标识符。"""

    def test_dart_camel_case(self) -> None:
        self.assertEqual(design_tokens.camel("color.status.onDanger"), "colorStatusOnDanger")
        self.assertEqual(design_tokens.camel("space.20"), "space20")
        self.assertEqual(design_tokens.camel("elevation.1"), "elevation1")
        self.assertEqual(design_tokens.camel("motion.spring.fast.damping"), "motionSpringFastDamping")

    def test_css_kebab_case(self) -> None:
        self.assertEqual(design_tokens.kebab("font.lineHeight.body"), "--font-line-height-body")
        self.assertEqual(design_tokens.kebab("motion.reducedDurationMs"), "--motion-reduced-duration-ms")
        self.assertEqual(design_tokens.kebab("radius.xs"), "--radius-xs")

    def test_numeric_segments_sort_naturally(self) -> None:
        paths = ["color.ember.100", "color.ember.50", "color.ember.900"]
        self.assertEqual(sorted(paths, key=design_tokens.natural_key),
                         ["color.ember.50", "color.ember.100", "color.ember.900"])


class TestColorConversion(unittest.TestCase):
    """十六进制到 Dart 字面量。"""

    def test_six_digit_gets_full_alpha(self) -> None:
        self.assertEqual(design_tokens.dart_color("#C93C22"), "0xFFC93C22")

    def test_eight_digit_swaps_alpha_to_front(self) -> None:
        self.assertEqual(design_tokens.dart_color("#1C1714EB"), "0xEB1C1714")

    def test_lowercase_input_is_normalised(self) -> None:
        self.assertEqual(design_tokens.dart_color("#ffffff"), "0xFFFFFFFF")

    def test_bad_length_raises(self) -> None:
        with self.assertRaises(design_tokens.TokenError):
            design_tokens.dart_color("#FFF")


class TestGeneratedContent(unittest.TestCase):
    """生成物内容的形状(用真实源头,不做假数据)。"""

    def test_semantic_tokens_only_in_mode_map(self) -> None:
        light = design_tokens.load_mode("light")
        self.assertNotIn("color.paper.5", light)
        self.assertIn("color.surface.page", light)

    def test_light_and_dark_differ_on_brand(self) -> None:
        self.assertNotEqual(design_tokens.load_mode("light")["color.brand.default"]["value"],
                            design_tokens.load_mode("dark")["color.brand.default"]["value"])

    def test_dart_emits_type_per_kind(self) -> None:
        self.assertEqual(design_tokens.dart_type({"value": "#FFFFFF", "type": "color"}), "Color")
        self.assertEqual(design_tokens.dart_type({"value": "16px", "type": "dimension"}), "double")
        self.assertEqual(design_tokens.dart_type({"value": 700, "type": "fontWeight"}), "int")
        self.assertEqual(design_tokens.dart_type({"value": "Fraunces", "type": "fontFamily"}), "String")

    def test_dart_number_keeps_two_decimals(self) -> None:
        """``number`` 类型必须保住两位小数(行高 1.55 不能变成 1.6)。

        备注信息：``:.1f`` 时代 Dart 侧 body 行高是 1.6、CSS 侧 1.55，而规范写 1.55 ——
        两个生成物各说一套，``--check`` 只比字节所以发现不了。这条钉住两个方向：
        该保留的小数不能被四舍五入，整数又要补 ``.0`` 才仍是 Dart 的 ``double``。
        """
        for value, expected in ((1.55, "1.55"), (1.15, "1.15"), (1.25, "1.25"),
                                (1.3, "1.3"), (1.0, "1.0"), (0, "0.0")):
            with self.subTest(value=value):
                self.assertEqual(
                    design_tokens.dart_literal({"value": value, "type": "number"}), expected)

    def test_repo_line_heights_match_the_token_source(self) -> None:
        """仓库生成物里的行高常量必须与 ``design/tokens/scale.json`` 逐值相等。"""
        scale = design_tokens.load_scale()
        dart = design_tokens.emit_dart(
            design_tokens.load_mode("light"), design_tokens.load_mode("dark"), scale)
        line_heights = {
            path: token for path, token in scale.items() if path.startswith("font.lineHeight.")
        }
        self.assertGreaterEqual(len(line_heights), 4, "行高 token 数量不对劲")
        for path, token in line_heights.items():
            step = path.rsplit(".", 1)[-1]
            name = f"fontLineHeight{step[:1].upper()}{step[1:]}"
            with self.subTest(path=path):
                self.assertIn(
                    f"const double {name} = {design_tokens.dart_double(float(token['value']))};",
                    dart,
                )

    def test_unknown_type_raises(self) -> None:
        with self.assertRaises(design_tokens.TokenError):
            design_tokens.dart_type({"value": 1, "type": "gradient"})

    def test_dart_output_has_no_block_comment_markers(self) -> None:
        """生成物里不允许出现 ``/*`` 或 ``*/``。

        备注信息：Dart 的块注释**可以嵌套**，头部文案里一旦带上 ``/*`` 就会打开一层
        永不闭合的注释，生成物直接是语法错误；而 ``--check`` 只比字节，发现不了这种错。
        2026-11-23 真的产出过一份这样的文件，被 ``flutter analyze`` 抓到。
        """
        dart = design_tokens.emit_dart(
            design_tokens.load_mode("light"), design_tokens.load_mode("dark"), design_tokens.load_scale())
        self.assertNotIn("/*", dart)
        self.assertNotIn("*/", dart)

    def test_dart_identifiers_are_legal(self) -> None:
        dart = design_tokens.emit_dart(
            design_tokens.load_mode("light"), design_tokens.load_mode("dark"), design_tokens.load_scale())
        names = re.findall(r"^const \w+ (\w+) =", dart, flags=re.MULTILINE)
        self.assertGreater(len(names), 20, "生成物里的常量数量不对劲")
        for name in names:
            self.assertRegex(name, r"^[A-Za-z_][A-Za-z0-9_]*$", f"非法 Dart 标识符:{name}")


class TestModeParity(unittest.TestCase):
    """明暗两套必须同键集(否则深色模式静默回落到浅色值)。"""

    def test_repository_modes_share_keys(self) -> None:
        light = design_tokens.load_mode("light")
        dark = design_tokens.load_mode("dark")
        self.assertEqual(set(light), set(dark))

    def test_missing_dark_token_raises(self) -> None:
        with self.assertRaises(design_tokens.TokenError):
            design_tokens.ensure_mode_parity({"color.a": {}}, {"color.b": {}})

    def test_parity_passes_on_identical_keys(self) -> None:
        design_tokens.ensure_mode_parity({"color.a": {}}, {"color.a": {}})

    def test_css_dark_blocks_cover_every_root_variable(self) -> None:
        css = design_tokens.emit_css(
            design_tokens.load_mode("light"), design_tokens.load_mode("dark"), design_tokens.load_scale())
        blocks = {}
        current = None
        for line in css.splitlines():
            stripped = line.strip()
            if stripped.startswith(":root {") or stripped.startswith(":root:not("):
                current = ":root"
            elif stripped.startswith('[data-theme="dark"]') or (stripped.endswith("{") and "[data-theme" in stripped):
                current = "dark" if '"dark"' in stripped else "light"
            elif stripped == "}":
                current = None
            elif current and ":" in stripped and stripped.startswith("--"):
                name = stripped.split(":")[0]
                blocks.setdefault(current, set()).add(name)
        root_vars = {name for name in blocks.get(":root", set()) if name.startswith("--color-")}
        self.assertTrue(root_vars, ":root 里没有任何颜色变量")
        self.assertLessEqual(root_vars, blocks.get("dark", set()),
                             "深色块缺了颜色变量 —— 这些元素在深色模式下会回落到浅色值")


class TestCheckAndWrite(unittest.TestCase):
    """漂移判定的两个方向。"""

    def _redirect_outputs(self, tmp: Path) -> dict[str, Path]:
        return {
            "dart": tmp / "tokens.g.dart",
            "css": tmp / "tokens.generated.css",
            "resolved": tmp / "tokens.resolved.json",
        }

    def test_write_then_check_is_green(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            outs = self._redirect_outputs(tmp)
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch_outputs(outs))
                with _quiet():
                    self.assertEqual(design_tokens.write(), 0)
                    self.assertEqual(design_tokens.check(), 0)
                    self.assertTrue(all(path.exists() for path in outs.values()))

    def test_stale_artifact_turns_gate_red(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            outs = self._redirect_outputs(tmp)
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch_outputs(outs))
                with _quiet():
                    self.assertEqual(design_tokens.write(), 0)
                outs["css"].write_bytes(b"/* hand edited */\n")
                with _quiet():
                    self.assertEqual(design_tokens.check(), 1)

    def test_missing_artifact_turns_gate_red(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            outs = self._redirect_outputs(tmp)
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch_outputs(outs))
                with _quiet():
                    self.assertEqual(design_tokens.check(), 1)

    def test_repo_artifacts_match_sources(self) -> None:
        with _quiet():
            self.assertEqual(design_tokens.check(), 0,
                             "仓库里的生成物与 design/tokens/*.json 不一致;跑 python scripts/design_tokens.py --write")

    def test_cli_requires_explicit_mode(self) -> None:
        with self.assertRaises(SystemExit) as raised, _quiet(), contextlib.redirect_stderr(io.StringIO()):
            design_tokens.main([])
        self.assertEqual(raised.exception.code, 2)


@contextlib.contextmanager
def patch_outputs(outs: dict[str, Path]):
    """把生成物路径临时指向别的目录。

    参数说明:
        outs: ``{"dart"|"css"|"resolved": 路径}``。

    返回参数:
        contextmanager: 退出时恢复原路径。

    使用示例:
        ``with patch_outputs(outs): design_tokens.write()``

    备注信息:
        直接改模块级常量而不复制 ``build()``:自测必须走**和门禁同一条**装配路径,
        否则测的是另一份实现。只用标准库实现,不依赖 ``unittest.mock`` 之外的补丁机制。
    """
    originals = (design_tokens.DART_OUT, design_tokens.CSS_OUT, design_tokens.RESOLVED_OUT)
    design_tokens.DART_OUT = outs["dart"]
    design_tokens.CSS_OUT = outs["css"]
    design_tokens.RESOLVED_OUT = outs["resolved"]
    try:
        yield
    finally:
        design_tokens.DART_OUT, design_tokens.CSS_OUT, design_tokens.RESOLVED_OUT = originals


if __name__ == "__main__":
    unittest.main()
