"""Figma(Tokens Studio）导出物 → 仓库 token 源 的往返校验器。

E-1 之后仓库的事实来源是 `design/tokens/*.json`，Figma 侧只是**可视化编辑端**：

    Figma(Tokens Studio) ──导出 JSON──> 本脚本比对 ──只落值──> design/tokens/*.json
                                                                └─> design_tokens.py --write

免费档没有 Theme、同步只能单文件，所以「只改值、不改结构」这条纪律**不能靠人自觉**：
编辑器一旦把 `color.brand.default` 从 `{color.ember.600}` 摊成 `#C93C22`，或把
`dimension` 改成 `number`，生成物就跟着变，而人眼看 diff 只会看到一堆值变了。
本脚本把这件事机械化成两个方向：

| 差异类别 | 含义 | 处置 |
|---|---|---|
| **值变更** | 路径、`$type` 都没动，只有 `$value` 不同 | 可用 `--apply` 落盘 |
| **悬空引用** | 值变更把某个值改成了 `{alias}`，但该别名在仓库里不存在 | **拒绝 `--apply`**，必须回 PR 手改 |
| **结构变更** | 路径新增/缺失、`$type` 变了、`$description` 变了 | **拒绝 `--apply`**，必须回 PR 手改 |

用法（仓库根目录）::

    python scripts/figma_tokens_roundtrip.py --export tmp/figma-export.json           # 只报告
    python scripts/figma_tokens_roundtrip.py --export tmp/figma-export.json --apply   # 落值
    python scripts/design_tokens.py --write                                          # 再重生成

退出码 0 = 无结构漂移（可能含值变更）/ 1 = 有结构漂移 / 2 = 用法或输入错误。

**已知的形态差异都在这层吸收**（否则「diff 只落在值上」永远做不到）：Tokens Studio 会写
`$themes` / `$metadata` 这两个仓库没有的包裹块、会把 `#RRGGBBAA` 写成 `rgba()`、把
`fontFamily` 写成数组、把 `"8px"` 写成 `8`、默认还是 legacy 格式（`value` 而非 `$value`）。
这些在本脚本里都归一到**可比形态**再比，不算结构变更。
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

#: 编辑器里的 token set 名 -> 仓库里的源文件。名字故意与文件名对齐（`semantic.light` 的
#: set 名就是 `light`），因为 set 名一旦和文件名对不上，人就得在两套命名之间来回翻译。
SET_FILES: dict[str, str] = {
    "light": "semantic.light.json",
    "dark": "semantic.dark.json",
    "primitive": "primitive.color.json",
    "scale": "scale.json",
}

#: Tokens Studio 的 legacy 类型名 -> 本仓库使用的 DTCG 类型名。只映射**确实等价**的：
#: `borderRadius` / `spacing` / `sizing` 在 DTCG 里都是 `dimension`，其余保持原样。
TS_TYPE_ALIASES: dict[str, str] = {
    "borderRadius": "dimension",
    "borderWidth": "dimension",
    "spacing": "dimension",
    "sizing": "dimension",
    "fontSizes": "dimension",
    "lineHeights": "number",
    "letterSpacing": "dimension",
    "fontFamilies": "fontFamily",
    "fontWeights": "fontWeight",
    "opacity": "number",
}

#: 仓库源的排版约定：叶子 token 必须**单行**（`"$value": ..., "$type": ...`），组按层缩进。
#: `--apply` 落盘时按这个约定重写，否则一次改值会带来满文件的换行噪声。
_INDENT = "  "
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3,8})$")
_ALIAS_RE = re.compile(r"^\{([^{}]+)\}$")
_RGB_RE = re.compile(
    r"^rgba?\(\s*([0-9.]+%?)\s*,\s*([0-9.]+%?)\s*,\s*([0-9.]+%?)\s*(?:,\s*([0-9.]+%?)\s*)?\)$"
)
_DIM_RE = re.compile(r"^(-?[0-9]*\.?[0-9]+)([a-zA-Z%]*)$")


class RoundtripError(RuntimeError):
    """导出物或输入参数不合法（读不到、不是 JSON、set 名不认识）。"""


def rel(path: Path) -> str:
    """把路径尽量显示成相对仓库根的形式。

    参数说明:
        path: 任意路径。

    返回参数:
        str: 相对路径（POSIX 分隔）或原路径字符串。

    使用示例:
        ``rel(REPO_ROOT / "design") == "design"``

    备注信息:
        与 ``design_tokens.py`` 同口径：仓库外路径不抛 ``ValueError``。
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
        ``read_json(Path("tmp/figma-export.json"))``

    备注信息:
        读不到或 JSON 非法时抛 ``RoundtripError``（而不是裸 ``OSError``），
        让 ``main`` 统一按退出码 2 处理 —— 这属于「输入不对」，不是「结构漂移」。
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RoundtripError(f"文件不存在:{rel(path)}") from exc
    except json.JSONDecodeError as exc:
        raise RoundtripError(f"{rel(path)} 不是合法 JSON:{exc}") from exc


