#!/usr/bin/env python3
"""Web 侧「裸值」门禁的配置守卫:stylelint 判据 + 白名单纪律。

为什么需要它
------------
「余烬 Ember」把视觉取值全部收进 ``design/tokens/*.json``,Web 侧只许消费生成物
``web/src/styles/tokens.generated.css``(CSS 变量)。这条纪律在 Web 侧的判定器是
**stylelint**(配置 ``web/.stylelintrc.json``,命令 ``npm run lint:styles``,门禁
``web-raw-values``)—— 与 App 侧 ``scripts/check_app_raw_values.py`` 同构,判据口径
逐个对齐(见下表)。

但 stylelint 的配置**不会自己喊**:删掉 ``color-no-hex``、把 ``ignoreFiles`` 加宽成
``src/**``、去掉 ``.vue`` 的 ``customSyntax``、把 npm 脚本里的 ``--report-needless-disables``
拿掉 —— 四种做法都会让门禁**静默变绿**,而不是变红。这个脚本就是防这四种:

1. ``web/.stylelintrc.json`` 的 ``rules`` 必须**至少**还是那份判据(缺一条、把单位列表
   削减、把布尔规则关掉 → 红;加更严的规则不算违规);
2. ``ignoreFiles`` 必须**恰好**是生成物那一条(加宽 = 放走整片页面,漏写 = 一上来就红成
   几千条;两者都判),且每个被忽略的路径必须真实存在(写错路径的「空豁免」判红);
3. ``.vue`` 的 ``customSyntax`` 必须是 ``postcss-html`` —— 少了它,``<style>`` 块根本
   解析不了,门禁对着 78 个页面一声不响;
4. ``package.json`` 里 ``lint:styles`` 与两个 devDependency 必须还在(``--max-warnings 0``
   与三条 ``--report-*`` 旗标逐个点名,它们是白名单纪律的执行者,见下)。

白名单纪律(存量债务)
--------------------
存量裸值**逐处**放行,写成 ``/* stylelint-disable-next-line <规则> -- 原因;到期:… */``
行内注释 —— 不是整条规则豁免,也不是整文件开关。本脚本机械要求:

- 只准 ``stylelint-disable-next-line`` / ``stylelint-disable-line``(逐处);
  ``stylelint-disable`` / ``stylelint-enable``(整文件开关)一律判红;
- 必须点名规则,且规则名必须真的在配置里(敲错的名字 = 一张空头豁免);
- 必须 ``--`` 之后写原因,且原因里带「到期:」(谁来清、清成什么,与 App 侧
  ``WhitelistEntry.expiry`` 同口径)。

「存量已清掉却没删」这一半不在这里判:CSS 里没有可执行语法告诉你注释是多余的,
这件事由 ``--report-needless-disables`` 在 ``web-raw-values`` 里判(对应 App 侧
「白名单条目在文件里找不到片段即判红」)。所以本脚本是**补充**,不是替代。

判据口径(App ↔ Web,均来自规范 §11.2 的「裸值」一行)
-----------------------------------------------------
======================  =================================  ================================
类别                    App(``check_app_raw_values.py``)   Web(``.stylelintrc.json``)
======================  =================================  ================================
裸 hex                  ``0x`` + 6/8 位十六进制             ``color-no-hex``
裸非法色值              ——                                 ``color-no-invalid-hex``
裸 ``rgb()``/``hsl()``  ——                                 ``function-disallowed-list``
裸字号                  ``fontSize: 17``                   ``font-size`` / ``font`` 的单位
裸间距                  ``EdgeInsets.all(16)``             ``padding*`` / ``margin*`` / ``gap`` 的单位
裸圆角                  ``BorderRadius.circular(9)``       ``border-radius*`` 的单位
======================  =================================  ================================

**``0`` 不算裸值**(CSS 里 ``0`` 无单位,天然通过);**由 token 派生的表达式不算裸值**
(``var(--space-4)`` / ``calc(var(--space-4) / 2)`` / ``color-mix(… var(--x) …)`` /
百分比 / ``auto`` / ``inherit``)—— 与 App 侧「``tokens.space4 / 2`` 是比例不是设计值」
同一条口径。

门禁注册也必须还在:``scripts/gates.toml`` 里 ``web-raw-values``(web 组)、
``contract-web-raw-values-check`` / ``-selftest``(contract 组)三条缺一条即红 ——
否则这个守卫自己会变成没人跑的脚本。

输出与退出码
------------
- 一行一条问题,形如 ``web/.stylelintrc.json: 缺规则 color-no-hex``;
- ``--check``:有问题退出码 ``1``,全清 ``0``;
- 默认(不带 ``--check``):只打印统计,退出码 ``0``;
- ``2``:工具自己出错(文件缺失 / 读不了 / ``gates.toml`` 不合法)。**这类不许算绿**。

用法:
    python scripts/check_web_raw_values.py            # 打印统计
    python scripts/check_web_raw_values.py --check    # 判红(门禁 contract-web-raw-values-check)
    python scripts/check_web_raw_values.py --verbose  # 附带逐条白名单命中
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: 仓库根目录(本文件在 ``scripts/`` 下)。
ROOT = Path(__file__).resolve().parent.parent

# `python scripts/check_web_raw_values.py` 时 sys.path[0] 是 scripts/;显式把仓库根放进去,
# 这样 `from scripts import run_gates` 在「直接跑」与「unittest」两种调用方式下都成立。
sys.path.insert(0, str(ROOT))

from scripts import run_gates  # noqa: E402  (必须在 sys.path 修好之后)

#: 缺省被检查的网页端目录。自测用 ``--web-root`` 指向临时目录。
DEFAULT_WEB_ROOT = ROOT / "web"
#: stylelint 配置与 npm 清单在网页端目录下的相对路径。
CONFIG_RELATIVE = Path(".stylelintrc.json")
PACKAGE_RELATIVE = Path("package.json")
#: 被扫描的样式源码目录(白名单注释就在其中)。
SOURCE_RELATIVE = Path("src")
#: 门禁注册表(缺了它「门禁是不是还注册着」就没人守)。
REGISTRY_RELATIVE = Path("scripts") / "gates.toml"
#: 生成物相对 ``web/`` 的路径(stylelint 的 ``ignoreFiles`` 就按配置所在目录解析):
#: 它必须被整文件排除,否则门禁一跑就是几千条。
GENERATED_RELATIVE = "src/styles/tokens.generated.css"
#: npm 脚本名与被 lint 的 glob(两条都在 ``package.json`` 里点名核对)。
STYLE_SCRIPT = "lint:styles"
STYLE_GLOB = "src/**/*.{vue,css}"
#: 想删也删不掉的旗标:``--max-warnings 0`` 让 warning 变红,三条 ``--report-*``
#: 是白名单纪律(多余放行 / 无原因放行 / 敲错规则名)的执行者。
REQUIRED_FLAGS = (
    "--max-warnings 0",
    "--report-needless-disables",
    "--report-descriptionless-disables",
    "--report-invalid-scope-disables",
)
#: 判定器本体(缺了它们 ``lint:styles`` 跑不起来)。
REQUIRED_DEV_DEPS = ("stylelint", "postcss-html")
#: ``.vue`` 的 ``<style>`` 块必须有这个解析器,否则「解析不了就一声不响」。
EXPECTED_VUE_SYNTAX = "postcss-html"
#: 单位黑名单(间距 / 圆角 / 字号共用一套;百分比与无单位的 ``0`` 不在其中)。
DISALLOWED_UNITS = ["px", "rem", "em", "pt", "vh", "vw", "vmin", "vmax"]
#: 单位规则 id(白名单注释里会点名它)。
UNIT_RULE = "declaration-property-unit-disallowed-list"
#: **判据本体**:规则 id → 至少必须成立的选项(加更严的规则 / 更长的单位列表不算违规)。
EXPECTED_RULES: dict[str, object] = {
    "color-no-hex": True,
    "color-no-invalid-hex": True,
    "function-disallowed-list": ["rgb", "rgba", "hsl", "hsla"],
    UNIT_RULE: {
        "/^(padding|margin)(-(top|right|bottom|left|block|inline)(-(start|end))?)?$/": list(DISALLOWED_UNITS),
        "/^(row-|column-)?gap$/": list(DISALLOWED_UNITS),
        "/^border(-(top|right|bottom|left)(-(start|end))?)?-radius$/": list(DISALLOWED_UNITS),
        "/^font(-size)?$/": list(DISALLOWED_UNITS),
    },
}
#: 白名单里必须出现的到期标记(与 App 侧 ``WhitelistEntry.expiry`` 同口径)。
EXPIRY_MARKER = "到期"
#: 扫描面的下限:目录写错时不许「零文件全部合规」。
MIN_SOURCE_FILES = 30
#: 必须注册着的门禁:id → (scope, 命令里必须出现的片段)。
REQUIRED_GATES = {
    "web-raw-values": ("web", f"npm run {STYLE_SCRIPT}"),
    "contract-web-raw-values-check": ("contract", "check_web_raw_values.py --check"),
    "contract-web-raw-values-selftest": ("contract", "test_check_web_raw_values"),
}

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_TOOLING = 2

#: 一条 stylelint 指令注释(``stylelint-disable-next-line …`` / ``stylelint-enable`` …)。
_DIRECTIVE = re.compile(r"stylelint-(disable-next-line|disable-line|disable|enable)\b([^\n]*)")
#: 逐处放行:只有这两种形态算「白名单条目」。
_PER_OCCURRENCE = ("disable-next-line", "disable-line")


@dataclass(frozen=True)
class Problem:
    """一处配置或白名单问题。

    Attributes:
        where: 打印用的位置(仓库相对路径,或 ``<文件>:<行>``)。
        message: 一行结论,含「该怎么改」。
    """

    where: str
    message: str

    def render(self) -> str:
        """渲染成一行。

        返回参数:
            形如 ``web/.stylelintrc.json: 缺规则 color-no-hex`` 的文本。

        使用示例:
            ``print(problem.render())``

        备注信息:
            无参数。
        """
        return f"{self.where}: {self.message}"


@dataclass(frozen=True)
class WhitelistEntry:
    """一条逐处放行的白名单(行内注释)。

    Attributes:
        path: 相对 ``web/`` 的文件路径。
        line: 注释所在行号(1 起,只给人看)。
        kinds: ``disable-next-line`` / ``disable-line``。
        rules: 被点名的规则 id。
        description: ``--`` 之后的原因与到期说明。
    """

    path: str
    line: int
    kinds: tuple[str, ...]
    rules: tuple[str, ...]
    description: str


@dataclass
class Report:
    """一次检查的全部结果。

    Attributes:
        source_files: 实际扫描的样式文件数。
        entries: 扫到的白名单条目。
        problems: 配置与白名单的问题(空 = 合规)。
        gate_problems: 门禁注册缺失(单独列,便于一眼看出「门禁被删了」)。
    """

    source_files: int = 0
    entries: list[WhitelistEntry] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    gate_problems: list[Problem] = field(default_factory=list)


def _read_json(path: Path) -> dict:
    """读一个 JSON 文件。

    参数说明:
        path: 文件路径。

    返回参数:
        解析出的字典。

    使用示例:
        ``_read_json(web_root / CONFIG_RELATIVE)``

    备注信息:
        文件缺失、不是 JSON、顶层不是对象时抛 :class:`OSError` / :class:`ValueError`,
        由调用方翻成退出码 2。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层必须是对象")
    return data


