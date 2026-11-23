"""设计 token 生成器（「余烬 Ember」单一事实来源）。

`design/tokens/*.json`（DTCG 形态）是**唯一事实来源**，本脚本把它展开成三份生成物：

| 生成物 | 消费者 |
|---|---|
| `app/lib/core/theme/tokens.g.dart` | Flutter（E-2 起被 theme 引用） |
| `web/src/styles/tokens.generated.css` | Web（E-3 起被 PrimeVue / Tailwind 引用） |
| `design/tokens.resolved.json` | 文档与 agent 查最终值 |

**为什么不用 Style Dictionary**：它是 JS 包，而 `contract` 轨只装 Python（PyYAML +
tree-sitter）。为了两份产物把 Node 拉进契约轨、并让门禁依赖 `npm ci`，成本远高于
收益；DTCG 用到的子集只有「嵌套分组 + `{alias}` 引用」，纯标准库 200 行就够，而且
版本永远不会漂。别名环、悬空引用都由本脚本自己报错（fail-closed），不静默输出空值。

用法（仓库根目录）::

    python scripts/design_tokens.py --write   # 改完 token 后重新生成
    python scripts/design_tokens.py --check   # 门禁：生成物与源头一致

退出码 0 = 一致 / 1 = 漂移或源头有错 / 2 = 用法错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKENS_DIR = REPO_ROOT / "design" / "tokens"
SCALE_SOURCE = TOKENS_DIR / "scale.json"
PRIMITIVE_SOURCE = TOKENS_DIR / "primitive.color.json"
SEMANTIC_SOURCES = {
    "light": TOKENS_DIR / "semantic.light.json",
    "dark": TOKENS_DIR / "semantic.dark.json",
}

DART_OUT = REPO_ROOT / "app" / "lib" / "core" / "theme" / "tokens.g.dart"
CSS_OUT = REPO_ROOT / "web" / "src" / "styles" / "tokens.generated.css"
RESOLVED_OUT = REPO_ROOT / "design" / "tokens.resolved.json"

ALIAS_RE = re.compile(r"^\{([^{}]+)\}$")
CAMEL_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")

HEADER_COMMON = (
    "GENERATED CODE - DO NOT EDIT BY HAND.\n"
    "源: design/tokens/ 下的 JSON:{sources}\n"
    "生成: python scripts/design_tokens.py --write\n"
    "改了 token 请改 design/tokens/ 里的 JSON 并重跑生成器;直接手改本文件会被门禁判红。"
)


class TokenError(RuntimeError):
    """token 源头不合法(悬空引用 / 循环引用 / 类型不支持)。"""


def rel(path: Path) -> str:
    """把路径尽量显示成相对仓库根的形式。

    参数说明:
        path: 任意路径(可能不在仓库里,例如自测用的临时目录)。

    返回参数:
        str: 相对路径(POSIX 分隔)或原路径字符串。

    使用示例:
        ``rel(REPO_ROOT / "design") == "design"``

    备注信息:
        直接调 ``path.relative_to(REPO_ROOT)`` 会对仓库外的路径抛 ``ValueError`` ——
        报错信息本身就炸掉,是最难查的一类门禁故障(自测里踩到过)。
    """
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    """读一个 JSON 文件。

    参数说明:
        path: 文件路径。

    返回参数:
        dict: 解析后的对象。

    使用示例:
        ``read_json(SCALE_SOURCE)``

    备注信息:
        读不到或 JSON 非法时抛出 ``TokenError``(而不是裸 ``OSError``),
        让上层统一按「源头有错」处理,退出码为 1。
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TokenError(f"缺少 token 源文件:{rel(path)}") from exc
    except json.JSONDecodeError as exc:
        raise TokenError(f"{rel(path)} 不是合法 JSON:{exc}") from exc