def is_token(node: Any) -> bool:
    """判断一个节点是不是叶子 token（而不是分组）。

    参数说明:
        node: 任意 JSON 节点。

    返回参数:
        bool: 带 ``$value``（或 legacy 的 ``value``）即视为 token。

    使用示例:
        ``is_token({"$value": "#FFF", "$type": "color"}) is True``

    备注信息:
        判断只看「有没有值」。只看 ``$type`` 会把带 ``$type`` 的分组误判成 token
        （DTCG 允许在分组上写 ``$type`` 继承给子节点），那会让展开结果少一整棵子树。
    """
    return isinstance(node, dict) and ("$value" in node or "value" in node)


def token_field(node: dict[str, Any], name: str) -> Any:
    """按 DTCG（``$name``）优先、legacy（``name``）兜底取字段。

    参数说明:
        node: 叶子 token 节点。
        name: 不带 ``$`` 的字段名，例如 ``value`` / ``type`` / ``description``。

    返回参数:
        Any: 字段值；两边都没有时返回 ``None``。

    使用示例:
        ``token_field({"value": "8px", "type": "dimension"}, "type") == "dimension"``

    备注信息:
        Tokens Studio 默认仍是 legacy 格式，免费档用户大多不会去设置页切 DTCG。
        两种形态必须在同一层吸收掉，否则第一次导出就会被判成「结构全变了」。
    """
    if f"${name}" in node:
        return node[f"${name}"]
    return node.get(name)


def flatten(node: dict[str, Any], prefix: tuple[str, ...] = ()) -> dict[str, dict[str, Any]]:
    """把嵌套分组压平成 ``{"color.text.primary": {"value": ..., "type": ...}}``。

    参数说明:
        node: 一层分组（根或子树）。
        prefix: 递归累积的路径前缀。

    返回参数:
        dict: token 路径 -> ``{"value", "type", "description"}``（缺项为 ``None``）。

    使用示例:
        ``flatten({"color": {"brand": {"$value": "#C93C22", "$type": "color"}}})``

    备注信息:
        ``$`` 开头的键（``$themes`` / ``$metadata`` / ``$description``）一律跳过：
        这些是 Tokens Studio 或 DTCG 的**包裹信息**，仓库里没有对应物，
        拿来比只会让第一次往返就红。
    """
    out: dict[str, dict[str, Any]] = {}
    for key, value in node.items():
        if key.startswith("$"):
            continue
        if is_token(value):
            out[".".join(prefix + (key,))] = {
                "value": token_field(value, "value"),
                "type": token_field(value, "type"),
                "description": token_field(value, "description"),
            }
        elif isinstance(value, dict):
            out.update(flatten(value, prefix + (key,)))
    return out


def _channel(text: str) -> float:
    """把一个颜色通道文本归一化到 0-255 浮点。

    参数说明:
        text: 形如 ``255`` / ``37.5`` / ``50%`` 的通道文本。

    返回参数:
        float: 0-255 区间的通道值。

    使用示例:
        ``_channel("50%") == 127.5``

    备注信息:
        百分比通道在 CSS 里合法，Tokens Studio 的取色器也可能写出这种形态；
        不归一化就会被判成「值变了」。
    """
    if text.endswith("%"):
        return round(float(text[:-1]) * 255 / 100, 3)
    return float(text)


