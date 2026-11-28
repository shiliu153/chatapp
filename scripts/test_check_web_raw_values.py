"""``scripts/check_web_raw_values.py``(Web 裸值门禁的配置守卫)的自测。

为什么要有它
------------
Web 侧的判定器是 stylelint 配置,**配置坏了不会自己喊**。两个方向都不能静默:

- **漏报**:删掉一条规则、把 ``ignoreFiles`` 加宽成 ``src/**``、去掉 ``.vue`` 的
  ``customSyntax``、拿掉 npm 脚本里的 ``--report-needless-disables`` —— 四种做法都让
  门禁**静默变绿**(这正是守卫存在的理由);
- **误报**:把「加严」当成违规(多一条规则、单位列表更长、多一个属性正则),
  人只能把守卫关掉,门禁也就没了。

另外三件事也钉住:白名单纪律(整文件开关 / 未点名规则 / 没写原因 / 没写到期)、
「目录写错不许零文件全绿」、以及**守卫自己读不出来时必须退出码 2**(不许伪装成绿)。

全部用例用临时目录造样本,不依赖真实 ``web/`` 的内容(唯一例外是
``test_repository_baseline_is_clean``:它证明配置、白名单与门禁注册现在都对得上)。

用法:
    python -m unittest scripts.test_check_web_raw_values -v
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import check_web_raw_values as gate

#: 合规的 ``.stylelintrc.json`` 样本(与仓库里那份同形)。
VALID_CONFIG = {
    "ignoreFiles": [gate.GENERATED_RELATIVE],
    "overrides": [{"files": ["**/*.vue"], "customSyntax": gate.EXPECTED_VUE_SYNTAX}],
    "rules": {
        "color-no-hex": True,
        "color-no-invalid-hex": True,
        "function-disallowed-list": ["rgb", "rgba", "hsl", "hsla"],
        gate.UNIT_RULE: {
            "/^(padding|margin)(-(top|right|bottom|left|block|inline)(-(start|end))?)?$/": list(
                gate.DISALLOWED_UNITS
            ),
            "/^(row-|column-)?gap$/": list(gate.DISALLOWED_UNITS),
            "/^border(-(top|right|bottom|left)(-(start|end))?)?-radius$/": list(
                gate.DISALLOWED_UNITS
            ),
            "/^font(-size)?$/": list(gate.DISALLOWED_UNITS),
        },
    },
}

#: 合规的 ``package.json`` 样本。
VALID_PACKAGE = {
    "name": "chatapp-web",
    "scripts": {
        gate.STYLE_SCRIPT: (
            f'stylelint "{gate.STYLE_GLOB}" ' + " ".join(gate.REQUIRED_FLAGS)
        ),
    },
    "devDependencies": {"stylelint": "^18.1.0", "postcss-html": "^2.0.1"},
}

#: 一条写对的白名单注释(逐处 + 点名规则 + 原因 + 到期)。
VALID_WHITELIST = (
    "  /* stylelint-disable-next-line "
    f"{gate.UNIT_RULE} -- 2px 无对应档位(space 从 4 起);到期:E-5 迁移该页时清掉 */\n"
)

#: 一份最小的合法注册表(三条门禁都在)。
VALID_REGISTRY = """\
[[gate]]
id = "contract-web-raw-values-check"
scope = "contract"
kind = "python"
command = "python scripts/check_web_raw_values.py --check"
reason = "配置守卫"

[[gate]]
id = "contract-web-raw-values-selftest"
scope = "contract"
kind = "python"
command = "python -m unittest scripts.test_check_web_raw_values -v"
reason = "配置守卫的自测"