def _as_list(value: object) -> list[object]:
    """把布尔/字符串/列表统一成列表。

    参数说明:
        value: 规则选项里的一项。

    返回参数:
        列表;``None`` 变成空列表。

    使用示例:
        ``_as_list(["rgb"])``

    备注信息:
        stylelint 允许把布尔规则写成 ``true`` 或 ``[true, {…}]``,这里统一掉。
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def check_rules(config: dict) -> list[Problem]:
    """核对 ``rules`` 至少还成立那份判据。

    参数说明:
        config: 解析后的 ``.stylelintrc.json``。

    返回参数:
        问题列表(空 = 判据完整)。

    使用示例:
        ``check_rules(_read_json(web_root / CONFIG_RELATIVE))``

    备注信息:
        「只许更严」:缺规则 / 关掉布尔规则 / 削减单位列表 / 砍掉某个属性正则 → 红;
        多一条规则、单位列表更长、多一个属性正则 → 不算违规(那是把门禁改得更紧)。
    """
    rules = config.get("rules")
    if not isinstance(rules, dict):
        return [Problem(CONFIG_RELATIVE.as_posix(), "没有 rules 段 —— 门禁等于没配")]

    problems: list[Problem] = []
    where = CONFIG_RELATIVE.as_posix()
    for rule_id, expected in EXPECTED_RULES.items():
        if rule_id not in rules:
            problems.append(Problem(where, f"缺规则 {rule_id}(Ember §11.2 的裸值判据之一)"))
            continue
        actual = rules[rule_id]
        if isinstance(expected, bool):
            if not any(bool(item) for item in _as_list(actual)):
                problems.append(Problem(where, f"规则 {rule_id} 被关掉了(当前值 {actual!r})"))
            continue
        if isinstance(expected, list):
            have = [item for item in _as_list(actual) if isinstance(item, str)]
            missing = [item for item in expected if item not in have]
            if missing:
                problems.append(
                    Problem(where, f"规则 {rule_id} 少了 {'、'.join(missing)}(算不算裸值就靠它)")
                )
            continue
        # 单位规则:属性正则 → 单位列表,逐条要求「至少还是这些」
        if not isinstance(actual, dict):
            problems.append(Problem(where, f"规则 {rule_id} 必须是 属性正则 → 单位列表 的表"))
            continue
        for property_pattern, units in expected.items():
            if property_pattern not in actual:
                problems.append(
                    Problem(where, f"规则 {rule_id} 少了属性 {property_pattern}(这一类裸值没人判)")
                )
                continue
            have = [item for item in _as_list(actual[property_pattern]) if isinstance(item, str)]
            missing = [unit for unit in units if unit not in have]
            if missing:
                problems.append(
                    Problem(
                        where,
                        f"规则 {rule_id} 的 {property_pattern} 少了单位 {'、'.join(missing)}",
                    )
                )
    return problems


def check_ignore(config: dict, web_root: Path) -> list[Problem]:
    """核对 ``ignoreFiles`` 恰好只放走生成物,且那条路径真实存在。

    参数说明:
        config: 解析后的 ``.stylelintrc.json``。
        web_root: 网页端目录(被忽略的路径相对它存在)。

    返回参数:
        问题列表(空 = 豁免面正确)。

    使用示例:
        ``check_ignore(_read_json(web_root / CONFIG_RELATIVE), web_root)``

    备注信息:
        两个方向都会坏:加宽(例如 ``src/**``)= 整片页面被放走;漏写 = 门禁对着成片
        hex 红几千条、人只能把门禁关掉。写错路径的「空豁免」同样判红 —— 否则下一个人
        会以为自己豁免了一条,其实什么都没豁免。
    """
    where = CONFIG_RELATIVE.as_posix()
    actual = config.get("ignoreFiles")
    entries = [str(item) for item in _as_list(actual)]
    problems: list[Problem] = []
    missing = [item for item in (GENERATED_RELATIVE,) if item not in entries]
    if missing:
        problems.append(
            Problem(where, f"ignoreFiles 少了 {'、'.join(missing)}(生成物必须整文件排除)")
        )
    extra = [item for item in entries if item not in (GENERATED_RELATIVE,)]
    for item in extra:
        problems.append(
            Problem(
                where,
                f"ignoreFiles 多出 {item}:只允许排除生成物 {GENERATED_RELATIVE},"
                "加宽豁免等于把门禁关掉",
            )
        )
    for item in entries:
        if not (web_root / item).is_file():
            problems.append(Problem(where, f"ignoreFiles 里的 {item} 不存在(空豁免,判红)"))
    return problems


def check_overrides(config: dict) -> list[Problem]:
    """核对 ``.vue`` 的 ``<style>`` 块有解析器。

    参数说明:
        config: 解析后的 ``.stylelintrc.json``。

    返回参数:
        问题列表(空 = 解析器还在)。

    使用示例:
        ``check_overrides(_read_json(web_root / CONFIG_RELATIVE))``

    备注信息:
        少了 ``customSyntax``,stylelint 读不了 78 个 ``.vue`` 页面,门禁对着整站样式
        一声不响 —— 这是最贵的一种「静默变绿」。
    """
    where = CONFIG_RELATIVE.as_posix()
    overrides = config.get("overrides")
    if not isinstance(overrides, list):
        return [Problem(where, "没有 overrides 段:.vue 的 <style> 块就没有解析器")]
    for item in overrides:
        if not isinstance(item, dict):
            continue
        files = [str(entry) for entry in _as_list(item.get("files"))]
        if not any(pattern.endswith("*.vue") for pattern in files):
            continue
        if item.get("customSyntax") == EXPECTED_VUE_SYNTAX:
            return []
        return [
            Problem(
                where,
                f"overrides 里 *.vue 的 customSyntax 不是 {EXPECTED_VUE_SYNTAX}"
                f"(当前 {item.get('customSyntax')!r})",
            )
        ]
    return [Problem(where, f"overrides 里没有 *.vue → customSyntax: {EXPECTED_VUE_SYNTAX}")]


def check_package(package: dict) -> list[Problem]:
    """核对 ``package.json`` 里的判据命令与依赖还在。

    参数说明:
        package: 解析后的 ``package.json``。

    返回参数:
        问题列表(空 = 命令与依赖完整)。

    使用示例:
        ``check_package(_read_json(web_root / PACKAGE_RELATIVE))``

    备注信息:
        旗标逐个点名而不是整串比对:重排旗标顺序不会红,少一个才会 ——
        少了 ``--report-needless-disables``,「存量清掉却没删白名单」就没人判了。
    """
    where = PACKAGE_RELATIVE.as_posix()
    problems: list[Problem] = []
    scripts = package.get("scripts")
    script = scripts.get(STYLE_SCRIPT) if isinstance(scripts, dict) else None
    if not isinstance(script, str):
        problems.append(Problem(where, f"没有 scripts.{STYLE_SCRIPT}(门禁命令没了)"))
    else:
        if "stylelint" not in script:
            problems.append(Problem(where, f"scripts.{STYLE_SCRIPT} 没有跑 stylelint"))
        if STYLE_GLOB not in script:
            problems.append(Problem(where, f"scripts.{STYLE_SCRIPT} 的扫描面不是 {STYLE_GLOB}"))
        for flag in REQUIRED_FLAGS:
            if flag not in script:
                problems.append(Problem(where, f"scripts.{STYLE_SCRIPT} 少了旗标 {flag}"))
    dev = package.get("devDependencies")
    dev = dev if isinstance(dev, dict) else {}
    for name in REQUIRED_DEV_DEPS:
        if name not in dev:
            problems.append(Problem(where, f"devDependencies 少了 {name}(判据跑不起来)"))
    return problems


def style_files(web_root: Path) -> list[Path]:
    """列出白名单扫描面里的样式文件。

    参数说明:
        web_root: 网页端目录。

    返回参数:
        排序后的 ``*.vue`` / ``*.css`` 路径列表。

    使用示例:
        ``style_files(DEFAULT_WEB_ROOT)``

    备注信息:
        按 POSIX 相对路径的字节序排序:输出顺序要跨平台稳定(Windows 大小写不敏感、
        Linux 敏感)。
    """
    root = web_root / SOURCE_RELATIVE
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix in (".vue", ".css")
    ]
    files.sort(key=lambda path: path.relative_to(root).as_posix().encode("utf-8"))
    return files


def scan_whitelist(web_root: Path, config: dict) -> tuple[list[WhitelistEntry], list[Problem]]:
    """扫样式源码里的白名单注释,核对「逐处 + 点名规则 + 原因 + 到期」。

    参数说明:
        web_root: 网页端目录。
        config: 解析后的 ``.stylelintrc.json``(用来核对点名的规则真的存在)。

    返回参数:
        二元组 ``(条目列表, 问题列表)``。

    使用示例:
        ``scan_whitelist(DEFAULT_WEB_ROOT, config)``

    备注信息:
        只做静态形态检查:「这处放行还有没有必要」要 stylelint 的
        ``--report-needless-disables`` 才判得出来(它需要 Node,所以住在 web 组)。
    """
    known = config.get("rules") if isinstance(config.get("rules"), dict) else {}
    entries: list[WhitelistEntry] = []
    problems: list[Problem] = []
    for path in style_files(web_root):
        relative = path.relative_to(web_root).as_posix()
        text = path.read_text(encoding="utf-8")
        for match in _DIRECTIVE.finditer(text):
            kind = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            where = f"{relative}:{line}"
            tail = match.group(2).split("*/", 1)[0]
            rules_part, _, description = tail.partition("--")
            rules = tuple(item for item in rules_part.split() if item)
            description = description.strip()
            entries.append(
                WhitelistEntry(
                    path=relative,
                    line=line,
                    kinds=(kind,),
                    rules=rules,
                    description=description,
                )
            )
            if kind not in _PER_OCCURRENCE:
                problems.append(
                    Problem(
                        where,
                        f"stylelint-{kind} 是整文件开关:白名单必须逐处"
                        "(stylelint-disable-next-line <规则> -- 原因;到期:…)",
                    )
                )
                continue
            if not rules:
                problems.append(Problem(where, "没有点名规则:整条规则的豁免等于把门禁关掉"))
            unknown = [rule for rule in rules if rule not in known]
            for rule in unknown:
                problems.append(
                    Problem(where, f"点名的规则 {rule} 不在配置里(敲错的规则名 = 空头豁免)")
                )
            if not description:
                problems.append(Problem(where, "没有写原因(-- 之后要写为什么这处不是设计值)"))
            elif EXPIRY_MARKER not in description:
                problems.append(
                    Problem(where, f"没有写{EXPIRY_MARKER}(谁来清、清成什么,与 App 侧同口径)")
                )
    return entries, problems


def check_gates(registry_path: Path) -> list[Problem]:
    """核对三条门禁还注册着。

    参数说明:
        registry_path: ``scripts/gates.toml`` 的路径。

    返回参数:
        问题列表(空 = 注册完整)。

    使用示例:
        ``check_gates(ROOT / REGISTRY_RELATIVE)``

    备注信息:
        注册表本身不合法时抛 ``run_gates.RegistryError``,由调用方翻成退出码 2 ——
        「判不出来」不许算绿。这个守卫自己要是没人跑,就白写了。
    """
    gates = run_gates.load_registry(registry_path)
    by_id = {gate.id: gate for gate in gates}
    where = REGISTRY_RELATIVE.as_posix()
    problems: list[Problem] = []
    for gate_id, (scope, fragment) in REQUIRED_GATES.items():
        gate = by_id.get(gate_id)
        if gate is None:
            problems.append(Problem(where, f"门禁 {gate_id} 没注册(判据就没人跑)"))
            continue
        if gate.scope != scope:
            problems.append(Problem(where, f"门禁 {gate_id} 的 scope 不是 {scope}"))
        if fragment not in gate.command:
            problems.append(Problem(where, f"门禁 {gate_id} 的命令不含 {fragment}"))
    return problems


def inspect(
    web_root: Path = DEFAULT_WEB_ROOT,
    registry_path: Path | None = ROOT / REGISTRY_RELATIVE,
) -> Report:
    """把配置、白名单、门禁注册三件事查一遍。

    参数说明:
        web_root: 网页端目录(自测传临时目录)。
        registry_path: 门禁注册表路径;``None`` 表示这次不查(自测临时目录里没有注册表)。

    返回参数:
        :class:`Report`。

    使用示例:
        ``inspect(DEFAULT_WEB_ROOT, ROOT / REGISTRY_RELATIVE)``

    备注信息:
        配置 / 清单缺失时抛 :class:`OSError` / :class:`ValueError`,
        由调用方翻成退出码 2:读不出来 ≠ 合规。
    """
    config = _read_json(web_root / CONFIG_RELATIVE)
    package = _read_json(web_root / PACKAGE_RELATIVE)
    report = Report()
    report.problems.extend(check_rules(config))
    report.problems.extend(check_ignore(config, web_root))
    report.problems.extend(check_overrides(config))
    report.problems.extend(check_package(package))
    report.source_files = len(style_files(web_root))
    if report.source_files < MIN_SOURCE_FILES:
        report.problems.append(
            Problem(
                SOURCE_RELATIVE.as_posix(),
                f"只扫到 {report.source_files} 个样式文件(少于 {MIN_SOURCE_FILES}):"
                "目录写错时不许「零文件全部合规」",
            )
        )
    entries, problems = scan_whitelist(web_root, config)
    report.entries.extend(entries)
    report.problems.extend(problems)
    if registry_path is not None:
        report.gate_problems.extend(check_gates(registry_path))
    return report


def check(
    web_root: Path = DEFAULT_WEB_ROOT,
    registry_path: Path | None = None,
    verbose: bool = False,
) -> int:
    """门禁入口:打印问题并以退出码表达。

    参数说明:
        web_root: 网页端目录。
        registry_path: 门禁注册表路径(缺省用仓库里那份;``None`` = 不查,自测用)。
        verbose: 是否附带逐条白名单命中。

    返回参数:
        ``0`` = 全清;``1`` = 有配置 / 白名单 / 注册问题;``2`` = 工具自己出错。

    使用示例:
        ``sys.exit(check(DEFAULT_WEB_ROOT))``

    备注信息:
        ``registry_path=None`` 只给自测用(临时目录里没有 ``scripts/gates.toml``);
        生产入口 :func:`main` 永远用仓库里那份。
    """
    try:
        report = inspect(web_root, registry_path or ROOT / REGISTRY_RELATIVE)
    except FileNotFoundError as error:
        print(f"错误:找不到 {error.filename}(Web 裸值门禁的配置没了)", file=sys.stderr)
        return EXIT_TOOLING
    except (OSError, ValueError, run_gates.RegistryError) as error:
        print(f"错误:{error}", file=sys.stderr)
        return EXIT_TOOLING

    problems = report.problems + report.gate_problems
    for problem in problems:
        print(problem.render())
    if verbose:
        _verbose(report)
    if problems:
        print(
            f"Web 裸值门禁配置:发现 {len(problems)} 处问题"
            f"(扫描 {report.source_files} 个样式文件、白名单 {len(report.entries)} 条)"
        )
        return EXIT_FINDINGS
    print(
        f"Web 裸值门禁配置:判据与白名单全部合规"
        f"(扫描 {report.source_files} 个样式文件,白名单放行 {len(report.entries)} 处存量)"
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 参数列表(缺省取 ``sys.argv[1:]``)。

    返回参数:
        进程退出码,含义见模块 docstring。

    使用示例:
        ``main(["--check"])``

    备注信息:
        ``--web-root`` 只给自测用(临时目录造样本);门禁命令里不带它。
    """
    parser = argparse.ArgumentParser(description="Web 侧裸值门禁的配置守卫")
    parser.add_argument("--check", action="store_true", help="判红:有问题即非 0")
    parser.add_argument(
        "--web-root", type=Path, default=DEFAULT_WEB_ROOT, help="网页端目录(自测用)"
    )
    parser.add_argument("--verbose", action="store_true", help="附带逐条白名单命中")
    args = parser.parse_args(argv)

    if not args.web_root.is_dir():
        print(f"错误:网页端目录不存在:{args.web_root}", file=sys.stderr)
        return EXIT_TOOLING

    if args.check:
        return check(args.web_root, verbose=args.verbose)

    try:
        report = inspect(args.web_root)
    except (OSError, ValueError, run_gates.RegistryError) as error:
        print(f"错误:{error}", file=sys.stderr)
        return EXIT_TOOLING
    print(
        f"Web 裸值门禁配置:扫描 {report.source_files} 个样式文件,"
        f"白名单 {len(report.entries)} 条,问题 {len(report.problems + report.gate_problems)} 处"
    )
    for problem in report.problems + report.gate_problems:
        print(problem.render())
    if args.verbose:
        _verbose(report)
    return EXIT_OK


def _verbose(report: Report) -> None:
    """打印逐条白名单命中(``--verbose``)。

    参数说明:
        report: 检查结果。

    返回参数:
        无返回值。

    使用示例:
        ``_verbose(report)``

    备注信息:
        走到 ``stderr``,不污染 ``--check`` 的机器可读输出。
    """
    for entry in report.entries:
        print(
            f"[白名单] {entry.path}:{entry.line} 规则 {'、'.join(entry.rules)}"
            f";{entry.description}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    sys.exit(main())
