"""规范正文与 token 源头的**双向**一致性门禁。

设计规范里的色阶表（§3.2）与语义色表（§3.3）是给人读的**产物**，真正的 owner 是
`design/tokens/*.json`。同一份事实两处手写必然分叉 —— 本仓库已经在这件事上过期过五次
（见 `docs/standards/writing.md` §5.1）。所以这里不靠人对照，直接判：

| 方向 | 判据 |
|---|---|
| 表里有、JSON 里没有 | 红（文档承诺了 token 里不存在的值） |
| JSON 里有、表里没有 | 红（新增 token 没进规范，读者看不到） |
| 两边都有但值不同 | 红（最危险：看起来都对，实际两个真理） |

覆盖面**只到色彩**（§3.2 两张色阶 + §3.3 语义表）。间距 / 圆角 / 字阶 / 弹簧在规范里
是散文 + 单值，没有可双向比对的表结构，留给人工评审。

用法（仓库根目录）::

    python scripts/design_spec_sync.py --check

退出码 0 = 一致 / 1 = 有漂移或表读不出来 / 2 = 用法错误。

备注:
    表读不出来一律判红（fail-closed）。规范被挪走、小节标题改名、表格被改坏都属于
    这类 —— 静默跳过等于把门禁关掉。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

# `python scripts/design_spec_sync.py` 时 sys.path[0] 是 scripts/,所以显式把仓库根放进去。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import design_contrast, design_tokens  # noqa: E402  (必须在 sys.path 修好之后)

RAMP_HEADING_RE = re.compile(r"^`(\w+)`（")
SEMANTIC_HEADING = "### 3.3 Semantic 对照表"
MIGRATION_HEADING = "### 18.2 色彩"
HEX_IN_CELL_RE = re.compile(r"`(#[0-9A-Fa-f]{6,8})`")
PERCENT_IN_CELL_RE = re.compile(r"(\d{1,3})\s*%")
HEADER_FIRST_CELL = {"档", "语义", "Semantic", "用途"}
COLOR_TOKEN_PREFIXES = ("surface.", "text.", "border.", "brand.", "accent.", "status.", "overlay.")


def parse_ramps(spec_path: Path) -> dict[str, dict[str, str]]:
    """解析 §3.2 的色阶表。

    参数说明:
        spec_path: 设计规范路径。

    返回参数:
        dict: ``{"ember": {"50": "#FFF0E9", ...}, "paper": {...}}``。

    使用示例:
        ``parse_ramps(find_spec())["ember"]["600"] == "#C93C22"``

    备注信息:
        靠「表头首格是 `档`、数据首格是 `hex`」识别表格,靠表上方那行 `` `ember`（…）``
        识别是哪个色阶。这样加一张新色阶表不用改脚本。
    """
    lines = spec_path.read_text(encoding="utf-8").splitlines()
    ramps: dict[str, dict[str, str]] = {}
    current: str | None = None
    pending_header: list[str] | None = None
    for line in lines:
        stripped = line.strip()
        heading = RAMP_HEADING_RE.match(stripped)
        if heading:
            current = heading.group(1)
            continue
        if not stripped.startswith("|"):
            pending_header = None
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells[0] == "档":
            pending_header = cells
            continue
        if cells[0] == "hex" and pending_header is not None and current:
            steps = pending_header[1:]
            values = cells[1:]
            if len(steps) != len(values):
                raise design_tokens.TokenError(
                    f"{current} 色阶表列数不一致:表头 {len(steps)} 档,数据 {len(values)} 个"
                )
            ramps[current] = {step: value.strip("`") for step, value in zip(steps, values)}
            pending_header = None
            current = None
    if not ramps:
        raise design_tokens.TokenError("§3.2 里一张色阶表都没解析出来(fail-closed)")
    return ramps


def parse_semantic_table(spec_path: Path) -> dict[str, dict[str, Any]]:
    """解析 §3.3 的语义色表。

    参数说明:
        spec_path: 设计规范路径。

    返回参数:
        dict: ``{"surface.page": {"light": ("#FBF7F3", None), "dark": ("#14110F", None)}}``,
        元组第二项是该格声明的透明度百分比(``surface.scrim`` 才有,其余为 ``None``)。

    使用示例:
        ``parse_semantic_table(find_spec())["brand.default"]["light"][0] == "#C93C22"``

    备注信息:
        语义名在表里写成 ``surface.page``(不带 ``color.`` 前缀),比对时补前缀。
        半透明色那一格是 ``#1C1714` @ 92%`` 这种形态,所以 hex 与百分比分别提取。
    """
    lines = spec_path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip().startswith(SEMANTIC_HEADING))
    except StopIteration as exc:
        raise design_tokens.TokenError(f"找不到小节「{SEMANTIC_HEADING}」") from exc

    table: dict[str, dict[str, Any]] = {}
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("##"):
            break
        if not stripped.startswith("|"):
            if table and not stripped:
                continue
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3 or cells[0] in HEADER_FIRST_CELL or set(cells[0]) <= {"-"}:
            continue
        name = cells[0].strip("`")
        if not name or " " in name:
            continue
        sides: dict[str, Any] = {}
        for side, cell in (("light", cells[1]), ("dark", cells[2])):
            hex_match = HEX_IN_CELL_RE.search(cell)
            if not hex_match:
                raise design_tokens.TokenError(f"语义色 {name} 的 {side} 格没有十六进制值:{cell}")
            percent = PERCENT_IN_CELL_RE.search(cell)
            sides[side] = (hex_match.group(1).upper(), int(percent.group(1)) if percent else None)
        table[name] = sides
    if len(table) < 5:
        raise design_tokens.TokenError(f"§3.3 只解析出 {len(table)} 行语义色,表可能被改坏了(fail-closed)")
    return table


def parse_migration_table(spec_path: Path) -> dict[str, tuple[str, str]] | None:
    """解析 §18.2「色彩」迁移表的**新值**列。

    参数说明:
        spec_path: 设计规范路径。

    返回参数:
        dict | None: ``{"brand.default": ("#C93C22", "#FF9370")}``;整节不存在时返回 ``None``。

    使用示例:
        ``parse_migration_table(find_spec())["text.secondary"] == ("#6A5F55", "#C4B9AD")``

    备注信息:
        这一列是给 E-5 迁移时对照用的**副本**,与 §3.3 会重复 → 必须同样被机械校验。
        整节不存在时返回 ``None`` 而不是报错:迁移完成、§18 被删掉是正常归宿,
        不该让门禁因此变红;但只要它还在,就必须判。
        只收映射到**颜色** token 的行(间距 / 圆角 / 字阶那几张表不是色彩事实)。
    """
    lines = spec_path.read_text(encoding="utf-8").splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip().startswith(MIGRATION_HEADING):
            start = index
            break
    if start is None:
        return None

    table: dict[str, tuple[str, str]] = {}
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("###"):
            break
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 4 or set(cells[0]) <= {"-"} or cells[0] in HEADER_FIRST_CELL:
            continue
        target = cells[2].strip("`")
        if not target.startswith(COLOR_TOKEN_PREFIXES):
            continue
        values = HEX_IN_CELL_RE.findall(cells[3])
        if len(values) != 2:
            raise design_tokens.TokenError(
                f"§18.2 的 {target} 一行应给出「浅 / 深」两个色值,实际找到 {values}")
        table[target] = (values[0].upper(), values[1].upper())
    if not table:
        raise design_tokens.TokenError("§18.2 存在但一行颜色迁移都没解析出来(fail-closed)")
    return table


def diff_migration(spec_table: dict[str, tuple[str, str]] | None,
                   light: dict[str, dict[str, Any]],
                   dark: dict[str, dict[str, Any]]) -> list[str]:
    """比对 §18.2 的新值列与真实 token。

    参数说明:
        spec_table: ``parse_migration_table`` 的结果(``None`` 表示该节不存在)。
        light: 浅色模式 token。
        dark: 深色模式 token。

    返回参数:
        list[str]: 问题描述列表(空 = 一致或该节不存在)。

    使用示例:
        ``diff_migration(parse_migration_table(spec), load_mode("light"), load_mode("dark"))``

    备注信息:
        单向即可:§18.2 是**副本**,副本抄错才是问题;token 里新增的语义色由 §3.3 的双向判定兜住。
    """
    if spec_table is None:
        return []
    problems: list[str] = []
    for target, (expected_light, expected_dark) in spec_table.items():
        path = f"color.{target}"
        for mode, tokens, expected in (("light", light, expected_light), ("dark", dark, expected_dark)):
            token = tokens.get(path)
            if token is None:
                problems.append(f"§18.2 引用了不存在的 token:{path}[{mode}]")
                continue
            actual = str(token["value"]).upper()
            if actual != expected:
                problems.append(f"§18.2 的 {target}[{mode}] 与 token 不一致:规范 {expected} / token {actual}")
    return problems


def token_alpha_percent(value: str) -> int | None:
    """取 token 颜色的透明度百分比。

    参数说明:
        value: ``#RRGGBB`` 或 ``#RRGGBBAA``。

    返回参数:
        int | None: 百分比;六位色返回 ``None``。

    使用示例:
        ``token_alpha_percent("#1C1714EB") == 92``

    备注信息:
        四舍五入到整数:规范表里写的是 ``92%``,而 ``0xEB`` 实际是 92.16%。
    """
    digits = value.strip().lstrip("#")
    if len(digits) == 8:
        return round(int(digits[6:8], 16) / 255 * 100)
    return None


def diff_ramps(spec_ramps: dict[str, dict[str, str]], tokens: dict[str, dict[str, Any]]) -> list[str]:
    """比对 §3.2 与 primitive token。

    参数说明:
        spec_ramps: ``parse_ramps`` 的结果。
        tokens: 压平后的 token 表(键形如 ``color.ember.50``)。

    返回参数:
        list[str]: 问题描述列表(空 = 一致)。

    使用示例:
        ``diff_ramps(parse_ramps(find_spec()), design_tokens.flatten(...))``

    备注信息:
        双向:表里有而 token 没有、token 有而表里没有、以及值不同,三种都报。
    """
    problems: list[str] = []
    documented: set[str] = set()
    for ramp_name, steps in spec_ramps.items():
        for step, hex_value in steps.items():
            path = f"color.{ramp_name}.{step}"
            documented.add(path)
            token = tokens.get(path)
            if token is None:
                problems.append(f"§3.2 写了 {ramp_name}.{step} = {hex_value},但 token 里没有 {path}")
                continue
            actual = str(design_tokens.raw_value(token)).upper()
            if actual != hex_value.upper():
                problems.append(f"{path} 不一致:规范 {hex_value} / token {actual}")
    for path in tokens:
        if path.startswith("color.") and path not in documented:
            problems.append(f"token 有 {path} = {design_tokens.raw_value(tokens[path])},但 §3.2 没写它")
    return problems


def diff_semantic(spec_table: dict[str, dict[str, Any]],
                   light: dict[str, dict[str, Any]],
                   dark: dict[str, dict[str, Any]]) -> list[str]:
    """比对 §3.3 与 semantic token(双模式、双向)。

    参数说明:
        spec_table: ``parse_semantic_table`` 的结果。
        light: 浅色模式解析后的 token。
        dark: 深色模式解析后的 token。

    返回参数:
        list[str]: 问题描述列表(空 = 一致)。

    使用示例:
        ``diff_semantic(parse_semantic_table(spec), load_mode("light"), load_mode("dark"))``

    备注信息:
        透明度也判:表里写 ``@ 92%`` 而 token 是不带 alpha 的六位色,同样是漂移。
    """
    problems: list[str] = []
    documented: set[str] = set()
    for name, sides in spec_table.items():
        path = f"color.{name}"
        documented.add(path)
        for mode, tokens in (("light", light), ("dark", dark)):
            token = tokens.get(path)
            if token is None:
                problems.append(f"§3.3 写了 {name},但 {mode} token 里没有 {path}")
                continue
            expected_hex, expected_percent = sides[mode]
            actual = str(token["value"]).upper()
            if actual[:7] != expected_hex[:7]:
                problems.append(f"{path}[{mode}] 色值不一致:规范 {expected_hex} / token {actual}")
                continue
            actual_percent = token_alpha_percent(actual)
            if expected_percent is not None and actual_percent != expected_percent:
                problems.append(
                    f"{path}[{mode}] 透明度不一致:规范 {expected_percent}% / token {actual_percent}%")
            if expected_percent is None and actual_percent is not None:
                problems.append(f"{path}[{mode}] 规范写的是实色,但 token 带了 alpha({actual})")
    for path in {**light, **dark}:
        if path not in documented:
            problems.append(f"token 有 {path},但 §3.3 没写它")
    return problems


def check(spec_path: Path | None = None) -> int:
    """门禁入口。

    参数说明:
        spec_path: 显式指定的规范路径(测试与排查用)。

    返回参数:
        int: 0 = 一致;1 = 有漂移或表读不出来。

    使用示例:
        ``sys.exit(check())``

    备注信息:
        两半(色阶 + 语义)各自 fail-closed:任意一半解析失败都直接判红,不返回「一半通过」。
    """
    try:
        spec = design_contrast.find_spec(spec_path)
        spec_ramps = parse_ramps(spec)
        spec_semantic = parse_semantic_table(spec)
        spec_migration = parse_migration_table(spec)
        primitives = design_tokens.flatten(design_tokens.read_json(design_tokens.PRIMITIVE_SOURCE))
        light, dark = design_tokens.load_mode("light"), design_tokens.load_mode("dark")
        problems = diff_ramps(spec_ramps, primitives)
        problems += diff_semantic(spec_semantic, light, dark)
        problems += diff_migration(spec_migration, light, dark)
    except design_tokens.TokenError as exc:
        print(f"::error::规范与 token 无法比对:{exc}")
        return 1

    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        print(f"::error::共 {len(problems)} 处漂移;改 design/tokens/*.json 后重跑生成器,再同步规范正文")
        return 1
    ramps = sum(len(steps) for steps in spec_ramps.values())
    migration = "n/a" if spec_migration is None else str(len(spec_migration))
    print(f"design_spec_sync: 色阶 {ramps} 档 + 语义 {len(spec_semantic)} 项 × 双模式 + "
          f"迁移表 {migration} 行,与规范正文完全一致")
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
        只提供 ``--check``:同步动作必须由人改文档完成,脚本不替人写规范正文。
    """
    parser = argparse.ArgumentParser(description="规范正文 ↔ token 源头 双向一致性门禁")
    parser.add_argument("--check", action="store_true", required=True, help="跑双向比对")
    parser.add_argument("--spec", type=Path, default=None, help="显式指定规范路径(排查用)")
    args = parser.parse_args(argv)
    return check(args.spec)


if __name__ == "__main__":
    sys.exit(main())