def _fmt_num(value: float) -> str:
    """把数值格式化成最短可比文本（去掉多余的 ``.0``）。

    参数说明:
        value: 数值。

    返回参数:
        str: ``255.0 -> "255"``、``0.92 -> "0.92"``。

    使用示例:
        ``_fmt_num(1.0) == "1"``

    备注信息:
        JSON 里 ``1`` 与 ``1.0`` 是两个不同文本、同一个数。比较前必须统一，
        否则 alpha=1.0 会被当成一次值变更。
    """
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def canonical_color(value: Any) -> str | None:
    """把任意合法写法的颜色归一到 ``rgba(r,g,b,a)``。

    参数说明:
        value: ``#RGB`` / ``#RRGGBB`` / ``#RRGGBBAA`` / ``rgb(...)`` / ``rgba(...)`` /
            DTCG 对象 ``{"colorSpace": "srgb", "components": [...], "alpha": ...}``。

    返回参数:
        str | None: 归一化文本；不认识时返回 ``None``。

    使用示例:
        ``canonical_color("#1C1714EB") == canonical_color("rgba(28,23,20,0.92)")``

    备注信息:
        这是往返保真度的**关键一环**：Tokens Studio 会把 8 位 hex 改写成语义等价的
        ``rgba()``。不做这一步，「只改一个色值」的导出里会冒出几十条假的值变更。
    """
    if isinstance(value, dict):
        components = value.get("components")
        if isinstance(components, list) and len(components) >= 3:
            channels = []
            for item in components[:3]:
                number = float(item)
                # DTCG 的 srgb 分量是 0-1 浮点，越界即按 0-255 处理（编辑器两种都写过）。
                channels.append(number * 255 if 0 <= number <= 1 else number)
            alpha = value.get("alpha", 1)
            alpha = float(alpha) if isinstance(alpha, (int, float)) else 1.0
            return "rgba({},{},{},{})".format(
                *(_fmt_num(round(channel, 3)) for channel in channels), _fmt_num(alpha)
            )
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    hex_match = _HEX_RE.match(text)
    if hex_match:
        digits = hex_match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) == 4:
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) not in (6, 8):
            return None
        red, green, blue = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
        alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return "rgba({},{},{},{})".format(red, green, blue, _fmt_num(round(alpha, 3)))
    rgb_match = _RGB_RE.match(text.replace(" ", ""))
    if rgb_match:
        red, green, blue, alpha = rgb_match.groups()
        alpha_text = _fmt_num(round(_channel(alpha), 3)) if alpha else "1"
        return "rgba({},{},{},{})".format(
            _fmt_num(round(_channel(red), 3)),
            _fmt_num(round(_channel(green), 3)),
            _fmt_num(round(_channel(blue), 3)),
            alpha_text,
        )
    return None


def canonical_dimension(value: Any) -> str | None:
    """把尺寸归一到 ``<数值><单位>``（缺单位按 ``px``）。

    参数说明:
        value: ``"8px"`` / ``8`` / ``{"value": 8, "unit": "px"}``。

    返回参数:
        str | None: 归一化文本；不认识时返回 ``None``。

    使用示例:
        ``canonical_dimension(8) == canonical_dimension("8px") == "8px"``

    备注信息:
        Tokens Studio 的数值型和文本型尺寸在 JSON 里是两种形态，用哪一个取决于
        取色/输入控件的路径，用户在 Figma 里改一个间距就可能悄悄换了形态。
    """
    if isinstance(value, dict):
        number, unit = value.get("value"), value.get("unit", "px")
        if isinstance(number, (int, float)):
            return f"{_fmt_num(float(number))}{unit}"
        return None
    if isinstance(value, (int, float)):
        return f"{_fmt_num(float(value))}px"
    if isinstance(value, str):
        match = _DIM_RE.match(value.strip())
        if match:
            number, unit = match.groups()
            return f"{_fmt_num(float(number))}{unit or 'px'}"
        return value.strip()
    return None