def flatten(node: dict[str, Any], prefix: tuple[str, ...] = ()) -> dict[str, dict[str, Any]]:
    """把嵌套分组压平成 ``{"color.text.primary": {...}}``。

    参数说明:
        node: 一层 token 分组。
        prefix: 递归累积的路径前缀。

    返回参数:
        dict: 叶子路径 -> 该 token 的原始声明(含 ``$value`` / ``$type``)。

    使用示例:
        ``flatten({"color": {"brand": {"default": {"$value": "#C93C22"}}}})``

    备注信息:
        以 ``$`` 开头的键(``$description`` / ``$type`` 等)不参与路径,与 DTCG 一致。
        一个节点既没有 ``$value`` 又有子节点时按分组继续下钻。
    """
    out: dict[str, dict[str, Any]] = {}
    for key, value in node.items():
        if key.startswith("$"):
            continue
        path = prefix + (key,)
        if isinstance(value, dict) and "$value" not in value and "value" not in value:
            out.update(flatten(value, path))
        elif isinstance(value, dict):
            out[".".join(path)] = value
        else:
            raise TokenError(f"{'.'.join(path)} 不是合法的 token(缺 $value)")
    return out


def raw_value(token: dict[str, Any]) -> Any:
    """取一个 token 的原始值。

    参数说明:
        token: token 声明。

    返回参数:
        Any: ``$value``(DTCG)或 ``value``(Tokens Studio 经典形态)的值。

    使用示例:
        ``raw_value({"$value": "#FFFFFF"})``

    备注信息:
        两种形态都认,是为了将来从 Tokens Studio 导出的文件能直接落进仓库。
    """
    if "$value" in token:
        return token["$value"]
    if "value" in token:
        return token["value"]
    raise TokenError(f"token 缺 $value:{token}")


def resolve(path: str, flat: dict[str, dict[str, Any]], stack: tuple[str, ...] = ()) -> Any:
    """解析一个 token 的最终值(递归展开 ``{alias}``)。

    参数说明:
        path: token 路径。
        flat: 压平后的 token 表。
        stack: 已访问路径(用于识别循环引用)。

    返回参数:
        Any: 展开到字面量的最终值。

    使用示例:
        ``resolve("color.brand.default", flat)``

    备注信息:
        悬空引用与循环引用都抛 ``TokenError`` —— 这两种错在生成物里表现为空值,
        不报错的话会一路跑到客户端渲染成透明,比直接红难查得多。
    """
    if path in stack:
        raise TokenError("别名循环引用:" + " -> ".join(stack + (path,)))
    if path not in flat:
        raise TokenError(f"别名指向不存在的 token:{path}")
    value = raw_value(flat[path])
    if isinstance(value, str):
        match = ALIAS_RE.match(value.strip())
        if match:
            return resolve(match.group(1), flat, stack + (path,))
    return value


def load_mode(mode: str) -> dict[str, dict[str, Any]]:
    """装配某一模式下的**语义** token 表(primitive 只作解析上下文)。

    参数说明:
        mode: ``light`` 或 ``dark``。

    返回参数:
        dict: 语义路径 -> ``{"value": 最终值, "type": 类型}``。

    使用示例:
        ``load_mode("dark")["color.brand.default"]["value"] == "#FF9370"``

    备注信息:
        返回结果**不含** primitive 色阶:它们是内部生值,两种模式取值相同,
        复制进两套生成物只会让客户端多出 60 个永远相同的常量。
    """
    primitive_flat = flatten(read_json(PRIMITIVE_SOURCE))
    flat = dict(primitive_flat)
    flat.update(flatten(read_json(SEMANTIC_SOURCES[mode])))
    return {
        path: {"value": resolve(path, flat), "type": token.get("$type") or token.get("type")}
        for path, token in flat.items()
        if path not in primitive_flat
    }


def load_scale() -> dict[str, dict[str, Any]]:
    """装配与模式无关的尺度 token(间距 / 圆角 / 字阶 / 弹簧 / 层级)。

    返回参数:
        dict: 路径 -> ``{"value": 最终值, "type": 类型}``。

    使用示例:
        ``load_scale()["radius.md"]["value"]``

    备注信息:
        尺度层不参与明暗切换,所以只有一份。
    """
    flat = flatten(read_json(SCALE_SOURCE))
    return {
        path: {"value": resolve(path, flat), "type": token.get("$type") or token.get("type")}
        for path, token in flat.items()
    }


