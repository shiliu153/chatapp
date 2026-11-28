"""``scripts/figma_tokens_roundtrip.py`` 的自测（纯离线，临时目录里造样本）。

进 CI 的 `contract` 轨。它钉住的是「Figma 侧只改值」这条纪律的机械判据：

- **形态兼容**：Tokens Studio 默认是 legacy 格式（`value` 而非 `$value`）、会把
  `#RRGGBBAA` 改写成语义等价的 `rgba()`、会把 `fontFamily` 写成数组、会往导出物里塞
  `$themes` / `$metadata` 两个仓库没有的包裹块。这些**都不许**被判成结构变更 ——
  否则第一次真实往返就会红一片，人只能把校验器关掉；
- **值 vs 结构**：路径增删、类型变更、描述变更必须判结构并**拒绝落盘**；
  只有 `$value` 变了才算值变更；
- **落盘不制造噪声**：写回源文件后，除被改的那一处值以外必须逐字节不变（含换行符）——
  这一条破了，「diff 只落在值上」就只是口号。

四个真实源文件（`design/tokens/*.json`）的字节级往返也钉在这里：本机检出 LF 与 CRLF
并存，`dump_source` 必须按各文件自己的换行符写回。
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts import figma_tokens_roundtrip as rt


def _quiet() -> contextlib.AbstractContextManager:
    """把 stdout 吞掉，避免用例输出污染 CI 日志。

    返回参数:
        contextlib.AbstractContextManager: 重定向到 ``io.StringIO`` 的上下文。

    使用示例:
        ``with _quiet(): rt.report_set("light", doc, False)``

    备注信息:
        校验器会打印 ``::error`` 行，自测里那些行是预期内的，不该出现在通过日志里。
    """
    return contextlib.redirect_stdout(io.StringIO())


def _capture() -> tuple[io.StringIO, contextlib.AbstractContextManager]:
    """同时拿到缓冲区与重定向上下文（需要在断言里读输出时用）。

    返回参数:
        tuple: ``(缓冲区, 上下文)``。

    使用示例:
        ``buffer, ctx = _capture(); with ctx: ...``

    备注信息:
        ``_quiet`` 只吞不留，断言输出内容时用本函数。
    """
    buffer = io.StringIO()
    return buffer, contextlib.redirect_stdout(buffer)


#: 一个「最小但形态齐全」的临时 token 仓库：组、别名、多类型、CRLF 文件各一份。
_LIGHT_FIXTURE = {
    "color": {
        "surface": {"page": {"$value": "{color.paper.5}", "$type": "color"}},
        "brand": {
            "default": {
                "$value": "{color.ember.600}",
                "$type": "color",
                "$description": "品牌锚点",
            },
            "on": {"$value": "#FFFFFF", "$type": "color"},
        },
        "overlay": {
            "scrim": {"$value": "#1C1714EB", "$type": "color"},
        },
    },
    "font": {
        "family": {"display": {"$value": "Fraunces", "$type": "fontFamily"}},
        "size": {"body": {"$value": "15px", "$type": "dimension"}},
        "weight": {"body": {"$value": 400, "$type": "fontWeight"}},
    },
    "space": {"16": {"$value": "16px", "$type": "dimension"}},
    "motion": {"reducedDurationMs": {"$value": 120, "$type": "duration"}},
}


class RoundtripFixture(unittest.TestCase):
    """带一个临时 token 仓库的基类（把 ``TOKENS_DIR`` 指到临时目录）。

    备注信息:
        落盘用例绝不能碰真仓库：`--apply` 会写 ``design/tokens/*.json``，
        而「试验值不进仓库」是本单的验收口径之一。
    """

    def setUp(self) -> None:
        """建临时目录、写一份 CRLF 的 light 源文件、替换模块常量。"""
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / rt.SET_FILES["light"]).write_bytes(
            rt.dump_source(_LIGHT_FIXTURE, "\r\n").encode("utf-8")
        )
        (self.tmp / rt.SET_FILES["dark"]).write_bytes(
            rt.dump_source({"color": {"surface": {"page": {"$value": "#14110F", "$type": "color"}}}}, "\n").encode("utf-8")
        )
        self._patch = unittest.mock.patch.object(rt, "TOKENS_DIR", self.tmp)
        self._patch.start()

    def tearDown(self) -> None:
        """撤销常量替换并删掉临时目录。"""
        self._patch.stop()
        self._tmp.cleanup()

    def source_text(self, set_name: str = "light") -> str:
        """读回临时仓库里某个 set 的源文本。

        参数说明:
            set_name: set 名。

        返回参数:
            str: 文件内容（保留原换行符）。

        使用示例:
            ``self.source_text("light")``

        备注信息:
            用 ``read_bytes().decode`` 而不是 ``read_text``：后者会把 CRLF 归一成 LF，
            那样「换行符被改写」这个缺陷就测不出来。
        """
        return (self.tmp / rt.SET_FILES[set_name]).read_bytes().decode("utf-8")


class TestDumpStability(unittest.TestCase):
    """钉住「读进来再写回去必须逐字节不变」。"""

    def test_real_sources_roundtrip_byte_identical(self) -> None:
        """四个真实源文件的往返必须零字节差异（含各自不同的换行符）。"""
        for name, filename in rt.SET_FILES.items():
            with self.subTest(set_name=name):
                path = rt.TOKENS_DIR / filename
                raw = path.read_bytes()
                dumped = rt.dump_source(rt.read_json(path), rt.detect_eol(raw))
                self.assertEqual(raw, dumped.encode("utf-8"), f"{filename} 往返后字节不一致")

    def test_detect_eol(self) -> None:
        """CRLF 与 LF 都要认对。"""
        self.assertEqual(rt.detect_eol(b'{\r\n  "a": 1\r\n}\r\n'), "\r\n")
        self.assertEqual(rt.detect_eol(b'{\n  "a": 1\n}\n'), "\n")
        self.assertEqual(rt.detect_eol(b"{}"), "\n")


class TestCanonicalForms(unittest.TestCase):
    """钉住「同义写法不许算成值变更」。"""

    def test_hex_and_rgba_are_the_same_color(self) -> None:
        """8 位 hex 与 rgba() 归一到同一形态（alpha 允许量化误差）。"""
        self.assertTrue(rt.colors_close(rt.canonical_color("#1C1714EB"), rt.canonical_color("rgba(28,23,20,0.92)")))
        self.assertEqual(rt.canonical_color("#1C1714"), rt.canonical_color("rgb(28,23,20)"))
        self.assertEqual(rt.canonical_color("#FFF"), rt.canonical_color("#FFFFFF"))

    def test_real_alpha_change_is_not_swallowed(self) -> None:
        """容差只吸收量化误差：0.92→0.85 这种真改动必须判得出来。"""
        self.assertFalse(
            rt.colors_close(rt.canonical_color("#1C1714EB"), rt.canonical_color("rgba(28,23,20,0.85)"))
        )
        self.assertFalse(
            rt.colors_close(rt.canonical_color("#1C1714"), rt.canonical_color("rgba(60,23,20,1)"))
        )

    def test_dtcg_color_object(self) -> None:
        """DTCG 的对象形态颜色要与等价 hex 对齐。"""
        dtcg = {"colorSpace": "srgb", "components": [1, 1, 1], "alpha": 1}
        self.assertEqual(rt.canonical_color(dtcg), rt.canonical_color("#FFFFFF"))

    def test_dimension_forms(self) -> None:
        """数值、带单位文本、DTCG 对象三种尺寸写法归一。"""
        self.assertEqual(rt.canonical_dimension(8), "8px")
        self.assertEqual(rt.canonical_dimension("8px"), "8px")
        self.assertEqual(rt.canonical_dimension({"value": 8, "unit": "px"}), "8px")
        self.assertEqual(rt.canonical_dimension("999px"), "999px")

    def test_font_family_forms(self) -> None:
        """数组与逗号串两种字族写法归一。"""
        self.assertEqual(rt.canonical_family(["Fraunces"]), "Fraunces")
        self.assertEqual(rt.canonical_family("Fraunces"), "Fraunces")
        self.assertEqual(
            rt.canonical_family(["PingFang SC", "sans-serif"]),
            rt.canonical_family("PingFang SC ,  sans-serif"),
        )

    def test_type_aliases(self) -> None:
        """legacy 类型别名要落到 DTCG 类型上。"""
        self.assertEqual(rt.normalize_type("spacing"), "dimension")
        self.assertEqual(rt.normalize_type("borderRadius"), "dimension")
        self.assertEqual(rt.normalize_type("color"), "color")
        self.assertIsNone(rt.normalize_type(None))


class TestFlatten(unittest.TestCase):
    """钉住展开口径：包裹块跳过、legacy 键名照样认。"""

    def test_skips_wrapper_blocks(self) -> None:
        """`$themes` / `$metadata` 不许出现在展开结果里。"""
        doc = {
            "$themes": [{"name": "light", "selectedTokenSets": {"light": "enabled"}}],
            "$metadata": {"tokenSetOrder": ["light", "dark"]},
            "color": {"brand": {"$value": "#C93C22", "$type": "color"}},
        }
        self.assertEqual(list(rt.flatten(doc)), ["color.brand"])

    def test_legacy_keys_are_recognized(self) -> None:
        """legacy 格式（`value` / `type`）与 DTCG 形态展开结果一致。"""
        legacy = {"color": {"brand": {"value": "#C93C22", "type": "color"}}}
        dtcg = {"color": {"brand": {"$value": "#C93C22", "$type": "color"}}}
        self.assertEqual(rt.flatten(legacy), rt.flatten(dtcg))

    def test_group_level_type_is_not_a_token(self) -> None:
        """分组上写 `$type` 不算叶子 token，子树要继续展开。"""
        doc = {"space": {"$type": "dimension", "16": {"$value": "16px"}}}
        self.assertEqual(list(rt.flatten(doc)), ["space.16"])


class TestCompare(RoundtripFixture):
    """钉住值变更与结构变更的分界。"""

    def test_value_only_change(self) -> None:
        """只改一个值：1 处值变更、0 处结构问题。"""
        export = json.loads(json.dumps(_LIGHT_FIXTURE))
        export["color"]["brand"]["default"]["$value"] = "#B42912"
        changes, problems = rt.compare(rt.flatten(_LIGHT_FIXTURE), rt.flatten(export))
        self.assertEqual(problems, [])
        self.assertEqual([change["path"] for change in changes], ["color.brand.default"])

    def test_semantically_equal_export_is_clean(self) -> None:
        """等价改写（hex→rgba、8→px、数组字族）不许产生任何变更。"""
        export = {
            "$metadata": {"tokenSetOrder": ["light"]},
            "color": {
                "overlay": {"scrim": {"value": "rgba(28, 23, 20, 0.92)", "type": "color"}},
                "brand": {
                    "on": {"value": "#FFFFFFFF", "type": "color"},
                    "default": {"value": "{color.ember.600}", "type": "color", "description": "品牌锚点"},
                },
                "surface": {"page": {"value": "{color.paper.5}", "type": "color"}},
            },
            "font": {
                "family": {"display": {"value": ["Fraunces"], "type": "fontFamilies"}},
                "size": {"body": {"value": 15, "type": "fontSizes"}},
                "weight": {"body": {"value": 400, "type": "fontWeights"}},
            },
            "space": {"16": {"value": "16px", "type": "spacing"}},
            "motion": {"reducedDurationMs": {"value": "120ms", "type": "duration"}},
        }
        changes, problems = rt.compare(rt.flatten(_LIGHT_FIXTURE), rt.flatten(export))
        self.assertEqual(problems, [])
        self.assertEqual(changes, [])

    def test_added_token_is_structure(self) -> None:
        """导出物多出 token 判结构。"""
        export = json.loads(json.dumps(_LIGHT_FIXTURE))
        export["color"]["surface"]["raised"] = {"$value": "#FFFFFF", "$type": "color"}
        _, problems = rt.compare(rt.flatten(_LIGHT_FIXTURE), rt.flatten(export))
        self.assertTrue(any("多出 token" in problem for problem in problems))

    def test_missing_token_is_structure(self) -> None:
        """导出物少 token 判结构（免费档单文件同步最容易发生的一件事）。"""
        export = json.loads(json.dumps(_LIGHT_FIXTURE))
        del export["space"]["16"]
        _, problems = rt.compare(rt.flatten(_LIGHT_FIXTURE), rt.flatten(export))
        self.assertTrue(any("缺少 token" in problem for problem in problems))

    def test_type_change_is_structure(self) -> None:
        """类型变更判结构。"""
        export = json.loads(json.dumps(_LIGHT_FIXTURE))
        export["space"]["16"]["$type"] = "number"
        _, problems = rt.compare(rt.flatten(_LIGHT_FIXTURE), rt.flatten(export))
        self.assertTrue(any("类型变更" in problem for problem in problems))

    def test_description_change_is_structure(self) -> None:
        """描述变更判结构（它是给人和文档看的，不属于「值」）。"""
        export = json.loads(json.dumps(_LIGHT_FIXTURE))
        export["color"]["brand"]["default"]["$description"] = "改过的说明"
        _, problems = rt.compare(rt.flatten(_LIGHT_FIXTURE), rt.flatten(export))
        self.assertTrue(any("描述变更" in problem for problem in problems))

    def test_dropped_description_is_not_structure(self) -> None:
        """导出物整段丢掉 description 不算仓库有错（那是导出物不完整）。"""
        export = json.loads(json.dumps(_LIGHT_FIXTURE))
        del export["color"]["brand"]["default"]["$description"]
        _, problems = rt.compare(rt.flatten(_LIGHT_FIXTURE), rt.flatten(export))
        self.assertEqual(problems, [])


class TestApply(RoundtripFixture):
    """钉住落盘行为：只改值、不制造格式噪声、结构漂移一律拒绝。"""

    def test_apply_writes_only_the_value(self) -> None:
        """落盘后除被改的值外，全文逐字节不变（含 CRLF 换行符）。"""
        before = self.source_text()
        doc = {
            "light": {
                "color": {
                    "surface": {"page": {"$value": "{color.paper.5}", "$type": "color"}},
                    "brand": {
                        "default": {"$value": "{color.overlay.scrim}", "$type": "color", "$description": "品牌锚点"},
                        "on": {"$value": "#FFFFFF", "$type": "color"},
                    },
                    "overlay": {"scrim": {"$value": "rgba(28,23,20,0.92)", "$type": "color"}},
                },
                "font": {
                    "family": {"display": {"$value": ["Fraunces"], "$type": "fontFamily"}},
                    "size": {"body": {"$value": "15px", "$type": "dimension"}},
                    "weight": {"body": {"$value": 400, "$type": "fontWeight"}},
                },
                "space": {"16": {"$value": "16px", "$type": "dimension"}},
                "motion": {"reducedDurationMs": {"$value": 120, "$type": "duration"}},
            }
        }
        with _quiet():
            status = rt.report_set("light", doc, apply=True)
        self.assertEqual(status, 0)
        after = self.source_text()
        self.assertIn("{color.overlay.scrim}", after)
        self.assertIn("\r\n", after, "落盘后换行符被改成 LF 了")
        self.assertEqual(
            before.replace("{color.ember.600}", "{color.overlay.scrim}"),
            after,
            "落盘除目标值外还动了别的东西",
        )

    def test_structure_drift_blocks_apply(self) -> None:
        """结构漂移时即使 --apply 也不许写文件。"""
        before = self.source_text()
        doc = {
            "light": {
                "color": {
                    "surface": {"page": {"$value": "{color.paper.5}", "$type": "color"}},
                    "brand": {"on": {"$value": "#FFFFFF", "$type": "color"}},
                }
            }
        }
        with _quiet():
            status = rt.report_set("light", doc, apply=True)
        self.assertEqual(status, 1)
        self.assertEqual(before, self.source_text(), "结构漂移时文件被改动了")

    def test_missing_set_returns_2(self) -> None:
        """导出物里没有该 set 时返回 2（输入问题，不是漂移）。"""
        with _quiet():
            self.assertEqual(rt.report_set("light", {"color": {}}, apply=False), 2)


class TestDanglingAlias(RoundtripFixture):
    """钉住「值变成解析不了的引用」这条 2026-11-28 真实导出撞到的坑。

    样本来自第一次真实往返:Tokens Studio 在「set 根就是 `color` 分组」的项目里，
    把引用写成 set 内相对路径 ``{ember.100}``，而仓库要求全路径 ``{color.ember.100}``。
    这种值进仓库后生成器会 fail-closed（`别名指向不存在的 token`），但如果校验器
    把它当普通值变更放过，`--apply` 之后本地才会炸 —— 那时人已经以为「只改了个值」。
    """

    def test_alias_target_parsing(self) -> None:
        """只认整值别名，字符串里嵌花括号不算。"""
        self.assertEqual(rt.alias_target("{color.ember.100}"), "color.ember.100")
        self.assertIsNone(rt.alias_target("#FFFFFF"))
        self.assertIsNone(rt.alias_target("0 2px 8px rgba(28,23,20,0.06)"))
        self.assertIsNone(rt.alias_target(400))

    def test_dangling_alias_blocks_apply(self) -> None:
        """截断成相对路径的引用必须判悬空、拒绝落盘，并提示完整写法。"""
        before = self.source_text()
        doc = json.loads(json.dumps(_LIGHT_FIXTURE))
        doc["color"]["brand"]["default"]["$value"] = "{ember.100}"
        buffer, ctx = _capture()
        with ctx:
            status = rt.report_set("light", doc, apply=True)
        self.assertEqual(status, 1)
        self.assertEqual(before, self.source_text(), "悬空引用时文件被改动了")
        self.assertIn("悬空引用", buffer.getvalue())

    def test_resolvable_alias_is_allowed(self) -> None:
        """换成仓库里确实存在的引用就该放行（含 --apply）。"""
        doc = json.loads(json.dumps(_LIGHT_FIXTURE))
        doc["color"]["brand"]["default"]["$value"] = "{color.overlay.scrim}"
        with _quiet():
            status = rt.report_set("light", doc, apply=True)
        self.assertEqual(status, 0)
        self.assertIn("{color.overlay.scrim}", self.source_text())

    def test_dangling_detection_ignores_unchanged_values(self) -> None:
        """仓库里本来就有的值不参与悬空判定（否则 untouched 的旧值会被误报）。"""
        changes = [
            {"path": "color.brand.default", "old": "#FFF", "new": "#000", "display_old": "", "display_new": ""}
        ]
        self.assertEqual(rt.dangling_aliases(changes, "light"), [])


class TestRealRepoNamespace(unittest.TestCase):
    """用**真仓库**的命名空间钉住「截断引用」的提示能力（不 monkeypatch TOKENS_DIR）。"""

    def test_suggest_alias_on_real_repo(self) -> None:
        """``{ember.100}`` 应被提示成 ``{color.ember.100}``。

        备注信息:
            样本正是 2026-11-28 第一次真实导出:``primitive.color.json`` 里
            ``color.ember.300`` 被写成 ``{ember.100}``，缺了 ``color.`` 前缀。
            这个用例必须跑在真仓库上 —— 提示能力依赖真实的跨 set 命名空间，
            放临时样本里测不到（临时目录只有 light/dark 两份文件）。
        """
        namespace = rt.namespace_paths()
        self.assertIn("color.ember.100", namespace)
        self.assertNotIn("ember.100", namespace)
        self.assertEqual(rt.suggest_alias("ember.100", "primitive"), "color.ember.100")
        self.assertIsNone(rt.suggest_alias("no.such.token", "primitive"))


class TestImportable(unittest.TestCase):
    """钉住 set → 文件名的映射与 CLI 的错误码口径。"""

    def test_set_files_cover_sources(self) -> None:
        """映射表覆盖 design/tokens 下除 generated 之外的全部源文件。"""
        for filename in rt.SET_FILES.values():
            self.assertTrue((rt.TOKENS_DIR / filename).exists(), f"映射到了不存在的文件:{filename}")

    def test_cli_missing_file_is_exit_2(self) -> None:
        """文件不存在按退出码 2 处理（输入问题，不是结构漂移）。"""
        buffer, ctx = _capture()
        with ctx:
            status = rt.main(["--export", str(Path(tempfile.gettempdir()) / "no-such-figma-export.json")])
        self.assertEqual(status, 2)
        self.assertIn("文件不存在", buffer.getvalue())

    def test_cli_unknown_set_is_exit_2(self) -> None:
        """导出物里没有可识别 set 且未指定 --set 时返回 2。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.json"
            path.write_text(json.dumps({"foo": {"bar": {"$value": 1, "$type": "number"}}}), encoding="utf-8")
            with _quiet():
                self.assertEqual(rt.main(["--export", str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