def canonical_family(value: Any) -> str | None:
    """把字体族归一到 ``A, B, C`` 文本。

    参数说明:
        value: 字符串或字符串列表（Tokens Studio 两种都写）。

    返回参数:
        str | None: 归一化文本；不认识时返回 ``None``。

    使用示例:
        ``canonical_family(["Fraunces"]) == canonical_family("Fraunces") == "Fraunces"``

    备注信息:
        只压空格与逗号间距，**不改大小写**：字族名是实物文件名的一部分
        （`Fraunces-Variable.ttf`），大小写错了要当场红，不能悄悄抹平。
    """
    if isinstance(value, str):
        parts = [part.strip().strip("'\"") for part in value.split(",")]
    elif isinstance(value, list):
        parts = [str(part).strip().strip("'\"") for part in value]
    else:
        return None
    return ", ".join(part for part in parts if part)


def colors_close(left: str, right: str) -> bool:
    """判断两个 ``rgba(...)`` 文本是否只是量化误差级别的差异。

    参数说明:
        left: ``canonical_color`` 的输出。
        right: ``canonical_color`` 的输出。

    返回参数:
        bool: 通道差 ≤1、alpha 差 ≤1.5/255 时返回 ``True``。

    使用示例:
        ``colors_close("rgba(28,23,20,0.922)", "rgba(28,23,20,0.92)") is True``

    备注信息:
        Tokens Studio 会把 8 位 hex 改写成语义等价的 ``rgba()``，而这个改写**是有损的**：
        ``#1C1714EB`` 的 alpha 是 235/255≈0.922，编辑器只写两位小数就变成 0.92。
        不留这点容差，仓库里每个半透明遮罩(scrim、阴影)都会在第一次往返时被报成值变更 ——
        噪声一多，人就会把校验器关掉，纪律随之失效。容差只吸收量化误差：
        alpha 差 5/255(约 0.02)这种真改动照样判得出来。
    """
    numbers = []
    for text in (left, right):
        match = re.match(r"^rgba\(([^)]+)\)$", text)
        if not match:
            return False
        numbers.append([float(part) for part in match.group(1).split(",")])
    if len(numbers[0]) != 4 or len(numbers[1]) != 4:
        return False
    channels_ok = all(abs(a - b) <= 1.0 for a, b in zip(numbers[0][:3], numbers[1][:3]))
    return channels_ok and abs(numbers[0][3] - numbers[1][3]) <= 1.5 / 255


def canonical_value(value: Any, kind: str | None) -> str:
    """按类型把一个 token 值转成可比文本。

    参数说明:
        value: 原始值。
        kind: 归一化后的类型名（``color`` / ``dimension`` / ``number`` …），未知时传 ``None``。

    返回参数:
        str: 可比较的规范文本（所有分支都返回字符串，便于统一 diff）。

    使用示例:
        ``canonical_value("#FF9370", "color") == "rgba(255,147,112,1)"``

    备注信息:
        认不出具体类型时退化成「去空白后的原文本」：宁可漏判一次归一化，
        也不要把一次真变更吞掉 —— 前者让人多看一眼，后者会静默改掉设计值。
    """
    if kind == "color":
        normalized = canonical_color(value)
        if normalized is not None:
            return normalized
    elif kind == "dimension":
        normalized = canonical_dimension(value)
        if normalized is not None:
            return normalized
    elif kind == "fontFamily":
        normalized = canonical_family(value)
        if normalized is not None:
            return normalized
    elif kind in {"number", "fontWeight", "duration"}:
        if isinstance(value, (int, float)):
            return _fmt_num(float(value))
        if isinstance(value, str):
            text = value.strip()
            duration = re.match(r"^(-?[0-9]*\.?[0-9]+)\s*(ms|s)?$", text)
            if duration:
                number, unit = duration.groups()
                if unit == "s":
                    return _fmt_num(float(number) * 1000)
                return _fmt_num(float(number))
    elif kind == "shadow" and isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def normalize_type(raw: Any) -> str | None:
    """把类型名归一到仓库使用的 DTCG 类型。

    参数说明:
        raw: 导出物里的 ``$type`` / ``type``，可能是 legacy 别名。

    返回参数:
        str | None: 归一化类型名；缺失时返回 ``None``。

    使用示例:
        ``normalize_type("spacing") == "dimension"``

    备注信息:
        别名表只收「语义确实等价」的（`spacing` / `sizing` / `borderRadius` → `dimension`）。
        把 `border`（复合）也塞进 `dimension` 会掩盖真正的结构变更。
    """
    if not isinstance(raw, str):
        return None
    return TS_TYPE_ALIASES.get(raw, raw)