def camel(path: str) -> str:
    """把点分路径转成 Dart 标识符片段。

    参数说明:
        path: 形如 ``color.status.onDanger`` 的路径。

    返回参数:
        str: 形如 ``colorStatusOnDanger`` 的标识符片段。

    使用示例:
        ``camel("space.20") == "space20"``

    备注信息:
        首段小写、后续段首字母大写(``color.status.onDanger`` -> ``colorStatusOnDanger``);
        纯数字段(``space.20``)直接拼在上一段后面,不插入分隔。
    """
    parts: list[str] = []
    for segment in path.split("."):
        if not segment:
            continue
        if parts and segment[:1].isdigit():
            parts[-1] = parts[-1] + segment
        elif parts:
            parts.append(segment[:1].upper() + segment[1:])
        else:
            parts.append(segment[:1].lower() + segment[1:])
    return "".join(parts)


def kebab(path: str) -> str:
    """把点分路径转成 CSS 自定义属性名。

    参数说明:
        path: 形如 ``font.lineHeight.body`` 的路径。

    返回参数:
        str: 形如 ``--font-line-height-body`` 的变量名。

    使用示例:
        ``kebab("radius.xs") == "--radius-xs"``

    备注信息:
        camelCase 段会先按大写边界切开(``reducedDurationMs`` -> ``reduced-duration-ms``)。
    """
    segments = []
    for segment in path.split("."):
        segments.extend(CAMEL_BOUNDARY_RE.sub("-", segment).lower().split("-"))
    return "--" + "-".join(part for part in segments if part)


def dart_color(value: str) -> str:
    """把 CSS 十六进制颜色转成 Dart ``Color`` 的字面量。

    参数说明:
        value: ``#RRGGBB`` 或 ``#RRGGBBAA``。

    返回参数:
        str: 形如 ``0xFFC93C22`` 的字面量。

    使用示例:
        ``dart_color("#1C1714EB") == "0xEB1C1714"``

    备注信息:
        带 alpha 的 8 位写法在 CSS 里是 ``RRGGBBAA``,Dart 要 ``AARRGGBB``,顺序必须换。
    """
    digits = value.strip().lstrip("#").upper()
    if len(digits) == 6:
        digits = "FF" + digits
    elif len(digits) == 8:
        digits = digits[6:8] + digits[0:6]
    else:
        raise TokenError(f"不支持的颜色写法:{value}")
    return f"0x{digits}"


def dart_literal(token: dict[str, Any]) -> str:
    """把一个已解析的 token 转成 Dart 字面量。

    参数说明:
        token: ``{"value": ..., "type": ...}``。

    返回参数:
        str: Dart 源码里的字面量文本。

    使用示例:
        ``dart_literal({"value": "16px", "type": "dimension"}) == "16.0"``

    备注信息:
        尺寸与时长在 Dart 侧只保留数值(px / ms 由类型语义承担);
        阴影暂时输出字符串,由 E-2 的 theme 组装成 ``BoxShadow``。
    """
    value, kind = token["value"], token["type"]
    if kind == "color":
        return f"Color({dart_color(str(value))})"
    if kind in {"dimension", "duration"}:
        number = re.sub(r"[a-zA-Z]+$", "", str(value))
        return f"{float(number):g}" if "." in str(float(number)) else f"{float(number):.1f}"
    if kind in {"number", "fontWeight"}:
        return f"{float(value):.1f}" if kind == "number" else str(int(value))
    if kind in {"fontFamily", "shadow"}:
        return "'" + str(value).replace("'", "\\'") + "'"
    raise TokenError(f"不支持的 token 类型:{kind}")