[[gate]]
id = "web-raw-values"
scope = "web"
kind = "shell"
command = "npm run lint:styles"
reason = "判据本体"
"""


class GateTestCase(unittest.TestCase):
    """一个用例一个临时 ``web/`` 骨架(样式文件数量刚好过下限)。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src" / "styles").mkdir(parents=True)
        self.write_config()
        self.write_package()
        self.write_file("src/styles/tokens.generated.css", ":root {\n  --x: #B4610C;\n}\n")
        for index in range(gate.MIN_SOURCE_FILES):
            self.write_file(f"src/features/Fixture{index}.vue", self.vue())
        self.registry = self.root / "gates.toml"
        self.registry.write_text(VALID_REGISTRY, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- 造样本 ----------------------------------------------------------

    def vue(self, style: str = ".a {\n  gap: var(--space-4);\n}\n") -> str:
        """把一段样式包成 ``.vue`` 的 ``<style>`` 块。

        参数说明:
            style: ``<style>`` 块里的样式文本。

        返回参数:
            完整的 ``.vue`` 文件内容。

        使用示例:
            ``self.vue(".a { gap: var(--space-4); }")``

        备注信息:
            默认带一条派生写法 —— 合规样本不该有任何问题。
        """
        return f"<template>\n  <div class=\"a\" />\n</template>\n\n<style scoped>\n{style}</style>\n"

    def write_file(self, relative: str, text: str) -> Path:
        """在临时 ``web/`` 下写一个文件。

        参数说明:
            relative: 相对 ``web/`` 的路径。
            text: 文件内容。

        返回参数:
            写入的路径。

        使用示例:
            ``self.write_file("src/features/x.vue", self.vue())``

        备注信息:
            父目录自动创建;内容按 UTF-8 写。
        """
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_config(self, config: dict | None = None) -> None:
        """改写临时 ``.stylelintrc.json``。

        参数说明:
            config: 新的配置;``None`` 表示写回合规样本。

        返回参数:
            无返回值。

        使用示例:
            ``self.write_config({**VALID_CONFIG, "ignoreFiles": ["src/**"]})``

        备注信息:
            传 ``None`` 之外的对象时不再深拷贝,调用方负责给出完整配置。
        """
        payload = VALID_CONFIG if config is None else config
        self.write_file(gate.CONFIG_RELATIVE.as_posix(), json.dumps(payload, ensure_ascii=False))

    def write_package(self, package: dict | None = None) -> None:
        """改写临时 ``package.json``。

        参数说明:
            package: 新的清单;``None`` 表示写回合规样本。

        返回参数:
            无返回值。

        使用示例:
            ``self.write_package({**VALID_PACKAGE, "devDependencies": {}})``

        备注信息:
            只影响 ``check_package`` 用的那几项。
        """
        payload = VALID_PACKAGE if package is None else package
        self.write_file(gate.PACKAGE_RELATIVE.as_posix(), json.dumps(payload, ensure_ascii=False))

    def whitelist(self, comment: str, declaration: str = "  gap: 2px;\n") -> None:
        """在第一个样式文件里放一条白名单注释。

        参数说明:
            comment: 被检查的 stylelint 注释(整行,不含缩进也可以)。
            declaration: 紧跟其后的声明。

        返回参数:
            无返回值。

        使用示例:
            ``self.whitelist("/* stylelint-disable-next-line x -- y;到期:z */")``

        备注信息:
            覆盖 ``src/features/Fixture0.vue``,其余样本文件保持干净。
        """
        self.write_file(
            "src/features/Fixture0.vue", self.vue(f".a {{\n{comment}\n{declaration}}}\n")
        )

    # -- 断言 ------------------------------------------------------------

    def report(self):
        """检查临时样本(不查注册表)。

        返回参数:
            :class:`scripts.check_web_raw_values.Report`。

        使用示例:
            ``self.report().problems``

        备注信息:
            注册表由 ``check_gates`` 自己的用例单独覆盖。
        """
        return gate.inspect(self.root, None)

    def messages(self) -> str:
        """把全部问题拼成一段文本,便于 ``assertIn`` 断言。

        返回参数:
            换行拼接的问题文本(空 = 无问题)。

        使用示例:
            ``self.assertIn("缺规则", self.messages())``

        备注信息:
            只用于断言,不打印。
        """
        return "\n".join(problem.render() for problem in self.report().problems)

    def run_check(self, registry: Path | None = None) -> tuple[int, str]:
        """跑一次 ``check()`` 并捕获输出。

        参数说明:
            registry: 注册表路径;缺省用本用例的临时注册表。

        返回参数:
            二元组 ``(退出码, stdout)``。

        使用示例:
            ``self.run_check()[0]``

        备注信息:
            ``stderr`` 一起并进返回值,方便断言「工具自己出错」的原因。
        """
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            code = gate.check(self.root, registry or self.registry)
        return code, stream.getvalue()


class BaselineTests(GateTestCase):
    """合规样本必须判绿 —— 否则「误报」那一半就是坏的。"""

    def test_clean_tree_has_no_problem(self) -> None:
        self.assertEqual(self.report().problems, [])

    def test_clean_tree_passes_check(self) -> None:
        code, output = self.run_check()
        self.assertEqual(code, gate.EXIT_OK, output)
        self.assertIn("合规", output)

    def test_repository_baseline_is_clean(self) -> None:
        """真实仓库的配置、白名单、门禁注册现在都对得上。"""
        report = gate.inspect(gate.DEFAULT_WEB_ROOT)
        self.assertEqual(report.problems, [])
        self.assertEqual(report.gate_problems, [])
        self.assertGreaterEqual(report.source_files, gate.MIN_SOURCE_FILES)


class RuleTests(GateTestCase):
    """``rules`` 只许更严:缺一条、关掉一条、削减单位都判红。"""

    def rules(self) -> dict:
        """取合规样本的 ``rules`` 深拷贝。

        返回参数:
            可直接改写再传回 :meth:`write_config` 的 ``rules`` 字典。

        使用示例:
            ``rules = self.rules(); del rules["color-no-hex"]``

        备注信息:
            用 ``json`` 往返做深拷贝,免得用例之间互相污染。
        """
        return json.loads(json.dumps(VALID_CONFIG["rules"]))

    def test_missing_rule_is_reported(self) -> None:
        rules = self.rules()
        del rules["color-no-hex"]
        self.write_config({**VALID_CONFIG, "rules": rules})
        self.assertIn("缺规则 color-no-hex", self.messages())

    def test_disabled_boolean_rule_is_reported(self) -> None:
        rules = self.rules()
        rules["color-no-hex"] = False
        self.write_config({**VALID_CONFIG, "rules": rules})
        self.assertIn("被关掉了", self.messages())

    def test_shrunk_unit_list_is_reported(self) -> None:
        rules = self.rules()
        rules[gate.UNIT_RULE]["/^(row-|column-)?gap$/"] = ["px"]
        self.write_config({**VALID_CONFIG, "rules": rules})
        self.assertIn("少了单位 rem", self.messages())

    def test_missing_property_pattern_is_reported(self) -> None:
        rules = self.rules()
        del rules[gate.UNIT_RULE]["/^font(-size)?$/"]
        self.write_config({**VALID_CONFIG, "rules": rules})
        self.assertIn("少了属性 /^font(-size)?$/", self.messages())

    def test_shrunk_function_list_is_reported(self) -> None:
        rules = self.rules()
        rules["function-disallowed-list"] = ["rgb"]
        self.write_config({**VALID_CONFIG, "rules": rules})
        self.assertIn("少了 rgba", self.messages())

    def test_missing_rules_section_is_reported(self) -> None:
        self.write_config({"ignoreFiles": [gate.GENERATED_RELATIVE]})
        self.assertIn("没有 rules 段", self.messages())

    def test_stricter_config_is_accepted(self) -> None:
        """多一条规则、单位更长、多一个属性正则都不算违规(误报方向)。"""
        rules = self.rules()
        rules["unit-disallowed-list"] = ["px"]
        rules["function-disallowed-list"] = ["rgb", "rgba", "hsl", "hsla", "oklch"]
        rules[gate.UNIT_RULE]["/^inset$/"] = ["px"]
        rules[gate.UNIT_RULE]["/^(row-|column-)?gap$/"] = list(gate.DISALLOWED_UNITS) + ["ch"]
        self.write_config({**VALID_CONFIG, "rules": rules})
        self.assertEqual(self.report().problems, [])


class IgnoreTests(GateTestCase):
    """``ignoreFiles`` 必须恰好只放走生成物,且那条路径真实存在。"""

    def test_missing_generated_file_is_reported(self) -> None:
        self.write_config({**VALID_CONFIG, "ignoreFiles": []})
        self.assertIn("ignoreFiles 少了", self.messages())

    def test_widened_ignore_is_reported(self) -> None:
        self.write_config({**VALID_CONFIG, "ignoreFiles": ["src/**"]})
        self.assertIn("只允许排除生成物", self.messages())

    def test_widened_ignore_also_keeps_the_generated_entry(self) -> None:
        config = {**VALID_CONFIG, "ignoreFiles": [gate.GENERATED_RELATIVE, "src/features/**"]}
        self.write_config(config)
        self.assertIn("src/features/**", self.messages())

    def test_nonexistent_ignore_path_is_reported(self) -> None:
        config = {**VALID_CONFIG, "ignoreFiles": [gate.GENERATED_RELATIVE, "src/styles/typo.css"]}
        self.write_config(config)
        self.assertIn("空豁免", self.messages())


class OverrideTests(GateTestCase):
    """``.vue`` 的解析器不能没:少了它,78 个页面的样式根本没人判。"""

    def test_missing_overrides_is_reported(self) -> None:
        self.write_config({k: v for k, v in VALID_CONFIG.items() if k != "overrides"})
        self.assertIn("没有 overrides 段", self.messages())

    def test_wrong_vue_syntax_is_reported(self) -> None:
        config = {
            **VALID_CONFIG,
            "overrides": [{"files": ["**/*.vue"], "customSyntax": "postcss-scss"}],
        }
        self.write_config(config)
        self.assertIn("customSyntax 不是", self.messages())


class PackageTests(GateTestCase):
    """npm 脚本与依赖是判据的执行者,缺一条就不判了。"""

    def package_with_script(self, script: str) -> dict:
        """拼一份只改脚本的清单。

        参数说明:
            script: ``scripts["lint:styles"]`` 的新值。

        返回参数:
            可直接传给 :meth:`write_package` 的字典。

        使用示例:
            ``self.package_with_script("stylelint \"src/**/*.vue\"")``

        备注信息:
            其余字段沿用合规样本。
        """
        return {**VALID_PACKAGE, "scripts": {gate.STYLE_SCRIPT: script}}

    def test_missing_style_script_is_reported(self) -> None:
        self.write_package({**VALID_PACKAGE, "scripts": {}})
        self.assertIn(f"没有 scripts.{gate.STYLE_SCRIPT}", self.messages())

    def test_missing_needless_flag_is_reported(self) -> None:
        script = f'stylelint "{gate.STYLE_GLOB}" --max-warnings 0 --report-descriptionless-disables'
        self.write_package(self.package_with_script(script))
        self.assertIn("--report-needless-disables", self.messages())

    def test_missing_max_warnings_is_reported(self) -> None:
        script = f'stylelint "{gate.STYLE_GLOB}" ' + " ".join(gate.REQUIRED_FLAGS[1:])
        self.write_package(self.package_with_script(script))
        self.assertIn("--max-warnings 0", self.messages())

    def test_wrong_glob_is_reported(self) -> None:
        script = f'stylelint "src/**/*.ts" ' + " ".join(gate.REQUIRED_FLAGS)
        self.write_package(self.package_with_script(script))
        self.assertIn("扫描面不是", self.messages())

    def test_missing_stylelint_command_is_reported(self) -> None:
        script = "eslint . " + " ".join(gate.REQUIRED_FLAGS)
        self.write_package(self.package_with_script(script))
        self.assertIn("没有跑 stylelint", self.messages())

    def test_missing_dev_dependency_is_reported(self) -> None:
        self.write_package({**VALID_PACKAGE, "devDependencies": {"stylelint": "^18.1.0"}})
        self.assertIn("devDependencies 少了 postcss-html", self.messages())


class WhitelistTests(GateTestCase):
    """白名单:逐处 + 点名规则 + 原因 + 到期,一条都不能省。"""

    def test_valid_entry_is_accepted(self) -> None:
        self.whitelist(VALID_WHITELIST.strip())
        report = self.report()
        self.assertEqual(report.problems, [])
        self.assertEqual(len(report.entries), 1)
        self.assertEqual(report.entries[0].rules, (gate.UNIT_RULE,))

    def test_file_wide_disable_is_reported(self) -> None:
        self.whitelist(f"/* stylelint-disable {gate.UNIT_RULE} -- 整文件关掉;到期:永不 */")
        self.assertIn("整文件开关", self.messages())

    def test_enable_comment_is_reported(self) -> None:
        self.whitelist(f"/* stylelint-enable {gate.UNIT_RULE} */")
        self.assertIn("整文件开关", self.messages())

    def test_entry_without_rule_names_is_reported(self) -> None:
        self.whitelist("/* stylelint-disable-next-line -- 没说哪条规则;到期:无 */")
        self.assertIn("没有点名规则", self.messages())

    def test_unknown_rule_name_is_reported(self) -> None:
        self.whitelist("/* stylelint-disable-next-line color-no-shouting -- 敲错;到期:无 */")
        self.assertIn("不在配置里", self.messages())

    def test_entry_without_description_is_reported(self) -> None:
        self.whitelist(f"/* stylelint-disable-next-line {gate.UNIT_RULE} */")
        self.assertIn("没有写原因", self.messages())

    def test_entry_without_expiry_is_reported(self) -> None:
        self.whitelist(f"/* stylelint-disable-next-line {gate.UNIT_RULE} -- 就是懒得改 */")
        self.assertIn("没有写到期", self.messages())

    def test_disable_line_form_is_accepted(self) -> None:
        """同行放行(``disable-line``)也是逐处,不误判成整文件开关。"""
        self.write_file(
            "src/features/Fixture0.vue",
            self.vue(
                f".a {{\n  gap: 2px; /* stylelint-disable-line {gate.UNIT_RULE} -- "
                "2px 无档位;到期:E-5 清掉 */\n}\n"
            ),
        )
        self.assertEqual(self.report().problems, [])


class ScanSurfaceTests(GateTestCase):
    """目录写错不许「零文件全部合规」。"""

    def test_too_few_files_is_reported(self) -> None:
        for path in (self.root / "src" / "features").glob("Fixture*.vue"):
            path.unlink()
        self.assertIn("只扫到", self.messages())

    def test_missing_config_is_tooling_error(self) -> None:
        (self.root / gate.CONFIG_RELATIVE).unlink()
        code, output = self.run_check()
        self.assertEqual(code, gate.EXIT_TOOLING, output)

    def test_broken_package_json_is_tooling_error(self) -> None:
        self.write_file(gate.PACKAGE_RELATIVE.as_posix(), "{ not json")
        code, output = self.run_check()
        self.assertEqual(code, gate.EXIT_TOOLING, output)


class GateRegistrationTests(GateTestCase):
    """门禁注册也要在:守卫自己没人跑,就白写了。"""

    def test_missing_gate_is_reported(self) -> None:
        self.registry.write_text(
            VALID_REGISTRY.replace('id = "web-raw-values"', 'id = "web-other"'), encoding="utf-8"
        )
        report = gate.inspect(self.root, self.registry)
        self.assertEqual(report.problems, [])
        self.assertIn("没注册", "\n".join(item.message for item in report.gate_problems))

    def test_wrong_scope_is_reported(self) -> None:
        self.registry.write_text(
            VALID_REGISTRY.replace('scope = "web"', 'scope = "app"'), encoding="utf-8"
        )
        report = gate.inspect(self.root, self.registry)
        self.assertIn("scope 不是 web", "\n".join(item.message for item in report.gate_problems))

    def test_wrong_command_is_reported(self) -> None:
        self.registry.write_text(
            VALID_REGISTRY.replace("npm run lint:styles", "npm run lint"),
            encoding="utf-8",
        )
        report = gate.inspect(self.root, self.registry)
        self.assertIn(
            "命令不含 npm run lint:styles",
            "\n".join(item.message for item in report.gate_problems),
        )

    def test_broken_registry_is_tooling_error(self) -> None:
        self.registry.write_text("[gate]\nid = 1\n", encoding="utf-8")
        code, output = self.run_check()
        self.assertEqual(code, gate.EXIT_TOOLING, output)


if __name__ == "__main__":
    unittest.main()