def alias_target(value: Any) -> str | None:
    """取出「整值就是一个别名引用」时被引用的 token 路径。

    参数说明:
        value: 一个 token 的值。

    返回参数:
        str | None: 形如 ``color.ember.100`` 的目标路径；不是纯别名时返回 ``None``。

    使用示例:
        ``alias_target("{color.ember.100}") == "color.ember.100"``

    备注信息:
        只认**整值**别名。仓库里没有「字符串里嵌别名」的写法（阴影是纯文本），
        所以不做部分替换 —— 那会把 ``0 2px 8px rgba(...)`` 这类值当引用去解析。
    """
    if not isinstance(value, str):
        return None
    match = _ALIAS_RE.match(value.strip())
    return match.group(1) if match else None


def namespace_paths() -> set[str]:
    """仓库四个源文件合并后的 token 路径全集。

    返回参数:
        set[str]: 所有可用于别名解析的路径。

    使用示例:
        ``"color.ember.100" in namespace_paths()``

    备注信息:
        别名是**跨 set** 解析的（``semantic.light.json`` 里的 ``{color.paper.5}``
        指向 ``primitive.color.json``），所以判定命名空间必须取并集而不是只看当前 set。
    """
    paths: set[str] = set()
    for filename in SET_FILES.values():
        path = TOKENS_DIR / filename
        if path.exists():
            paths |= set(flatten(read_json(path)))
    return paths


def suggest_alias(target: str, set_name: str) -> str | None:
    """给一个悬空引用猜出「正确写法」，用于报错提示。

    参数说明:
        target: 导出物里写的引用目标（已剥掉花括号）。
        set_name: 当前校验的 set 名。

    返回参数:
        str | None: 猜到的完整路径；猜不出来返回 ``None``。

    使用示例:
        ``suggest_alias("ember.100", "primitive") == "color.ember.100"``

    备注信息:
        2026-11-28 真实导出物上撞到的形态:Tokens Studio 在「set 根就是 `color` 分组」
        的项目里，把引用写成 **set 内相对路径** ``{ember.100}``，而仓库要求全路径
        ``{color.ember.100}``。这种截断在仓库侧就是**悬空引用**，生成器会 fail-closed，
        所以这里不只是报错，还要把「应该写成什么」直接说出来 —— 否则人只会看到一条
        「别名指向不存在的 token」，不知道是前缀丢了。
    """
    namespace = namespace_paths()
    for head in read_json(TOKENS_DIR / SET_FILES[set_name]):
        if head.startswith("$"):
            continue
        candidate = f"{head}.{target}"
        if candidate in namespace:
            return candidate
    return None


def find_set(doc: dict[str, Any], name: str) -> dict[str, Any] | None:
    """从导出物里取出某个 token set 的子树。

    参数说明:
        doc: 导出物根对象。
        name: set 名（``light`` / ``dark`` / ``primitive`` / ``scale``）。

    返回参数:
        dict | None: 该 set 的子树；导出物里没有这个 set 时返回 ``None``。

    使用示例:
        ``find_set(read_json(path), "light")``

    备注信息:
        两种形态都要认：多 set 单文件（``{"light": {...}, "dark": {...}}``）按顶层键取；
        单 set 文件（整个文档就是 token 树）直接返回根。免费档只能单文件同步，
        两种形态都会遇到，所以这里不做「必须有一种」的硬假设。
    """
    candidate = doc.get(name)
    if isinstance(candidate, dict) and flatten(candidate):
        return candidate
    if flatten(doc) and name in SET_FILES:
        # 单 set 文件：根就是 token 树。此时无法从内容反推 set 名，
        # 由调用方用 --set 指明；这里只在「根确实有 token」时认下来。
        return doc
    return None