def dart_type(token: dict[str, Any]) -> str:
    """给出 Dart 侧应声明的类型名。

    参数说明:
        token: ``{"value": ..., "type": ...}``。

    返回参数:
        str: ``Color`` / ``double`` / ``int`` / ``String`` 之一。

    使用示例:
        ``dart_type({"value": "#FFFFFF", "type": "color"}) == "Color"``

    备注信息:
        只有这四种:新增类型必须同时扩展本函数,否则生成会抛错(fail-closed)。
    """
    kind = token["type"]
    if kind == "color":
        return "Color"
    if kind in {"dimension", "duration", "number"}:
        return "double"
    if kind == "fontWeight":
        return "int"
    if kind in {"fontFamily", "shadow"}:
        return "String"
    raise TokenError(f"不支持的 token 类型:{kind}")


def css_value(token: dict[str, Any]) -> str:
    """把一个已解析的 token 转成 CSS 值文本。

    参数说明:
        token: ``{"value": ..., "type": ...}``。

    返回参数:
        str: 可直接写进自定义属性的值。

    使用示例:
        ``css_value({"value": 1.55, "type": "number"}) == "1.55"``

    备注信息:
        颜色原样输出(保留 8 位 alpha 写法);时长补 ``ms`` 单位。
    """
    value, kind = token["value"], token["type"]
    if kind == "duration":
        return f"{value}ms" if not str(value).endswith("ms") else str(value)
    return str(value)


def natural_key(path: str) -> tuple[tuple[int, int, str], ...]:
    """把路径切成可自然排序的键(数字段按数值比,其余按字符比)。

    参数说明:
        path: token 路径。

    返回参数:
        tuple: 供 ``sorted`` 使用的键。

    使用示例:
        ``sorted(["color.ember.50", "color.ember.100"], key=natural_key)``

    备注信息:
        纯字典序会把 ``100`` 排在 ``50`` 前面,色阶读起来是乱的;切段后
        ``ember.50`` < ``ember.100``。整个键只由 ASCII 构成,Windows 与 Linux 结果一致。
    """
    return tuple(
        (0, int(chunk), "") if chunk.isdigit() else (1, 0, chunk)
        for chunk in re.split(r"(\d+)", path)
        if chunk
    )


def sorted_paths(tokens: dict[str, dict[str, Any]]) -> list[str]:
    """返回稳定排序后的 token 路径列表。

    参数说明:
        tokens: 路径 -> token。

    返回参数:
        list[str]: 按自然序(数字段按数值)排列的路径。

    使用示例:
        ``sorted_paths(load_scale())[0]``

    备注信息:
        排序必须跨平台一致(仓库踩过 ``sorted(Path)`` 大小写敏感差异的坑),
        所以键里不出现语言环境相关的东西。
    """
    return sorted(tokens, key=natural_key)


def emit_dart(light: dict, dark: dict, scale: dict) -> str:
    """生成 ``app/lib/core/theme/tokens.g.dart`` 的完整内容。

    参数说明:
        light: 浅色模式的语义 token。
        dark: 深色模式的语义 token。
        scale: 与模式无关的尺度 token。

    返回参数:
        str: 文件内容(行尾 LF)。

    使用示例:
        ``emit_dart(load_mode("light"), load_mode("dark"), load_scale())``

    备注信息:
        顶层 ``const`` 而不是类:页面侧取用直观,也不会触发 ``flutter analyze``
        的 ``unused_element``(公开成员不算未使用)。
    """
    # 用 ``//`` 行注释而不是 ``/* */`` 块注释:Dart 的块注释**可以嵌套**,头部文案里
    # 一旦出现 ``/*`` 就会打开一层永不闭合的嵌套注释 —— 生成物直接是语法错误
    # (2026-11-23 被 ``flutter analyze`` 当场抓到,门禁只比字节是发现不了的)。
    rule = "// " + "=" * 76
    lines = [
        rule,
        *[f"// {line}" for line in HEADER_COMMON.format(
            sources="primitive.color.json, semantic.light.json, semantic.dark.json, scale.json"
        ).splitlines()],
        rule,
        "",
        "import 'dart:ui' show Color;",
        "",
        "// lib/core/theme/tokens.g.dart 由 scripts/design_tokens.py 生成。",
        "",
    ]
    for label, tokens in (("Light", light), ("Dark", dark)):
        lines.append(f"// --- 色彩 · {label} ---")
        for path in sorted_paths(tokens):
            token = tokens[path]
            if token["type"] != "color":
                continue
            lines.append(f"const {dart_type(token)} {camel(path)}{label} = {dart_literal(token)};")
        lines.append("")
    lines.append("// --- 尺度（与模式无关） ---")
    for path in sorted_paths(scale):
        token = scale[path]
        lines.append(f"const {dart_type(token)} {camel(path)} = {dart_literal(token)};")
    lines.append("")
    return "\n".join(lines)


