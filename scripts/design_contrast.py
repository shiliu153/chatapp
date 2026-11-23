"""对比度门禁（「余烬 Ember」§3.4 的机械判定）。

设计规范 §3.4 那张分级表是**阈值的唯一 owner**；本脚本把它读出来，再拿
`design/contrast-pairs.toml` 里声明的配对去撞。因此这里**不写任何阈值常量** ——
想收紧口径就改规范正文，改完门禁立刻跟着变（`TestSpecTableParsed` 钉住这一点）。

两条曲线同时判，因为它们的失效方向不同：

- **WCAG 2.2 比值**是合规底线（AA 4.5 / 非正文 3.0），但对手调灰字过于宽松；
- **APCA Lc** 是感知对比度，按字号/字重分档（正文 75 / 次级 60 / 三级 45 / 按钮 60）。
  实测里「浅灰在暖白上 WCAG 4.5 通过、APCA 只有 30」是常态。

用法（仓库根目录）::

    python scripts/design_contrast.py --check          # 门禁
    python scripts/design_contrast.py --check --verbose  # 逐行打印

退出码 0 = 全部过线 / 1 = 有不过线的配对或口径读不出来 / 2 = 用法错误。

备注:
    规范表读不出来**一律判红**(fail-closed)。真出现这种情况,通常是规范被挪走或
    §3.4 标题改名 —— 静默跳过等于把门禁关掉。
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

# `python scripts/design_contrast.py` 时 sys.path[0] 是 scripts/,所以要显式把仓库根放进去,
# 这样 `from scripts import design_tokens` 两种调用方式(直接跑 / unittest)都成立。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import design_tokens  # noqa: E402  (必须在 sys.path 修好之后)

REPO_ROOT = design_tokens.REPO_ROOT
PAIRS_SOURCE = REPO_ROOT / "design" / "contrast-pairs.toml"

#: 规范的候选位置:生效期间在 specs/,v1.0 之后归档到 archive/specs/,两处都认。
SPEC_CANDIDATES = (
    REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-11-23-ui-redesign-ember-design.md",
    REPO_ROOT / "docs" / "superpowers" / "archive" / "specs" / "2026-11-23-ui-redesign-ember-design.md",
)

SECTION_HEADING = "### 3.4 对比度口径"
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def find_spec(explicit: Path | None = None) -> Path:
    """定位承载 §3.4 分级表的设计规范。

    参数说明:
        explicit: 显式指定的路径(测试与手工排查用)。

    返回参数:
        Path: 已存在的规范文件路径。

    使用示例:
        ``find_spec()``

    备注信息:
        找不到就抛 ``design_tokens.TokenError``:门禁宁可红,也不要「没读到表 = 没违例」。
    """
    if explicit is not None:
        if not explicit.exists():
            raise design_tokens.TokenError(f"指定的规范不存在:{explicit}")
        return explicit
    for candidate in SPEC_CANDIDATES:
        if candidate.exists():
            return candidate
    raise design_tokens.TokenError(
        "找不到 Ember 设计规范(specs/ 与 archive/specs/ 都没有);"
        "门禁无法判定对比度口径,按 fail-closed 判红"
    )


def parse_rules(spec_path: Path) -> dict[str, tuple[float, float]]:
    """从规范 §3.4 的 Markdown 表解析出「标签 -> (WCAG 下限, APCA 下限)」。

    参数说明:
        spec_path: 设计规范文件路径。

    返回参数:
        dict: 行首标签 -> ``(wcag_min, apca_min)``。

    使用示例:
        ``parse_rules(find_spec())["正文"] == (4.5, 75.0)``

    备注信息:
        只认四列形态 ``| 用途 | 字号/字重 | WCAG | APCA |``;行首标签保留原文,
        匹配时用前缀比对,所以 ``三级`` 能命中 ``三级（时间戳）``。
    """
    text = spec_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip().startswith(SECTION_HEADING))
    except StopIteration as exc:
        raise design_tokens.TokenError(f"{spec_path.name} 里找不到小节「{SECTION_HEADING}」") from exc

    rules: dict[str, tuple[float, float]] = {}
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if not stripped.startswith("|"):
            if rules and stripped == "":
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 4 or set(cells[0]) <= {"-", " "} or cells[0] == "用途":
            continue
        wcag_match = NUMBER_RE.search(cells[2])
        apca_match = NUMBER_RE.search(cells[3])
        if not wcag_match or not apca_match:
            continue
        rules[cells[0]] = (float(wcag_match.group()), float(apca_match.group()))

    if len(rules) < 3:
        raise design_tokens.TokenError(
            f"{spec_path.name} §3.4 只解析出 {len(rules)} 行,表可能被改坏了(fail-closed)"
        )
    return rules


def load_pairs(path: Path | None = None) -> list[dict[str, str]]:
    """读取配对声明。

    参数说明:
        path: 配对表路径(默认 ``design/contrast-pairs.toml``)。

    返回参数:
        list[dict]: 每项含 ``name`` / ``rule`` / ``fg`` / ``bg``。

    使用示例:
        ``load_pairs()[0]["rule"] == "正文"``

    备注信息:
        缺字段或配对表为空都抛 ``TokenError``;配对表是「撞哪两个 」的唯一 owner。
    """
    target = path or PAIRS_SOURCE
    if not target.exists():
        raise design_tokens.TokenError(f"缺少配对表:{design_tokens.rel(target)}")
    data = tomllib.loads(target.read_text(encoding="utf-8"))
    pairs = data.get("pair") or []
    if not pairs:
        raise design_tokens.TokenError("配对表里没有任何 [[pair]]")
    for pair in pairs:
        for field in ("name", "rule", "fg", "bg"):
            if not pair.get(field):
                raise design_tokens.TokenError(f"配对缺字段 {field}:{pair}")
    return pairs


def srgb_to_linear(channel: int) -> float:
    """把 0–255 的 sRGB 分量线性化。

    参数说明:
        channel: 0–255 的整数分量。

    返回参数:
        float: 线性化后的 0–1 分量。

    使用示例:
        ``srgb_to_linear(255) == 1.0``

    备注信息:
        按 WCAG 的分段公式(阈值 0.04045),与 APCA 的简化 2.4 幂不同,所以两条曲线分开算。
    """
    value = channel / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def parse_hex(color: str) -> tuple[int, int, int]:
    """把 ``#RGB`` / ``#RRGGBB`` / ``#RRGGBBAA`` 解析成 RGB 三元组。

    参数说明:
        color: CSS 十六进制颜色。

    返回参数:
        tuple[int, int, int]: ``(r, g, b)``,各 0–255。

    使用示例:
        ``parse_hex("#1C1714EB") == (0x1C, 0x17, 0x14)``

    备注信息:
        alpha 在这里被丢弃:对比度判定假设是实底。半透明遮罩上的文字要用
        「叠底后的实际颜色」登记配对,不能直接拿带 alpha 的值来算。
    """
    digits = color.strip().lstrip("#")
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    if len(digits) not in (6, 8):
        raise design_tokens.TokenError(f"不支持的颜色写法:{color}")
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def relative_luminance(color: str) -> float:
    """算 WCAG 相对亮度。

    参数说明:
        color: CSS 十六进制颜色。

    返回参数:
        float: 0–1 的相对亮度。

    使用示例:
        ``relative_luminance("#FFFFFF") == 1.0``

    备注信息:
        系数取 WCAG 2.x 的 0.2126 / 0.7152 / 0.0722。
    """
    red, green, blue = parse_hex(color)
    return 0.2126 * srgb_to_linear(red) + 0.7152 * srgb_to_linear(green) + 0.0722 * srgb_to_linear(blue)


def wcag_ratio(foreground: str, background: str) -> float:
    """算 WCAG 对比度比值。

    参数说明:
        foreground: 前景色。
        background: 背景色。

    返回参数:
        float: 1–21 的比值。

    使用示例:
        ``wcag_ratio("#000000", "#FFFFFF") == 21.0``

    备注信息:
        顺序无关(取亮的那一方做分子)。
    """
    first, second = relative_luminance(foreground), relative_luminance(background)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


def apca_y(color: str) -> float:
    """算 APCA 的简化亮度 Y。

    参数说明:
        color: CSS 十六进制颜色。

    返回参数:
        float: APCA 亮度。

    使用示例:
        ``apca_y("#FFFFFF")``

    备注信息:
        APCA 0.98G-4g 用 2.4 幂直接作用在 sRGB 编码值上,不做 WCAG 的分段线性化。
    """
    red, green, blue = parse_hex(color)
    return (0.2126729 * (red / 255.0) ** 2.4
            + 0.7151522 * (green / 255.0) ** 2.4
            + 0.0721750 * (blue / 255.0) ** 2.4)


def apca_lc(foreground: str, background: str) -> float:
    """算 APCA 的感知对比度 Lc。

    参数说明:
        foreground: 前景色。
        background: 背景色。

    返回参数:
        float: ``-108..106`` 区间的 Lc 值;``|Lc|`` 小于 7.5 时归零(视为无对比)。

    使用示例:
        ``abs(apca_lc("#1C1714", "#FBF7F3")) > 100``

    备注信息:
        极性不同公式不同(深字浅底 / 浅字深底),两段都做黑位软钳制,
        否则近黑背景上的深字会被算出虚高的对比。
    """
    text_y, back_y = apca_y(foreground), apca_y(background)
    if text_y < 0.022:
        text_y += (0.022 - text_y) ** 1.414
    if back_y < 0.022:
        back_y += (0.022 - back_y) ** 1.414
    if abs(back_y - text_y) < 0.0005:
        return 0.0
    if back_y > text_y:
        sapc = (back_y ** 0.56 - text_y ** 0.57) * 1.14
    else:
        sapc = (back_y ** 0.65 - text_y ** 0.62) * 1.14
    scaled = 0.0 if abs(sapc) < 0.1 else sapc * 100
    return 0.0 if abs(scaled) < 7.5 else scaled


def rule_for(label: str, rules: dict[str, tuple[float, float]]) -> tuple[float, float]:
    """按行首标签前缀找阈值。

    参数说明:
        label: 配对表里的 ``rule``。
        rules: ``parse_rules`` 的结果。

    返回参数:
        tuple[float, float]: ``(wcag_min, apca_min)``。

    使用示例:
        ``rule_for("三级", rules)``

    备注信息:
        匹配不上就抛错:说明配对表引用了规范里不存在的一档,阈值无从判定。
    """
    for name, limits in rules.items():
        if name.startswith(label):
            return limits
    raise design_tokens.TokenError(
        f"配对表的 rule「{label}」在规范 §3.4 里找不到对应行(现有:{'、'.join(rules)})"
    )


def evaluate(spec_path: Path | None = None, pairs_path: Path | None = None) -> list[dict[str, object]]:
    """跑完两种模式的全部配对。

    参数说明:
        spec_path: 规范路径(默认自动定位)。
        pairs_path: 配对表路径(默认仓库内那份)。

    返回参数:
        list[dict]: 每项含 ``mode`` / ``name`` / ``wcag`` / ``apca`` / ``limits`` / ``ok``。

    使用示例:
        ``[row for row in evaluate() if not row["ok"]]``

    备注信息:
        任何一档口径读不出来都会抛 ``TokenError``,不会返回「空结果 = 通过」。
    """
    spec = find_spec(spec_path)
    rules = parse_rules(spec)
    pairs = load_pairs(pairs_path)
    results: list[dict[str, object]] = []
    for mode in ("light", "dark"):
        tokens = design_tokens.load_mode(mode)
        for pair in pairs:
            limits = rule_for(pair["rule"], rules)
            fg = str(tokens[pair["fg"]]["value"])
            bg = str(tokens[pair["bg"]]["value"])
            ratio = wcag_ratio(fg, bg)
            lc = abs(apca_lc(fg, bg))
            results.append({
                "mode": mode,
                "name": pair["name"],
                "fg": fg,
                "bg": bg,
                "wcag": ratio,
                "apca": lc,
                "limits": limits,
                "ok": ratio >= limits[0] and lc >= limits[1],
            })
    return results


def check(verbose: bool = False, spec_path: Path | None = None, pairs_path: Path | None = None) -> int:
    """门禁入口:打印结论并以退出码表达。

    参数说明:
        verbose: 是否逐行打印全部配对(默认只打印失败项与汇总)。
        spec_path: 规范路径(默认自动定位)。
        pairs_path: 配对表路径(默认仓库内那份)。

    返回参数:
        int: 0 = 全部过线;1 = 有不过线或有口径错。

    使用示例:
        ``sys.exit(check())``

    备注信息:
        失败行按 ``模式 | 配对 | 实测/下限`` 打印,并给出可执行的修法(改哪个 token)。
    """
    try:
        results = evaluate(spec_path, pairs_path)
    except design_tokens.TokenError as exc:
        print(f"::error::对比度口径不可用:{exc}")
        return 1

    failures = [row for row in results if not row["ok"]]
    for row in results:
        wcag_min, apca_min = row["limits"]
        if verbose or not row["ok"]:
            verdict = "PASS" if row["ok"] else "FAIL"
            print(f"[{verdict}] {row['mode']:5s} | {row['name']:22s} | "
                  f"WCAG {row['wcag']:.2f}/{wcag_min:.1f} | APCA {row['apca']:.1f}/{apca_min:.1f} | "
                  f"{row['fg']} on {row['bg']}")
    if failures:
        print(f"::error::对比度有 {len(failures)} 处不过线;改 design/tokens/semantic.*.json 里对应的 token")
        return 1
    print(f"design_contrast: {len(results)} 组配对全部过线(双模式)")
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
        只提供 ``--check``:本门禁不生成任何东西,写文件反而是它不该有的能力。
    """
    parser = argparse.ArgumentParser(description="对比度门禁（余烬 Ember §3.4）")
    parser.add_argument("--check", action="store_true", required=True, help="跑双模式全部配对")
    parser.add_argument("--verbose", action="store_true", help="逐行打印全部配对")
    parser.add_argument("--spec", type=Path, default=None, help="显式指定规范路径(排查用)")
    parser.add_argument("--pairs", type=Path, default=None, help="显式指定配对表(排查用)")
    args = parser.parse_args(argv)
    return check(verbose=args.verbose, spec_path=args.spec, pairs_path=args.pairs)


if __name__ == "__main__":
    sys.exit(main())