def compare(repo: dict[str, dict[str, Any]], export: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """比对一个 set 的仓库版与导出版，把差异分成「值」与「结构」。

    参数说明:
        repo: 仓库版展开结果（来自 ``design/tokens/*.json``）。
        export: 导出版展开结果。

    返回参数:
        tuple: ``(值变更列表, 结构问题描述列表)``。
            值变更每项是 ``{"path", "old", "new", "display_old", "display_new"}``。

    使用示例:
        ``changes, problems = compare(repo, export)``

    备注信息:
        结构问题的口径是**保守**的：路径增删、类型变更、`$description` 变更都算结构，
        且一旦非空就拒绝落盘。理由见模块 docstring —— 结构变更的后果是生成物改形状，
        那不是「改个色值」，必须回到 PR 里被人看见。
    """
    changes: list[dict[str, Any]] = []
    problems: list[str] = []
    repo_paths, export_paths = set(repo), set(export)
    for path in sorted(export_paths - repo_paths):
        problems.append(f"导出物多出 token（仓库没有）:{path}")
    for path in sorted(repo_paths - export_paths):
        problems.append(f"导出物缺少 token（仓库有）:{path}")
    for path in sorted(repo_paths & export_paths):
        repo_token, export_token = repo[path], export[path]
        repo_kind = normalize_type(repo_token["type"])
        export_kind = normalize_type(export_token["type"])
        if repo_kind != export_kind and export_kind is not None:
            problems.append(f"类型变更:{path}  {repo_kind} -> {export_kind}")
            continue
        kind = repo_kind
        old_value = canonical_value(repo_token["value"], kind)
        new_value = canonical_value(export_token["value"], kind)
        equivalent = old_value == new_value or (
            kind == "color" and colors_close(old_value, new_value)
        )
        if not equivalent:
            changes.append(
                {
                    "path": path,
                    "old": repo_token["value"],
                    "new": export_token["value"],
                    "display_old": old_value,
                    "display_new": new_value,
                }
            )
        # 描述只在两边都有、且确实不同时才判结构：Tokens Studio 导出可能整段丢掉
        # description，那是「导出物不完整」，不能倒过来判仓库有错。
        repo_desc = repo_token["description"]
        export_desc = export_token["description"]
        if repo_desc is not None and export_desc is not None and repo_desc != export_desc:
            problems.append(f"描述变更:{path}  {repo_desc!r} -> {export_desc!r}")
    return changes, problems


def detect_eol(raw: bytes) -> str:
    """探测一份文件实际使用的换行符。

    参数说明:
        raw: 文件的原始字节。

    返回参数:
        str: ``"\\r\\n"`` 或 ``"\\n"``（没有换行时按 ``"\\n"``）。

    使用示例:
        ``detect_eol(Path("design/tokens/semantic.light.json").read_bytes())``

    备注信息:
        仓库的 ``.gitattributes`` **刻意不做全局换行归一化**，所以同一目录下 LF 与 CRLF
        并存（本机检出实测：`primitive.color.json` / `scale.json` 是 LF，
        `semantic.light.json` / `semantic.dark.json` 是 CRLF）。落盘若统一成 LF，
        一次改值会把整份文件算成「全部重写」—— 「diff 只落在值上」当场破产。
    """
    return "\r\n" if b"\r\n" in raw else "\n"


def dump_source(doc: dict[str, Any], eol: str = "\n") -> str:
    """按仓库源的排版约定序列化。

    参数说明:
        doc: 一个 token set 的完整对象。
        eol: 行尾符（由 ``detect_eol`` 给出，默认 LF）。

    返回参数:
        str: 文本（缩进 2、叶子 token 单行、按 ``eol`` 收尾、末尾留一个换行）。

    使用示例:
        ``dump_source(read_json(TOKENS_DIR / "semantic.light.json"))``

    备注信息:
        这是本脚本最容易被忽视的一环：直接 ``json.dumps(indent=2)`` 会把单行的叶子
        token 拆成 4 行，一次改值就带来满文件重排 —— 「diff 只落在值上」当场破产。
        自测里钉了「四个源文件读进来再 dump 回去必须字节一致」。
    """
    lines: list[str] = ["{"]

    def emit(node: dict[str, Any], depth: int, last: bool) -> None:
        """递归写一层分组（闭包，仅供 ``dump_source`` 使用）。

        参数说明:
            node: 当前层对象。
            depth: 当前缩进层数。
            last: 是否是父层的最后一项（决定行尾逗号）。

        返回参数:
            无（直接往 ``lines`` 里追加）。

        使用示例:
            ``emit(doc, 1, True)``

        备注信息:
            叶子判定与 ``is_token`` 同口径，保证「读进来怎么分、写回去还怎么分」。
        """
        indent = _INDENT * depth
        items = list(node.items())
        for index, (key, value) in enumerate(items):
            tail = "" if index == len(items) - 1 else ","
            if is_token(value):
                parts = []
                for field in ("value", "type", "description"):
                    raw = token_field(value, field)
                    if raw is None:
                        continue
                    parts.append(f'"${field}": {json.dumps(raw, ensure_ascii=False)}')
                lines.append(f'{indent}{json.dumps(key, ensure_ascii=False)}: {{ {", ".join(parts)} }}{tail}')
            elif isinstance(value, dict):
                lines.append(f'{indent}{json.dumps(key, ensure_ascii=False)}: {{')
                emit(value, depth + 1, index == len(items) - 1)
                lines.append(f"{indent}}}{tail}")
            else:
                lines.append(f'{indent}{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}{tail}')

    emit(doc, 1, True)
    lines.append("}")
    return eol.join(lines) + eol


def set_value(doc: dict[str, Any], path: str, value: Any) -> None:
    """把某个 token 的值写进嵌套对象（保持其余结构与键序不动）。

    参数说明:
        doc: 一个 token set 的完整对象（原地修改）。
        path: 点分 token 路径。
        value: 要写入的新值。

    返回参数:
        无（原地修改）。

    使用示例:
        ``set_value(doc, "color.brand.default", "{color.ember.700}")``

    备注信息:
        只写 ``$value``（或 legacy 的 ``value``），**绝不新建节点**：
        找不到路径就抛 ``KeyError`` 而不是顺手补一个空壳 —— 补空壳等于悄悄改结构。
    """
    *parents, leaf = path.split(".")
    node: Any = doc
    for key in parents:
        node = node[key]
    target = node[leaf]
    if "$value" in target:
        target["$value"] = value
    else:
        target["value"] = value


def apply_changes(set_name: str, changes: list[dict[str, Any]]) -> int:
    """把值变更落盘到 ``design/tokens/`` 里对应的源文件。

    参数说明:
        set_name: set 名。
        changes: ``compare`` 返回的值变更列表。

    返回参数:
        int: 0 = 成功；1 = 落盘失败（源文件结构不符）。

    使用示例:
        ``apply_changes("light", changes)``

    备注信息:
        落盘后**不自动**重生成 Dart/CSS：那一步有它自己的命令与门禁，
        混在一起会让「生成为什么变了」变得不可追。函数只打印下一步该跑什么。
    """
    target_path = TOKENS_DIR / SET_FILES[set_name]
    raw = target_path.read_bytes()
    doc = read_json(target_path)
    for change in changes:
        try:
            set_value(doc, change["path"], change["new"])
        except (KeyError, TypeError) as exc:
            print(f"::error file={rel(target_path)}::无法写入 {change['path']}（源文件结构与导出物对不上）:{exc}")
            return 1
    target_path.write_bytes(dump_source(doc, detect_eol(raw)).encode("utf-8"))
    print(f"已写入 {rel(target_path)}（{len(changes)} 处值变更）")
    print("下一步:python scripts/design_tokens.py --write")
    return 0


def dangling_aliases(changes: list[dict[str, Any]], set_name: str) -> list[tuple[str, str, str | None]]:
    """挑出「值变更把某个值改成了仓库里不存在的引用」的那些。

    参数说明:
        changes: ``compare`` 返回的值变更列表。
        set_name: 当前校验的 set 名（用来猜「完整路径」应为怎么写）。

    返回参数:
        list[tuple]: 每项是 ``(token 路径, 引用目标, 建议的完整路径或 None)``。

    使用示例:
        ``dangling_aliases([{"path": "color.ember.300", "new": "{ember.100}", ...}], "primitive")``

    备注信息:
        为什么值变更还要单独判一次引用：**别名变值也是值变更**，但改成一个解析不了的
        别名不会在 Dart/CSS 生成物里留下任何痕迹（生成器 fail-closed 直接报错），
        而 ``--apply`` 之后本地才会炸 —— 那时人已经以为「只改了个值」。
        2026-11-28 第一次真实导出就撞上了：Tokens Studio 把引用写成 set 内相对路径
        ``{ember.100}``，仓库要求 ``{color.ember.100}``。
    """
    namespace = namespace_paths()
    found: list[tuple[str, str, str | None]] = []
    for change in changes:
        target = alias_target(change["new"])
        if target is not None and target not in namespace:
            found.append((change["path"], target, suggest_alias(target, set_name)))
    return found


def report_set(set_name: str, doc: dict[str, Any], apply: bool) -> int:
    """校验并（可选）落盘一个 set。

    参数说明:
        set_name: set 名。
        doc: 导出物根对象。
        apply: 是否把值变更落盘。

    返回参数:
        int: 0 = 无结构漂移；1 = 有结构漂移或落盘失败；2 = 导出物里没有这个 set。

    使用示例:
        ``report_set("light", read_json(path), apply=False)``

    备注信息:
        结构漂移时即使给了 ``--apply`` 也**不落盘**：先让人把结构问题按 PR 处理干净，
        下一轮再落值。这条是 fail-closed 的落点。
    """
    subset = find_set(doc, set_name)
    if subset is None:
        print(f"::error::导出物里找不到 token set 「{set_name}」（试过顶层键与整文档两种形态）")
        return 2
    repo = flatten(read_json(TOKENS_DIR / SET_FILES[set_name]))
    export = flatten(subset)
    changes, problems = compare(repo, export)
    print(f"=== {set_name}（{rel(TOKENS_DIR / SET_FILES[set_name])}）:仓库 {len(repo)} 个 token,导出 {len(export)} 个 ===")
    if changes:
        print(f"值变更 {len(changes)} 处:")
        for change in changes:
            print(f"  {change['path']}: {change['display_old']} -> {change['display_new']}")
    else:
        print("值变更:无（导出物与仓库完全等价）")
    dangling = dangling_aliases(changes, set_name)
    if dangling:
        print(f"::error::悬空引用 {len(dangling)} 处（新值引用了仓库里不存在的 token,不自动落盘）:")
        for change_path, target, hint in dangling:
            tail = f";正确写法应为 {{{hint}}}" if hint else ""
            print(f"  {change_path} -> {{{target}}}{tail}")
    if problems:
        print(f"::error::结构变更 {len(problems)} 处（必须走 PR 手改,不自动落盘）:")
        for problem in problems:
            print(f"  {problem}")
    if problems or dangling:
        return 1
    if apply and changes:
        return apply_changes(set_name, changes)
    if changes:
        print("提示:加 --apply 可把这些值写入源文件（结构未变,引用可解析,安全）")
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 参数列表（默认取 ``sys.argv[1:]``）。

    返回参数:
        int: 进程退出码（0 / 1 / 2）。

    使用示例:
        ``main(["--export", "tmp/figma-export.json"])``

    备注信息:
        不给 ``--set`` 时,按导出物里实际出现的 set 名逐个校验;给了就只校验那个。
        两种用法对应两种真实场景:一次导出带多 set（多文件同步/手拼),或一次只导一个 set
        （免费档单文件同步的常态）。
    """
    parser = argparse.ArgumentParser(description="Figma 导出物 → 仓库 token 源 的往返校验器")
    parser.add_argument("--export", required=True, help="Tokens Studio 导出的 JSON 路径")
    parser.add_argument("--set", choices=sorted(SET_FILES), help="只校验这一个 set")
    parser.add_argument("--apply", action="store_true", help="把值变更写回 design/tokens/（结构未变时）")
    args = parser.parse_args(argv)
    try:
        doc = read_json(Path(args.export))
    except RoundtripError as exc:
        print(f"::error::{exc}")
        return 2
    names = [args.set] if args.set else [name for name in SET_FILES if isinstance(doc.get(name), dict)]
    if not names:
        print("::error::导出物里没有可识别的 set,请用 --set 指明（light/dark/primitive/scale）")
        return 2
    failed = 0
    for name in names:
        status = report_set(name, doc, args.apply)
        if status == 1:
            failed = 1
        elif status == 2 and args.set:
            return 2
    return failed


if __name__ == "__main__":
    sys.exit(main())