def emit_css(light: dict, dark: dict, scale: dict) -> str:
    """生成 ``web/src/styles/tokens.generated.css`` 的完整内容。

    参数说明:
        light: 浅色模式的语义 token。
        dark: 深色模式的语义 token。
        scale: 与模式无关的尺度 token。

    返回参数:
        str: 文件内容(行尾 LF)。

    使用示例:
        ``emit_css(load_mode("light"), load_mode("dark"), load_scale())``

    备注信息:
        浅色写在 ``:root``;深色同时给「跟随系统」与「显式 ``data-theme``」两条路径,
        显式选择必须能压过系统偏好(``:root:not([data-theme="light"])``)。
    """
    def block(tokens: dict, scale_tokens: dict | None, indent: str) -> list[str]:
        out = []
        for path in sorted_paths(tokens):
            token = tokens[path]
            if token["type"] != "color":
                continue
            out.append(f"{indent}{kebab(path)}: {css_value(token)};")
        if scale_tokens:
            for path in sorted_paths(scale_tokens):
                out.append(f"{indent}{kebab(path)}: {css_value(scale_tokens[path])};")
        return out

    lines = [
        "/" + "*" * 78,
        HEADER_COMMON.format(sources="primitive.color.json, semantic.light.json, semantic.dark.json, scale.json"),
        "*" + "/",
        "",
        ":root {",
        *block(light, scale, "  "),
        "}",
        "",
        "/* 跟随系统（显式选了 light 时不生效） */",
        "@media (prefers-color-scheme: dark) {",
        '  :root:not([data-theme="light"]) {',
        *block(dark, None, "    "),
        "  }",
        "}",
        "",
        '/* 显式选择:优先级高于系统偏好 */',
        '[data-theme="dark"] {',
        *block(dark, None, "  "),
        "}",
        "",
        '[data-theme="light"] {',
        *block(light, None, "  "),
        "}",
        "",
    ]
    return "\n".join(lines)


