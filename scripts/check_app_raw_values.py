#!/usr/bin/env python3
"""App 侧「裸值」机械门禁:裸 hex / 裸字号 / 裸间距 / 裸圆角。

为什么需要它
------------
「余烬 Ember」把视觉取值全部收进 ``design/tokens/*.json``,代码只许消费生成物
``app/lib/core/theme/tokens.g.dart``。这条纪律此前**只有人工 grep**:E-5.1~E-5.6 六单的验收
都在 PR 里贴一条手写 ``grep``,而 grep 只查得到 ``0xFF``,查不到 ``fontSize: 17``、
``EdgeInsets.all(16)``、``BorderRadius.circular(9)`` 这些**同样把设计值写死在页面里**的写法。
规范 §11.2 那张表里的「裸值」一行因此长期是空头 owner(校验入口只有人眼)。

判什么(口径全部来自规范 §11.2,本脚本不另立标准)
------------------------------------------------
1. **裸 hex**:``0x`` + 6 位以上十六进制字面量。色值 ``0xFFRRGGBB`` 是 8 位,
   省掉 alpha 的 ``0xRRGGBB`` 是 6 位,两者都是裸色值。
2. **裸字号**:``fontSize:`` 的值**以数字字面量开头**(``fontSize: 17`` /
   ``TextStyle(fontSize: 12)``)。顺带按字号下限加一句提示:< 11 违反「任意字号 ≥ 11」,
   < 13 违反「正文 ≥ 13」。
3. **裸间距**:``EdgeInsets.all / only / symmetric / fromLTRB / fromSTEB`` 的实参值以数字字面量
   开头(一处调用算一处,把同一调用里写死的几个值合并成一行)。
4. **裸圆角**:``BorderRadius.circular(<数字>)`` / ``Radius.circular(<数字>)``。

**``0`` 不算裸值**:token 源里没有 0 档,``0`` 表达的是「没有间距 / 没有圆角」
(``EdgeInsets.zero`` 那类语义),既不是设计值也没有可替换的 token —— 把它判红只会把
「聚焦外扩内边距为 0」这种刻意写法逼进白名单。字号里的 ``0`` 例外:那是真写死的取值
(``ember_field`` 用 ``fontSize: 0`` 压掉 Material 的默认错误行高),照样判。

**由 token 派生的表达式不算裸值**:``EdgeInsets.symmetric(horizontal: tokens.space4 / 2)``
里那个 ``2`` 是比例,不是设计值 —— 判据是「实参的值整段以数字字面量开头」,值里出现
``tokens.`` 或其他标识符就不再是裸值。

扫描面
------
``app/lib/**/*.dart``,排除生成物 ``app/lib/core/theme/tokens.g.dart``(token 生成器写出来的
成片 hex 常量,本来就是这个样子);``app/test/**`` 不在扫描面内(用例里写死尺寸是刻意的,
门禁只追「新代码」。

判之前先把**注释与字符串字面量抹成空格**(保留换行与偏移):文档注释里写 ``0xFF``、字符串里
写 ``'fontSize: 17'`` 都不是代码。字符串插值 ``${...}`` 里的代码同样被抹掉 —— 那是表达式,
不是视觉取值,漏扫可接受(记在这里,免得后来的人以为是 bug)。

白名单(存量债务,只增不减是不许发生的)
--------------------------------------
``WHITELIST`` 是**逐条**例外:文件 + 该处源码行片段 + 原因 + 到期说明。它**不是**整条规则的
豁免 —— 那等于把门禁关掉。

匹配按「文件 + 片段」而不是行号:任何一次上方增删都会让行号漂移,片段不会。条目里仍记了
当时的行号,``--verbose`` 会打印它与实际行号的偏差,便于定期收口。

**条目在文件里找不到对应片段即判红**:要么存量已经清掉(删掉条目),要么那行代码改过了
(重新核对)。这样白名单只会越用越短。

输出与退出码
------------
- 一行一条违规,形如 ``app/lib/features/x.dart:12: 裸字号 fontSize: 17:改用 tokens.fontSizeSubtitle``;
- ``--check``:有违规(或白名单失效)退出码 ``1``,全清退出码 ``0``;
- 默认(不带 ``--check``):只打印统计(文件数 / 逐规则条数 / 白名单条数),退出码 ``0``;
- ``2``:工具自己出错(找不到 token 生成物 / 目录不存在)。**这类不许算绿**。

用法:
    python scripts/check_app_raw_values.py            # 打印统计
    python scripts/check_app_raw_values.py --check    # 判红(门禁 app-raw-values 跑的就是这一条)
    python scripts/check_app_raw_values.py --verbose  # 附带逐条白名单命中与行号偏差
"""

from __future__ import annotations

import argparse
import bisect
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: 仓库根目录(本文件在 ``scripts/`` 下)。
ROOT = Path(__file__).resolve().parent.parent
#: 缺省扫描目录。自测用 ``--root`` 指向临时目录。
DEFAULT_ROOT = ROOT / "app" / "lib"
#: 生成物在扫描目录下的相对路径 —— 它必须被排除,否则规则一上来就红成一片。
GENERATED_RELATIVE = Path("core/theme/tokens.g.dart")
#: 字号下限(规范 §11.2「字号」一行):任意字号 ≥ 11,正文档 ≥ 13。
FONT_MIN_ANY = 11.0
FONT_MIN_BODY = 13.0

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_TOOLING = 2

# ---------------------------------------------------------------------------
# 词法:先把注释与字符串抹成空格,再判。正则跑在「只有代码」的文本上。
# ---------------------------------------------------------------------------

_STRING_START = re.compile(r"""[rR]?('''|\"\"\"|'|")""")


def mask_non_code(source: str) -> str:
    """把注释与字符串字面量替换成空格(保留换行与字符偏移)。

    参数说明:
        source: 一个 Dart 源文件的全文。

    返回参数:
        与 ``source`` **等长**的文本:代码原样保留,注释与字符串内容变成空格,换行保留
        (行号因此可以直接按偏移换算)。

    使用示例:
        ``mask_non_code("a(); // 0xFF\\nb();")``

    备注信息:
        只处理「让正则别把注释当代码」这一件事,不是完整的 Dart 词法分析器:插值
        ``${...}`` 里的表达式会连同外层字符串一起被抹掉(那里不写视觉取值),但插值内的
        **字符串字面量必须单独跳过** —— ``'${data['k'] ?? ''}'`` 这种写法在本仓库很常见,
        不跳过就会让外层字符串提前收尾,把后半段**代码**当成字符串抹掉:那是漏报方向,
        门禁最不该错的方向(详见 :func:`_skip_interpolation`)。正则字面量 ``/.../`` 不特殊
        处理(``app/lib`` 里没有出现;出现了会多判,不会漏判)。
    """
    out = list(source)
    index = 0
    length = len(source)

    def blank(start: int, stop: int) -> None:
        for position in range(start, min(stop, length)):
            if out[position] != "\n":
                out[position] = " "

    while index < length:
        char = source[index]
        following = source[index + 1] if index + 1 < length else ""
        if char == "/" and following == "/":
            stop = source.find("\n", index)
            stop = length if stop < 0 else stop
            blank(index, stop)
            index = stop
            continue
        if char == "/" and following == "*":
            # Dart 的块注释可以嵌套,深度计数必须留着,否则 /* /* */ */ 会提前收尾。
            depth = 1
            cursor = index + 2
            while cursor < length and depth:
                if source.startswith("/*", cursor):
                    depth += 1
                    cursor += 2
                elif source.startswith("*/", cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
            blank(index, cursor)
            index = cursor
            continue
        match = _STRING_START.match(source, index)
        if match:
            cursor = _skip_string(
                source,
                match.end(),
                match.group(1),
                match.group(0)[0] in "rR",
                length,
            )
            blank(index, cursor)
            index = cursor
            continue
        index += 1
    return "".join(out)


def _skip_string(source: str, start: int, quote: str, raw: bool, length: int) -> int:
    """返回字符串字面量结束处的下标。

    参数说明:
        source: 源文件全文。
        start: 开引号之后的下标。
        quote: 开引号:单引号 / 双引号 / 连续三个单引号 / 连续三个双引号(多行字符串)。
        raw: 是否原始字符串(``r'...'`` 里反斜杠不是转义)。
        length: 源文件长度。

    返回参数:
        闭引号之后的下标;字符串没闭合时返回 ``length``。

    使用示例:
        ``_skip_string(source, index + 1, "'", False, len(source))``

    备注信息:
        非原始字符串里的 ``${...}`` 交给 :func:`_skip_interpolation` 整段跳过 —— 插值里
        可以有字符串,字符串里又可以再有插值。
    """
    cursor = start
    while cursor < length:
        if not raw and source[cursor] == "\\":
            cursor += 2
            continue
        if source.startswith(quote, cursor):
            return cursor + len(quote)
        if not raw and source.startswith("${", cursor):
            cursor = _skip_interpolation(source, cursor + 2, length)
            continue
        cursor += 1
    return length


def _skip_interpolation(source: str, start: int, length: int) -> int:
    """跳过 ``${...}`` 里的表达式,返回配对 ``}`` 之后的下标。

    参数说明:
        source: 源文件全文。
        start: ``${`` 之后的下标。
        length: 源文件长度。

    返回参数:
        配对 ``}`` 之后的下标;没配对时返回 ``length``。

    使用示例:
        ``_skip_interpolation(source, cursor + 2, len(source))``

    备注信息:
        必须把插值里的字符串一起跳过:``'${data['k'] ?? ''}'`` 若不跳过内层的 ``'``,外层
        字符串会在那里提前收尾,后面的代码被抹成空格 —— 漏报方向。这里只跳花括号与字符串,
        注释与正则字面量不处理(插值里极少出现,出现了会多判而不是漏判)。
    """
    depth = 1
    cursor = start
    while cursor < length and depth:
        char = source[cursor]
        if char == "{":
            depth += 1
            cursor += 1
            continue
        if char == "}":
            depth -= 1
            cursor += 1
            continue
        match = _STRING_START.match(source, cursor)
        if match:
            cursor = _skip_string(
                source,
                match.end(),
                match.group(1),
                match.group(0)[0] in "rR",
                length,
            )
            continue
        cursor += 1
    return cursor


# ---------------------------------------------------------------------------
# token 生成物:建议「改用哪个 token」与字号解析都从它读,不在本脚本里抄值。
# ---------------------------------------------------------------------------

_TOKEN_CONST = re.compile(
    r"^const double (fontSize|radius|space)([A-Za-z0-9]+) = ([0-9]+(?:\.[0-9]+)?);$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class TokenScale:
    """生成物里 ``fontSize*`` / ``radius*`` / ``space*`` 三组数值 token。

    Attributes:
        by_name: token 名 → 值(例如 ``fontSizeSubtitle`` → ``17.0``)。
    """

    by_name: dict[str, float] = field(default_factory=dict)

    def value_of(self, name: str) -> float | None:
        """按 token 名取值。

        参数说明:
            name: 不含 ``tokens.`` 前缀的常量名,如 ``fontSizeBody``。

        返回参数:
            值;名字不存在时为 ``None``。

        使用示例:
            ``scale.value_of("fontSizeBody")``

        备注信息:
            用于字号下限判断;名字不存在说明页面引用了不存在的 token,交给
            ``flutter analyze`` 去红,这里不重复判。
        """
        return self.by_name.get(name)

    def suggest(self, prefix: str, value: float) -> str | None:
        """给出「这个数字对应哪个 token」。

        参数说明:
            prefix: ``fontSize`` / ``radius`` / ``space`` 之一(由规则决定)。
            value: 代码里写死的数值。

        返回参数:
            形如 ``tokens.space16`` 的建议;没有恰好相等的 token 时为 ``None``
            (说明该值本身不在 token 源里,得先改规范与 token 源)。

        使用示例:
            ``scale.suggest("space", 16)``

        备注信息:
            只做**等值**匹配:近似匹配会给出「看起来对但换了档位」的建议,比没有建议更坏。
        """
        for name, token_value in self.by_name.items():
            if name.startswith(prefix) and token_value == value:
                return f"tokens.{name}"
        return None


def load_token_scale(path: Path) -> TokenScale:
    """从 ``tokens.g.dart`` 读出三组数值 token。

    参数说明:
        path: 生成物路径(缺省 ``<root>/core/theme/tokens.g.dart``)。

    返回参数:
        解析出的 :class:`TokenScale`。

    使用示例:
        ``load_token_scale(DEFAULT_ROOT / GENERATED_RELATIVE)``

    备注信息:
        文件不存在时抛 :class:`FileNotFoundError`,由调用方翻成退出码 2:没有 token 源就没有
        「该改成哪个 token」的建议,门禁的输出会退化成「你错了但不说怎么改」。
    """
    text = path.read_text(encoding="utf-8")
    by_name: dict[str, float] = {}
    for prefix, name, value in _TOKEN_CONST.findall(text):
        by_name[f"{prefix}{name}"] = float(value)
    return TokenScale(by_name=by_name)


# ---------------------------------------------------------------------------
# 规则
# ---------------------------------------------------------------------------

_HEX = re.compile(r"(?<![\w.])0[xX]([0-9A-Fa-f]{6,})(?![\w])")
_FONT_SIZE = re.compile(r"\bfontSize\s*:\s*")
_EDGE_INSETS = re.compile(r"\bEdgeInsets\.(all|only|symmetric|fromLTRB|fromSTEB)\s*\(")
_CIRCULAR = re.compile(r"\b(BorderRadius|Radius)\.circular\s*\(")
#: 「值以数字字面量开头」:``16`` / ``2.5`` / ``-8`` 命中,``tokens.space4 / 2`` 不命中。
_NUMBER_PREFIX = re.compile(r"^-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?![0-9A-Za-z_.])")


@dataclass(frozen=True)
class Violation:
    """一处裸值。

    Attributes:
        path: 相对**被扫描目录**的路径(白名单按它匹配,``app/lib`` 之外的空)。
        display: 打印用的路径(仓库相对,便于点进编辑器)。
        line: 违规所在行号(1 起)。
        rule: 规则 id,用于统计。
        message: 一行结论,含「该改成什么」。
        snippet: 该行源码片段(去首尾空白、内部空白折叠),白名单按它匹配。
    """

    path: str
    display: str
    line: int
    rule: str
    message: str
    snippet: str

    def render(self) -> str:
        """渲染成一行 ``<文件>:<行>: <结论>``。

        返回参数:
            一行字符串,``grep`` 与 CI 日志都能直接定位。

        使用示例:
            ``print(violation.render())``

        备注信息:
            无参数。
        """
        return f"{self.display}:{self.line}: {self.message}"


@dataclass(frozen=True)
class WhitelistEntry:
    """一条白名单:逐处放行的存量裸值。

    Attributes:
        path: 相对 ``app/lib`` 的文件路径。
        line: 记录时的行号(**只给人看**,判定不看它 —— 会漂)。
        snippet: 该行源码片段(去首尾空白、内部空白折叠)。
        reason: 为什么这处数字/hex 不是设计值,或者为什么这一单不改。
        expiry: 收口说明:谁来清、清成什么。
    """

    path: str
    line: int
    snippet: str
    reason: str
    expiry: str


#: 存量白名单。**逐条**放行,不是整条规则豁免(见模块 docstring「白名单」)。
#: 每加一条都要写清 ``reason`` 与 ``expiry``;删条目是清理页单的一部分。
#:
#: 这 17 条是 2026-11-28 接入门禁时的实测存量(``python scripts/check_app_raw_values.py``),
#: 一条都不改业务代码 —— 本单只装门禁。绝大多数集中在「心跳」期的 ``core/widgets/app_*``
#: 通用件上,随 Ember 逐页迁移会自然消失;``space`` / ``radius`` 档位从 4 / 8 起,所以
#: 2.5 / 3 / 5 / 9 这些「按高度取一半」的胶囊圆角与细描边留白没有对应档位,属于要先补
#: 规范与 token 源的那一类。
WHITELIST: tuple[WhitelistEntry, ...] = (
    WhitelistEntry(
        path="im/upload_idempotency.dart",
        line=44,
        snippet="final seq = (_keySequence = (_keySequence + 1) & 0xffffff).toRadixString(36);",
        reason="序号位掩码(24 位整数掩码),不是色值;这一行没有任何视觉取值",
        expiry="永久例外:位掩码语义不会变成视觉 token;若改成具名常量 const _sequenceMask = 0xffffff 可考虑移出白名单",
    ),
    WhitelistEntry(
        path="core/ui/ember_field.dart",
        line=193,
        snippet="errorStyle: const TextStyle(height: 0, fontSize: 0),",
        reason="把 Material 自带错误行的行高压掉的结构性开关(errorText 改由字段下方自绘替代),不是设计取值",
        expiry="随 AppTextField 收口:不再向 Material 传 errorText 后删除本行",
    ),
    WhitelistEntry(
        path="core/ui/ember_pressable.dart",
        line=245,
        snippet=".add(const BorderRadius.all(Radius.circular(4))),",
        reason="聚焦光晕的圆角补正:光晕外扩 4px(Positioned -4)+ 2px 描边,圆角要在包围盒半径上加 4 才与内层贴合,不是独立设计档位",
        expiry="若 Ember 规范为「聚焦光晕」定义外扩/圆角 token,改为读 token",
    ),
    WhitelistEntry(
        path="core/widgets/app_avatar.dart",
        line=57,
        snippet="padding: const EdgeInsets.all(2.5),",
        reason="头像光环(渐变描边)的粗细 2.5px;space 档位从 4 起,没有 2.5",
        expiry="头像规格清理单:先补「光环粗细」token 或复用最接近档位,再改这一行",
    ),
    WhitelistEntry(
        path="core/widgets/app_avatar.dart",
        line=63,
        snippet="padding: const EdgeInsets.all(2),",
        reason="在线点的白色描边宽度 2px(同上,space 档位从 4 起)",
        expiry="与在线点规格一并收口,做法同上一条",
    ),
    WhitelistEntry(
        path="core/widgets/app_badge.dart",
        line=20,
        snippet="padding: const EdgeInsets.symmetric(horizontal: 5),",
        reason="18px 角标的横向留白(角标按高度定尺寸,space 档位从 4 起)",
        expiry="角标组件清理单:改读 space 档位(4 或 8)并复跑角标截图",
    ),
    WhitelistEntry(
        path="core/widgets/app_badge.dart",
        line=23,
        snippet="borderRadius: BorderRadius.circular(9),",
        reason="18px 高度角标的胶囊圆角 = 高度一半,不是 radius 档位",
        expiry="同一单里改成 tokens.radiusPill(圆角由半径表达,不写死高度的一半)",
    ),
    WhitelistEntry(
        path="core/widgets/app_dialog.dart",
        line=47,
        snippet=".copyWith(fontSize: 17, color: colors.text1),",
        reason="AppText.subtitle 的档位就是 17,这里 copyWith 同一数值是冗余写法,不是新取值",
        expiry="删掉 copyWith 里的 fontSize 即可(等价),随 app_dialog 迁移或清理单做",
    ),
    WhitelistEntry(
        path="core/widgets/app_empty_state.dart",
        line=37,
        snippet="Text(title, style: AppText.subtitle.copyWith(fontSize: 17)),",
        reason="AppText.subtitle 已是 17,该 copyWith 是冗余写法",
        expiry="删掉 copyWith(fontSize: 17)(等价),随空态组件清理单做",
    ),
    WhitelistEntry(
        path="core/widgets/app_error_view.dart",
        line=33,
        snippet="Text(title, style: AppText.subtitle.copyWith(fontSize: 17)),",
        reason="AppText.subtitle 已是 17,该 copyWith 是冗余写法",
        expiry="删掉 copyWith(fontSize: 17)(等价),随错误视图清理单做",
    ),
    WhitelistEntry(
        path="core/widgets/app_sub_page_bar.dart",
        line=45,
        snippet=".copyWith(fontSize: 17, color: colors.text1), // 17/w600(§5.2)",
        reason="注释自陈 17/w600 就是 subtitle 档,与 AppText.subtitle 重复",
        expiry="删掉 copyWith 里的 fontSize 即可(等价),随子页导航栏清理单做",
    ),
    WhitelistEntry(
        path="core/widgets/app_sub_page_bar.dart",
        line=65,
        snippet="padding: const EdgeInsets.only(right: 8),",
        reason="8 就是 tokens.space8,可直接替换的存量",
        expiry="改成 tokens.space8(零视觉变化),随子页导航栏清理单做",
    ),
    WhitelistEntry(
        path="features/chat/chats_page.dart",
        line=374,
        snippet="padding: EdgeInsets.symmetric( horizontal: tokens.space4, vertical: 1, )",
        reason="「官方」标签的 1px 贴边留白(描边式标签),space 档位从 4 起,没有 1",
        expiry="若规范为描边标签定义内边距就改读 token;改成 space4 需先过视觉验收,不在本单范围",
    ),
    WhitelistEntry(
        path="features/discovery/widgets/profile_card.dart",
        line=308,
        snippet="borderRadius: BorderRadius.circular(3),",
        reason="6px 高度滑动指示点的胶囊圆角 = 高度一半",
        expiry="改成 tokens.radiusPill,或先为「指示点」补规格",
    ),
    WhitelistEntry(
        path="features/moderation/widgets/report_sheet.dart",
        line=32,
        snippet="padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),",
        reason="四个方向都是 16 = tokens.space16,可直接替换的存量",
        expiry="改成 EdgeInsets.fromLTRB(tokens.space16, tokens.space16, tokens.space16, tokens.space16 + MediaQuery.viewInsetsOf(context).bottom)(零视觉变化)",
    ),
    WhitelistEntry(
        path="features/profile/widgets/profile_voice_card.dart",
        line=260,
        snippet="borderRadius: BorderRadius.circular(2),",
        reason="4px 高度录制进度条的胶囊圆角 = 高度一半(轨道层)",
        expiry="改成 tokens.radiusPill",
    ),
    WhitelistEntry(
        path="features/profile/widgets/profile_voice_card.dart",
        line=268,
        snippet="borderRadius: BorderRadius.circular(2),",
        reason="同一条进度条的填充层,圆角同上",
        expiry="改成 tokens.radiusPill",
    ),
)


def _split_top_level(text: str, separator: str) -> list[str]:
    """按顶层分隔符切分(跳过括号内部的)。

    参数说明:
        text: 待切分的片段。
        separator: 单字符分隔符(``,`` 或 ``:``)。

    返回参数:
        切分结果,至少一段。

    使用示例:
        ``_split_top_level("a: 1, b: 2", ",")``

    备注信息:
        跑在**已抹掉字符串**的文本上,所以不必考虑引号里的分隔符。
    """
    parts: list[str] = []
    depth = 0
    start = 0
    for position, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(text[start:position])
            start = position + 1
    parts.append(text[start:])
    return parts


def _value_of_argument(argument: str) -> str:
    """取一个实参的「值」部分。

    参数说明:
        argument: 一个实参片段,可能是 ``horizontal: 5`` 也可能是位置参数 ``16``。

    返回参数:
        命名实参取顶层冒号之后的那一段,位置参数原样返回。

    使用示例:
        ``_value_of_argument("horizontal: 5")``

    备注信息:
        取**最后**一段:三元表达式 ``cond ? 8 : 4`` 的两个分支都该判,取最后一段不会漏掉
        「以数字开头」这个判据。
    """
    return _split_top_level(argument, ":")[-1].strip()


def _starts_with_number(value: str) -> float | None:
    """判「值以数字字面量开头」并取出那个数字。

    参数说明:
        value: 实参的值表达式(已 strip)。

    返回参数:
        数字;不以数字字面量开头时返回 ``None``。

    使用示例:
        ``_starts_with_number("16 + MediaQuery.viewInsetsOf(context).bottom")``

    备注信息:
        用「开头」而不是「包含」:``16 + MediaQuery...`` 里那个 16 仍是写死的设计值;
        ``tokens.space4 / 2`` 以标识符开头,不是裸值。
    """
    match = _NUMBER_PREFIX.match(value)
    return float(match.group(0)) if match else None


def _matching_paren(text: str, open_index: int) -> int:
    """找出与 ``text[open_index]`` 处 ``(`` 配对的 ``)``。

    参数说明:
        text: 已抹掉字符串与注释的文本。
        open_index: ``(`` 的下标。

    返回参数:
        配对的 ``)`` 下标;找不到返回 ``-1``。

    使用示例:
        ``_matching_paren("all(2)", 3)``

    备注信息:
        只在已抹掉字符串的文本上调用,所以括号计数不会被字符串里的括号干扰。
    """
    depth = 0
    for position in range(open_index, len(text)):
        char = text[position]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return position
    return -1


def _format_number(value: float) -> str:
    """把数值渲染成不带多余小数点的字符串。

    参数说明:
        value: 数值。

    返回参数:
        ``16`` / ``2.5`` 这样的文本。

    使用示例:
        ``_format_number(16.0)``

    备注信息:
        只用于拼消息文本。
    """
    return f"{value:g}"


def _suggest_values(scale: TokenScale, prefix: str, values: list[float]) -> str:
    """把一组写死的值翻成「该改成哪些 token」。

    参数说明:
        scale: token 生成物里的数值档位。
        prefix: ``space`` 或 ``radius``(字号建议另走一条,要带下限提示)。
        values: 同一处写死的值(去掉重复)。

    返回参数:
        一句可直接照做的建议;有值在 token 源里找不到对应档时一并点名。

    使用示例:
        ``_suggest_values(scale, "space", [16.0, 16.0])``

    备注信息:
        「找不到对应 token」不是本门禁的事:按规范,新场景先复用最接近的档,确需新档
        **先改规范与 token 源**,再动页面 —— 所以这里只提示,不替人挑替身档位。
    """
    tokens: list[str] = []
    missing: list[str] = []
    for value in values:
        suggestion = scale.suggest(prefix, value)
        if suggestion:
            if suggestion not in tokens:
                tokens.append(suggestion)
        else:
            text = _format_number(value)
            if text not in missing:
                missing.append(text)
    parts = []
    if tokens:
        parts.append("改用 " + "、".join(tokens))
    if missing:
        parts.append("、".join(missing) + " 在 token 源里没有对应档:先改规范与 token 源,再改页面")
    return ";".join(parts)


def _font_size_note(value: float) -> str:
    """给出字号下限的提示尾巴。
    参数说明:
        value: 代码里写死的字号。

    返回参数:
        ``< 11`` / ``< 13`` 对应的提示;不低于 13 时为空串。

    使用示例:
        ``_font_size_note(9)``

    备注信息:
        规范 §11.2 的字号一行是「正文 < 13、任意 < 11 → 红」,并进裸值判定。裸值本身
        已经红了,这里只补一句「低到哪一档也不合法」,省得人以为改回 token 就万事大吉。
    """
    if value < FONT_MIN_ANY:
        return f"(低于任意字号下限 {_format_number(FONT_MIN_ANY)})"
    if value < FONT_MIN_BODY:
        return f"(低于正文下限 {_format_number(FONT_MIN_BODY)};{_format_number(FONT_MIN_ANY)} 只给 micro 角标)"
    return ""


def scan_dart_source(
    source: str,
    relative_path: str,
    display: str,
    scale: TokenScale,
) -> list[Violation]:
    """判一个 Dart 源文件里的裸值。

    参数说明:
        source: 文件全文。
        relative_path: 相对扫描目录的路径(白名单用它匹配)。
        display: 打印用路径(仓库相对)。
        scale: token 生成物里的数值档位,用来给出「改成哪个 token」的建议。

    返回参数:
        违规列表(按行号升序)。

    使用示例:
        ``scan_dart_source(text, "features/x.dart", "app/lib/features/x.dart", scale)``

    备注信息:
        判之前先把注释与字符串抹成空格;行号按偏移换算,与源码一一对应。
    """
    code = mask_non_code(source)
    line_starts = [0]
    for index, char in enumerate(source):
        if char == "\n":
            line_starts.append(index + 1)

    def line_of(offset: int) -> int:
        return bisect.bisect_right(line_starts, offset)

    def snippet_of(offset: int, end: int) -> str:
        line_number = line_of(offset)
        start = line_starts[line_number - 1]
        # 单行构造取整行(读白名单时能看到 ``padding:`` 之类的前缀),跨行构造取整段调用,
        # 因为只取首行会得到 ``padding: EdgeInsets.symmetric(`` 这种认不出是谁的片段。
        if line_number < len(line_starts):
            line_end = line_starts[line_number] - 1
        else:
            line_end = len(source)
        return " ".join(source[start : max(line_end, end)].split())

    found: list[Violation] = []

    def add(offset: int, end: int, rule: str, message: str) -> None:
        line_number = line_of(offset)
        found.append(
            Violation(
                path=relative_path,
                display=display,
                line=line_number,
                rule=rule,
                message=message,
                snippet=snippet_of(offset, end),
            )
        )

    for match in _HEX.finditer(code):
        literal = "0x" + match.group(1)
        add(
            match.start(),
            match.end(),
            "hex",
            f"裸 hex {literal}:颜色只能来自 tokens(design/tokens/*.json → tokens.g.dart)",
        )

    for match in _FONT_SIZE.finditer(code):
        cursor = match.end()
        depth = 0
        while cursor < len(code):
            char = code[cursor]
            if char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and char in ",;":
                break
            cursor += 1
        value = _starts_with_number(code[match.end() : cursor].strip())
        if value is None:
            continue
        suggestion = scale.suggest("fontSize", value)
        target = f"改用 {suggestion}" if suggestion else "改用 tokens.fontSize*(该值不在 token 源里,先改规范与 token 源)"
        add(
            match.start(),
            cursor,
            "font-size",
            f"裸字号 fontSize: {_format_number(value)}:{target}{_font_size_note(value)}",
        )

    for match in _EDGE_INSETS.finditer(code):
        open_index = match.end() - 1
        close_index = _matching_paren(code, open_index)
        if close_index < 0:
            continue
        kind = match.group(1)
        naked: list[tuple[str, float]] = []
        for argument in _split_top_level(code[open_index + 1 : close_index], ","):
            raw_value = _value_of_argument(argument)
            value = _starts_with_number(raw_value)
            if value is None or value == 0:
                continue
            named = _split_top_level(argument, ":")
            label = named[0].strip() if len(named) > 1 else ""
            naked.append((f"{label}={_format_number(value)}" if label else _format_number(value), value))
        if not naked:
            continue
        add(
            match.start(),
            close_index + 1,
            "space",
            f"裸间距 EdgeInsets.{kind}(…):写死的值 {', '.join(item[0] for item in naked)}"
            f" → {_suggest_values(scale, 'space', [item[1] for item in naked])}",
        )

    for match in _CIRCULAR.finditer(code):
        open_index = match.end() - 1
        close_index = _matching_paren(code, open_index)
        if close_index < 0:
            continue
        value = _starts_with_number(code[open_index + 1 : close_index].strip())
        if value is None or value == 0:
            continue
        add(
            match.start(),
            close_index + 1,
            "radius",
            f"裸圆角 {match.group(1)}.circular({_format_number(value)}):"
            f"{_suggest_values(scale, 'radius', [value])}",
        )

    found.sort(key=lambda item: (item.line, item.rule))
    return found


# ---------------------------------------------------------------------------
# 白名单
# ---------------------------------------------------------------------------


@dataclass
class Report:
    """一次扫描的全部结果。

    Attributes:
        files: 实际扫描的 Dart 文件数。
        violations: 没被白名单放行的违规。
        justified: 被白名单放行的违规,与命中的条目配对。
        stale: 文件里已经找不到对应片段的条目。
        drift: 行号漂移的条目(条目记录行, 实际行, 条目)。
        scanned_root: 被扫描目录。
    """

    files: int
    violations: list[Violation] = field(default_factory=list)
    justified: list[tuple[WhitelistEntry, Violation]] = field(default_factory=list)
    stale: list[WhitelistEntry] = field(default_factory=list)
    drift: list[tuple[WhitelistEntry, int]] = field(default_factory=list)
    scanned_root: Path = DEFAULT_ROOT


def dart_files(root: Path) -> list[Path]:
    """列出扫描面内的 Dart 文件。

    参数说明:
        root: 扫描目录(通常是 ``app/lib``)。

    返回参数:
        排序后的路径列表,已排除生成物 ``core/theme/tokens.g.dart``。

    使用示例:
        ``dart_files(DEFAULT_ROOT)``

    备注信息:
        排序按 POSIX 路径的字节序:输出顺序要跨平台稳定(Windows 大小写不敏感、Linux 敏感,
        ``sorted(Path)`` 会让两边顺序不同,``--check`` 的日志因此不该依赖它)。
    """
    generated = (root / GENERATED_RELATIVE).resolve()
    files = [
        path
        for path in root.rglob("*.dart")
        if path.is_file() and path.resolve() != generated
    ]
    files.sort(key=lambda path: path.relative_to(root).as_posix().encode("utf-8"))
    return files


def apply_whitelist(
    violations: list[Violation],
    entries: tuple[WhitelistEntry, ...],
) -> tuple[list[Violation], list[tuple[WhitelistEntry, Violation]], list[WhitelistEntry], list[tuple[WhitelistEntry, int]]]:
    """按白名单逐条抵扣违规。

    参数说明:
        violations: 全部违规。
        entries: 白名单条目。

    返回参数:
        四元组 ``(未放行的违规, (条目, 被放行的违规) 对, 失效条目, (条目, 实际行) 漂移对)``。

    使用示例:
        ``apply_whitelist(violations, WHITELIST)``

    备注信息:
        匹配键是「相对路径 + 行片段」,不是行号 —— 行号会随上方增删漂移。同一条目只抵扣
        **一处**:同一个文件里两行片段完全相同(例如两处 ``circular(2)``),就要写两条,
        否则其中一处仍会被判红 —— 这是有意的,白名单必须逐处可见。
    """
    buckets: dict[tuple[str, str], list[Violation]] = {}
    for violation in violations:
        buckets.setdefault((violation.path, violation.snippet), []).append(violation)

    justified: list[tuple[WhitelistEntry, Violation]] = []
    stale: list[WhitelistEntry] = []
    drift: list[tuple[WhitelistEntry, int]] = []
    for entry in entries:
        key = (entry.path, entry.snippet)
        pool = buckets.get(key)
        if not pool:
            stale.append(entry)
            continue
        matched = pool.pop(0)
        justified.append((entry, matched))
        if matched.line != entry.line:
            drift.append((entry, matched.line))

    remaining = [item for pool in buckets.values() for item in pool]
    remaining.sort(key=lambda item: (item.path.encode("utf-8"), item.line))
    return remaining, justified, stale, drift


def scan(root: Path, entries: tuple[WhitelistEntry, ...] = WHITELIST) -> Report:
    """扫一个目录并把白名单抵扣掉。

    参数说明:
        root: 扫描目录(缺省由调用方给 ``app/lib``)。
        entries: 白名单条目。

    返回参数:
        :class:`Report`。

    使用示例:
        ``scan(DEFAULT_ROOT)``

    备注信息:
        token 生成物缺失时抛 :class:`FileNotFoundError`:没有它就给不出「改成哪个 token」的建议。
    """
    root = root.resolve()
    scale = load_token_scale(root / GENERATED_RELATIVE)
    violations: list[Violation] = []
    files = dart_files(root)
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            display = path.relative_to(ROOT).as_posix()
        except ValueError:
            display = path.as_posix()
        violations.extend(scan_dart_source(path.read_text(encoding="utf-8"), relative, display, scale))
    remaining, justified, stale, drift = apply_whitelist(violations, entries)
    return Report(
        files=len(files),
        violations=remaining,
        justified=justified,
        stale=stale,
        drift=drift,
        scanned_root=root,
    )


def _display_of(root: Path, relative: str) -> str:
    """把白名单里的相对路径渲染成仓库相对路径(打印用)。

    参数说明:
        root: 扫描目录。
        relative: 相对扫描目录的路径。

    返回参数:
        仓库相对路径;扫描目录不在仓库内时用绝对路径。

    使用示例:
        ``_display_of(DEFAULT_ROOT, "im/upload_idempotency.dart")``

    备注信息:
        只影响打印,不影响判定。
    """
    try:
        return (root / relative).relative_to(ROOT).as_posix()
    except ValueError:
        return (root / relative).as_posix()


def _print_summary(report: Report, stream) -> None:
    """打印逐规则统计。

    参数说明:
        report: 扫描结果。
        stream: 输出流(``sys.stdout`` 或 ``sys.stderr``)。

    返回参数:
        无返回值。

    使用示例:
        ``_print_summary(report, sys.stdout)``

    备注信息:
        违规条数按规则分三行写,是为了让人一眼看出「这次是不是只多了一类」。
    """
    counts: dict[str, int] = {}
    for violation in report.violations:
        counts[violation.rule] = counts.get(violation.rule, 0) + 1
    total = len(report.violations)
    detail = ", ".join(f"{rule}={counts[rule]}" for rule in sorted(counts)) or "无"
    print(
        f"App 裸值:扫描 {report.files} 个 Dart 文件,违规 {total} 处({detail});"
        f"白名单放行 {len(report.justified)} 处 / 共 {len(WHITELIST)} 条",
        file=stream,
    )


def _scan_or_none(
    root: Path,
    entries: tuple[WhitelistEntry, ...] = WHITELIST,
) -> Report | None:
    """扫一遍目录,把工具自身的错误翻成 ``None``。

    参数说明:
        root: 扫描目录。
        entries: 白名单条目(缺省生产用的 :data:`WHITELIST`;自测传入临时条目)。

    返回参数:
        扫描结果;工具自身出错(找不到 token 生成物 / 读不了文件)时打印原因并返回 ``None``。

    使用示例:
        ``report = _scan_or_none(DEFAULT_ROOT)``

    备注信息:
        ``None`` 在 :func:`main` 里一律翻成退出码 2 —— 「跑不了」不许伪装成「全绿」。
    """
    try:
        return scan(root, entries=entries)
    except FileNotFoundError as error:
        print(
            f"错误:找不到 token 生成物 {error.filename};先跑 python scripts/design_tokens.py --write",
            file=sys.stderr,
        )
        return None
    except OSError as error:
        print(f"错误:{error}", file=sys.stderr)
        return None


def check(
    root: Path,
    verbose: bool = False,
    entries: tuple[WhitelistEntry, ...] = WHITELIST,
) -> int:
    """门禁入口:打印违规并以退出码表达。

    参数说明:
        root: 扫描目录。
        verbose: 是否附带逐条白名单命中与行号偏差。
        entries: 白名单条目(缺省生产用的 :data:`WHITELIST`;自测传入临时条目)。

    返回参数:
        ``0`` = 全部合规;``1`` = 有违规或白名单失效;``2`` = 工具自己出错。

    使用示例:
        ``sys.exit(check(DEFAULT_ROOT))``

    备注信息:
        白名单失效也算红:条目在文件里找不到对应片段,说明存量已清(应删条目)或代码改过
        (应重新核对)。不这样判,白名单会只增不减,门禁迟早被它关掉。
    """
    report = _scan_or_none(root, entries=entries)
    if report is None:
        return EXIT_TOOLING

    for violation in report.violations:
        print(violation.render())
    for entry in report.stale:
        print(
            f"{_display_of(report.scanned_root, entry.path)}:{entry.line}: "
            f"白名单条目失效(该文件里已找不到这行片段):存量已清就删条目,代码改过就重新核对 —— {entry.snippet}"
        )
    if verbose:
        _verbose(report)
    if report.violations or report.stale:
        print(
            f"App 裸值门禁:发现 {len(report.violations)} 处裸值 + {len(report.stale)} 条失效白名单"
            f"(扫描 {report.files} 个文件)"
        )
        return EXIT_FINDINGS
    print(f"App 裸值门禁:{report.files} 个文件全部合规(白名单放行 {len(report.justified)} 处存量)")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 参数列表(默认取 ``sys.argv[1:]``)。

    返回参数:
        进程退出码,含义见模块 docstring。

    使用示例:
        ``main(["--check"])``

    备注信息:
        ``--root`` 只给自测用(临时目录造样本);生产路径不参数化,门禁命令里也没有它。
    """
    parser = argparse.ArgumentParser(description="App 侧裸值门禁(裸 hex / 字号 / 间距 / 圆角)")
    parser.add_argument("--check", action="store_true", help="判红:有违规或白名单失效即非 0")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="扫描目录(自测用,缺省 app/lib)")
    parser.add_argument("--verbose", action="store_true", help="附带逐条白名单命中与行号偏差")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"错误:扫描目录不存在:{args.root}", file=sys.stderr)
        return EXIT_TOOLING

    if args.check:
        return check(args.root, verbose=args.verbose)

    report = _scan_or_none(args.root)
    if report is None:
        return EXIT_TOOLING
    _print_summary(report, sys.stdout)
    for violation in report.violations:
        print(violation.render())
    if args.verbose:
        _verbose(report)
    return EXIT_OK


def _verbose(report: Report) -> None:
    """打印白名单命中与行号漂移(``--verbose``)。

    参数说明:
        report: 扫描结果。

    返回参数:
        无返回值。

    使用示例:
        ``_verbose(report)``

    备注信息:
        走到 ``stderr``,不污染 ``--check`` 的机器可读输出。
    """
    for entry, violation in report.justified:
        print(
            f"[白名单] {violation.display}:{violation.line} <- 记录行 {entry.line};{entry.reason}",
            file=sys.stderr,
        )
    for entry, actual in report.drift:
        print(
            f"[白名单] 行号漂移:{_display_of(report.scanned_root, entry.path)} 记录 {entry.line} → 实际 {actual}(判定按片段,不需要改)",
            file=sys.stderr,
        )


if __name__ == "__main__":
    sys.exit(main())