def emit_resolved(light: dict, dark: dict, scale: dict) -> str:
    """生成 ``design/tokens.resolved.json`` 的完整内容。

    参数说明:
        light: 浅色模式的语义 token。
        dark: 深色模式的语义 token。
        scale: 与模式无关的尺度 token。

    返回参数:
        str: 文件内容(缩进 2、行尾 LF、末尾换行)。

    使用示例:
        ``emit_resolved(load_mode("light"), load_mode("dark"), load_scale())``

    备注信息:
        这份文件是给人/agent 查最终值的(别名已展开),不参与构建;
        保留 ``$type`` 是为了让读者知道每个值该怎么用。
    """
    payload = {
        "$meta": {"source": "design/tokens/*.json", "generator": "scripts/design_tokens.py"},
        "light": {path: {"$type": tok["type"], "$value": tok["value"]} for path, tok in light.items()},
        "dark": {path: {"$type": tok["type"], "$value": tok["value"]} for path, tok in dark.items()},
        "scale": {path: {"$type": tok["type"], "$value": tok["value"]} for path, tok in scale.items()},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def ensure_mode_parity(light: dict[str, dict[str, Any]], dark: dict[str, dict[str, Any]]) -> None:
    """校验明暗两套语义 token 的键集完全一致。

    参数说明:
        light: 浅色模式 token 表。
        dark: 深色模式 token 表。

    返回参数:
        无(校验通过即返回)。

    使用示例:
        ``ensure_mode_parity(load_mode("light"), load_mode("dark"))``

    备注信息:
        少一个深色值 → 该元素在深色模式下**静默回落到浅色值**(CSS 变量没被覆盖),
        表现为「某个角落一直是亮的」,极难定位。所以这是 fail-closed 而不是警告。
    """
    missing_dark = sorted(set(light) - set(dark))
    missing_light = sorted(set(dark) - set(light))
    if missing_dark or missing_light:
        details = []
        if missing_dark:
            details.append("深色缺:" + "、".join(missing_dark))
        if missing_light:
            details.append("浅色缺:" + "、".join(missing_light))
        raise TokenError("明暗两套语义 token 键集不一致 —— " + ";".join(details))


def build() -> dict[Path, str]:
    """算出全部生成物的期望内容。

    返回参数:
        dict: 目标路径 -> 期望文本。

    使用示例:
        ``build()[DART_OUT]``

    备注信息:
        一次装配、一次解析,``--check`` 与 ``--write`` 共用同一份结果 ——
        两条路径不可能给出不同答案。
    """
    light = load_mode("light")
    dark = load_mode("dark")
    scale = load_scale()
    ensure_mode_parity(light, dark)
    return {
        DART_OUT: emit_dart(light, dark, scale),
        CSS_OUT: emit_css(light, dark, scale),
        RESOLVED_OUT: emit_resolved(light, dark, scale),
    }


def check() -> int:
    """校验仓库里的生成物与源头一致。

    返回参数:
        int: 0 = 一致;1 = 有漂移或源头有错。

    使用示例:
        ``sys.exit(check())``

    备注信息:
        逐文件比对字节(不做换行归一化):生成物必须原样提交,CI 按字节判。
    """
    try:
        expected = build()
    except TokenError as exc:
        print(f"::error::token 源头不合法:{exc}")
        return 1
    fail = 0
    for path, text in expected.items():
        rel_path = rel(path)
        if not path.exists():
            print(f"::error file={rel_path}::生成物不存在,先跑 python scripts/design_tokens.py --write")
            fail = 1
            continue
        # 按字节读:``read_text`` 会把 CRLF 归一化成 LF,那样 CRLF 版本的生成物也能过关,
        # 而 CI 是按字节比对的(仓库踩过「CRLF 让同一份契约算出两个哈希」的坑)。
        actual = path.read_bytes().decode("utf-8")
        if actual != text:
            print(f"::error file={rel_path}::与 design/tokens/*.json 不一致,先跑 python scripts/design_tokens.py --write")
            fail = 1
    if not fail:
        print(f"design_tokens: {len(expected)} 份生成物与源头一致")
    return fail


def write() -> int:
    """按源头重写全部生成物。

    返回参数:
        int: 0 = 成功;1 = 源头有错。

    使用示例:
        ``sys.exit(write())``

    备注信息:
        父目录不存在时自动创建;先写 ``design/tokens.resolved.json`` 再写两端产物,
        保证即使中途失败,人也能看到展开后的值。
    """
    try:
        expected = build()
    except TokenError as exc:
        print(f"::error::token 源头不合法:{exc}")
        return 1
    for path, text in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        print(f"已写入 {rel(path)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 参数列表(默认取 ``sys.argv[1:]``)。

    返回参数:
        int: 进程退出码。

    使用示例:
        ``main(["--check"])``

    备注信息:
        ``--check`` 与 ``--write`` 必须显式二选一:默认动作是这两者之一时,
        最容易被误当成「什么都不做」。
    """
    parser = argparse.ArgumentParser(description="设计 token 生成器（余烬 Ember）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="校验生成物与源头一致")
    group.add_argument("--write", action="store_true", help="按源头重写生成物")
    args = parser.parse_args(argv)
    return check() if args.check else write()


if __name__ == "__main__":
    sys.exit(main())
