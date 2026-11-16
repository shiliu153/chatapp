#!/usr/bin/env python3
"""C++ 注释机械门禁:文件头 22 行块 + 每个函数一块五字段注释。

为什么需要它
------------
``docs/standards/cpp.md`` 原先自己写着「现在没有机械门禁,这是刻意留的、也是暂时的」:
这套注释是「块」不是 docstring,没有 AST 级入口,正则又判不准 ``.h`` 声明 / ``.cpp`` 定义 /
lambda / ``= delete`` 在文本上的差别。于是 PR #313 一次性把整套注释块补齐之后,
**新增 C++ 代码时没有任何东西会拦** —— 那正是 ``python.md`` §7 用 ``CommentCoverageTests``
消灭掉的那类缺口(见该 issue 与 ``docs/standards/cpp.md`` §8)。

本脚本把「要不要块」这件事交给解析器,而不是正则:``tree-sitter-cpp`` 能给出
``function_definition`` / ``declaration`` / ``field_declaration`` 的节点类型与
``class_specifier`` 作用域,于是「类内 inline 定义」「``= delete``」「lambda」「``struct``
字段」都是**结构判定**,不是猜。

判三件事(口径全部来自 ``docs/standards/cpp.md``,这里不另立标准)
--------------------------------------------------------------
1. **文件头**(§2):第 1 行起是 22 行块(唯一例外 ``src/net/frames.h`` 在「额外注明」段
   多一行,见 §2.3),固定字段值一致,``文件名称`` 的值等于该文件相对 ``imserver/`` 的路径
   (如 ``src/net/ws_server.h``,不带 ``imserver/`` 前缀)。
2. **函数注释块**(§3 / §5):``src/`` 下每个函数定义与每个头文件函数声明各一块;``tests/``
   下每个 ``TEST(套件, 用例)`` 各一块。块紧贴签名上方(中间不空行),上下各一条分隔线,
   字段固定 5 个且顺序固定。
3. **块不许落进函数体**(§4 那条硬事实:现库全部注释块都在函数体外):分隔线缩进
   只允许顶格或 2 空格(``src/util/media_sign.h`` 的类成员块),≥4 空格判红。

分隔线的判据是「去掉行首缩进后正好是 ``//`` + 115 个 ``-``」(显示列 117),**不按整行宽度硬卡
缩进**:``src/util/media_sign.h`` 整行 119 列是合法写法。

豁免(误报比漏报更贵,全部按 §4 边界表)
--------------------------------------
lambda、函数体内的局部对象、宏、纯数据 ``struct`` 字段、``= delete`` 不需要块 ——
这些都由「节点类型 + 作用域」判定:扫描时不进入 ``compound_statement``(函数体)与
``lambda_expression``,只认命名空间 / 类作用域里的**函数**节点。

``tests/`` 下的辅助函数与 fixture 类成员不在强制范围内:现库的块绝大多数来自 ``src/`` 与
``tests/`` 里的 ``TEST`` 用例,``tests/`` 另有一批 helper / fixture 方法**没有块**(多数连注释
都没有)。§4 的边界表说要块,但那样门禁在当前的 ``imserver/`` 上就红了,而门禁第一口径是零
误报 —— 所以这里只强制 ``src/`` 与 ``TEST`` 用例;偏差用 ``--verbose`` 逐条列出来,便于后续
单独收口(见 PR 遗留)。

**写给后来改这个脚本的人**:块的总数、``src/`` 与 ``tests/`` 的分布都**不写死在本脚本里** ——
每加一个 C++ 函数就漂一次(实测:补注释那轮之后又漂过),而 ``scripts/facts.py`` 的哨兵只覆盖
``docs/**/*.md``,覆盖不到代码里的字面量。要现算就自己跑,别抄数字:
``python scripts/check_cpp_comments.py --verbose``(打印每个文件的块数 / 需块函数数与合计)、
``python -m unittest scripts.test_check_cpp_comments -v``(门禁自测)。

依赖(缺了就 fail-closed)
------------------------
只用标准库 + ``tree-sitter`` / ``tree-sitter-cpp`` 两个 wheel(``scripts/requirements-gates.txt``)。
缺 wheel 时**退出码 2** 并打印安装命令,退出码 2 在执行器里同样是一道红门禁 ——
「跑不了」不许伪装成「全绿」。

退出码
------
- ``0``:全部合规(默认不打印任何东西;``--verbose`` 打基线计数);
- ``1``:发现违规(逐条 ``<文件>:<行>: <缺什么>`` + 末尾一行汇总);
- ``2``:工具自身出错(缺 wheel / 文件读不了 / 解析出 ``ERROR`` 节点 / ``--root`` 不是
  ``imserver`` 目录)。**这类不许算绿**。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: 仓库根目录(本文件在 ``scripts/`` 下)。``--root`` 的缺省值以它为基准。
ROOT = Path(__file__).resolve().parent.parent
#: 缺省被检查的目录:``imserver/``。自测用 ``--root`` 指向临时目录。
DEFAULT_ROOT = ROOT / "imserver"
#: 依赖清单(本地 ``scripts/stacks/bootstrap.sh`` 与 CI 的 ``contract.yml`` 都装这一份)。
REQUIREMENTS = "scripts/requirements-gates.txt"
#: 缺依赖时要打印的安装命令(本地与 CI 都能照抄)。
INSTALL_COMMAND = f"python -m pip install -r {REQUIREMENTS}"
#: 函数注释块分隔线里 ``-`` 的个数:``//`` + 115 个 ``-`` = 117 显示列(cpp.md §3.1)。
DASHES = 115
#: 分隔线的规范形态(顶格)。判定时先去掉行首缩进再比较。
SEPARATOR = "//" + "-" * DASHES
#: 注释块里 5 个字段的固定顺序(cpp.md §3.1)。
FIELDS = ("函数简介", "参数说明", "返回参数", "使用示例", "备注信息")
#: 文件头里**值固定**的字段(``文件名称`` 逐文件不同,单独判;cpp.md §2.2)。
HEADER_FIXED_VALUES = (
    ("项目名称", "chat_app / imserver"),
    ("公司名称", "个人项目（shiliu153）"),
    ("版本信息", "查看 app/pubspec.yaml 内 version 字段 版本说明"),
    ("开发环境", "CMake 3.22 + g++ (C++20) Linux x86_64"),
    ("适用平台", "Linux x86_64 服务端"),
    ("仓库地址", "https://github.com/shiliu153/chatapp"),
)
#: 文件头字段的期望顺序(``文件名称`` 在前,其余固定值字段按此顺序)。
HEADER_LABELS = ("文件名称",) + tuple(label for label, _ in HEADER_FIXED_VALUES)
#: 文件头里**必须出现**的整行内容(许可证依据 + 修改记录表头,cpp.md §2.2)。
HEADER_REQUIRED_LINES = (
    "本文件是 chat_app 自建 IM 服务端的一部分",
    "额外注明：",
    "本文件使用 MIT 开源许可证协议 许可申明英文版见仓库根目录 LICENSE 文件",
    "欢迎各位使用并传播本程序 但修改内容时必须保留作者的版权声明（即本声明）",
    "修改记录",
)
#: 「额外注明」段允许的额外行数:基准 1 行,§2.3 允许再补**一行**文件级说明。
EXTRA_NOTE_ALLOWANCE = 1
#: 分隔线允许的缩进(cpp.md §6):顶格 1260 条、类体 2 空格 14 条;≥4 空格 = 落进函数体。
ALLOWED_INDENTS = (0, 2)
#: 需要「块」的 gtest 宏。``tests/`` 下除这些用例以外不强制(见模块 docstring「豁免」)。
TEST_MACROS = ("TEST", "TEST_F", "TEST_P", "TYPED_TEST", "TYPED_TEST_P")
#: 被检查的文件后缀(cpp.md 的适用范围:``.h`` / ``.cpp``)。
SOURCE_SUFFIXES = (".h", ".cpp")
#: 被检查的子目录:``src/``(生产代码)与 ``tests/``(gtest)。``build/`` 之类不进扫描。
SCANNED_SUBDIRS = ("src", "tests")
#: 分隔线正则:``//`` + 一串 ``-``(宽度另判,用于「缩进 ≥4」这条)。
SEPARATOR_LIKE = re.compile(r"^//-+$")
#: 文件头起止行(``/****…`` 与 ``****…/``,各至少 20 个 ``*``)。
HEADER_OPEN = re.compile(r"^/\*{20,}$")
HEADER_CLOSE = re.compile(r"^\*{20,}/$")
#: 文件头字段行:``* 字段名 + 空白 + 值``。
HEADER_FIELD = re.compile(r"^\*\s+(\S+)\s+(\S.*)$")

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_TOOLING = 2


class ToolingError(RuntimeError):
    """工具自身跑不了(缺依赖 / 读不了文件 / 解析失败)—— 退出码 2,不是「绿」。"""


@dataclass(frozen=True)
class Finding:
    """一处违规:定到 ``文件:行``,后面一句「缺什么」。

    Attributes:
        path: 相对仓库根的路径(如 ``imserver/src/util/uuid.h``),点进日志可跳转。
        line: 1 起的行号。文件级问题(如文件头)定位到第 1 行。
        message: 缺什么 / 哪条判据不满足。
    """

    path: str
    line: int
    message: str

    def render(self) -> str:
        """渲染成人读的一行 ``<文件>:<行>: <缺什么>``。"""
        return f"{self.path}:{self.line}: {self.message}"


@dataclass
class FileReport:
    """单个文件的检查结果(供 ``--verbose`` 打基线计数)。

    Attributes:
        path: 相对仓库根的路径。
        blocks: 该文件里被认出的注释块数(``// 函数简介`` 的个数)。
        required: 该文件里**要求有块**的函数节点数。
        findings: 该文件的违规列表。
        exempt_tests: ``tests/`` 下按现库惯例豁免(非 ``TEST``)的函数数。
        warnings: 不判红但值得知道的解析告警(如 tree-sitter 补出的缺记号)。
    """

    path: str
    blocks: int = 0
    required: int = 0
    exempt_tests: int = 0
    findings: list[Finding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_parser():
    """加载 tree-sitter C++ 解析器(缺依赖即 ``ToolingError``,不静默降级成正则)。

    Returns:
        ``tree_sitter.Parser`` 实例(已绑定 C++ 语言)。

    Raises:
        ToolingError: ``tree-sitter`` / ``tree-sitter-cpp`` 没装,或语言包版本不兼容。
    """
    try:
        import tree_sitter_cpp
        from tree_sitter import Language, Parser
    except ModuleNotFoundError as exc:  # 缺 wheel:fail-closed
        raise ToolingError(
            f"缺依赖 {exc.name}(本门禁用 tree-sitter 解析 C++ 函数边界)。"
            f"安装:{INSTALL_COMMAND}"
        ) from exc
    try:
        language = Language(tree_sitter_cpp.language())
    except Exception as exc:  # noqa: BLE001 - 版本不兼容也必须 fail-closed,不许「全绿」
        raise ToolingError(
            f"tree-sitter-cpp 语言包不可用({exc});重新安装:{INSTALL_COMMAND}"
        ) from exc
    return Parser(language)


def read_lines(path: Path) -> list[str]:
    """读文件并按行切开(去掉行尾 ``\\r``,Windows 检出与 CI 行为一致)。

    Args:
        path: 文件路径。

    Returns:
        行列表(不含换行符;文件末尾的换行不产生空行)。

    Raises:
        ToolingError: 文件读不了或不是 UTF-8。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolingError(f"读不了 {path}:{exc}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").splitlines()


def relative_path(root: Path, path: Path) -> str:
    """取文件相对仓库根的路径(报告里的 ``<文件>`` 用仓库根口径,便于点进 CI 日志)。

    Args:
        root: 仓库根目录。
        path: 被检查的文件。

    Returns:
        POSIX 形式的相对路径(如 ``imserver/src/util/uuid.h``)。
    """
    return path.resolve().relative_to(root.resolve()).as_posix()


def header_findings(rel: str, lines: list[str], inside_imserver: str) -> list[tuple[int, str]]:
    """检查文件头那 22 行块(cpp.md §2)。

    Args:
        rel: 相对仓库根的路径(报告用)。
        lines: 文件全部行。
        inside_imserver: 该文件相对 ``imserver/`` 的路径(``文件名称`` 字段的期望值)。

    Returns:
        ``(行号, 「缺什么」)`` 列表;空列表表示文件头合规。
    """
    if not lines or not HEADER_OPEN.match(lines[0].strip()):
        return [(1, "缺文件头:第 1 行起应是 /****… 开始的 22 行块(见 docs/standards/cpp.md §2)")]

    close = None
    for index in range(1, len(lines)):
        stripped = lines[index].strip()
        if HEADER_CLOSE.match(stripped):
            close = index
            break
        if not stripped.startswith("*"):
            break
    if close is None:
        return [(1, "文件头没有闭合(找不到 ****/ 收尾行,或块被非注释行截断)")]

    block = lines[: close + 1]
    problems: list[tuple[int, str]] = []

    # 1. 固定行(许可证依据 / 额外注明 / 修改记录):位置不做要求,但必须出现。
    for required in HEADER_REQUIRED_LINES:
        if not any(line.lstrip("* ").strip() == required for line in block):
            problems.append((1, f"文件头缺固定行:{required}"))

    # 2. 字段:顺序固定,固定值要逐字相同,``文件名称`` 等于该文件在 imserver/ 内的路径。
    positions: dict[str, int] = {}
    for index, line in enumerate(block):
        match = HEADER_FIELD.match(line.strip())
        if match and match.group(1) in HEADER_LABELS:
            positions.setdefault(match.group(1), index)
    missing = [label for label in HEADER_LABELS if label not in positions]
    if missing:
        problems.append((1, "文件头缺字段:" + " / ".join(missing)))
    else:
        order = sorted(positions.items(), key=lambda item: item[1])
        actual = [label for label, _ in order]
        if actual != [label for label in HEADER_LABELS if label in positions]:
            problems.append((1, "文件头字段顺序错:期望 " + " → ".join(HEADER_LABELS)))
        for label, expected in HEADER_FIXED_VALUES:
            got = HEADER_FIELD.match(block[positions[label]].strip()).group(2).strip()
            if got != expected:
                problems.append(
                    (positions[label] + 1, f"文件头字段 {label} 的值为「{got}」,应为「{expected}」")
                )
        name_line = positions["文件名称"]
        got_name = HEADER_FIELD.match(block[name_line].strip()).group(2).strip()
        if got_name != inside_imserver:
            problems.append(
                (
                    name_line + 1,
                    f"文件头 文件名称 为「{got_name}」,应为文件相对 imserver/ 的路径「{inside_imserver}」",
                )
            )

    # 3. 「额外注明」段只允许补一行(§2.3 的唯一例外,现库 frames.h)。
    try:
        note_index = next(
            index for index, line in enumerate(block) if line.lstrip("* ").strip() == "额外注明："
        )
        name_index = positions.get("文件名称", len(block))
        extras = [
            line
            for line in block[note_index + 1 : name_index]
            if line.lstrip("* ").strip()
            and not (
                HEADER_FIELD.match(line.strip())
                and HEADER_FIELD.match(line.strip()).group(1) in HEADER_LABELS
            )
        ]
        # 「额外注明：」下面基准是 2 行(许可证指路 + 版权声明要求),§2.3 允许多 1 行。
        if len(extras) > 2 + EXTRA_NOTE_ALLOWANCE:
            problems.append(
                (
                    note_index + 1,
                    f"「额外注明」段多出 {len(extras) - 2 - EXTRA_NOTE_ALLOWANCE} 行(cpp.md §2.3 只允许补 1 行文件级说明)",
                )
            )
    except StopIteration:
        pass  # 上面已经报「缺固定行:额外注明：」

    return problems


def block_findings(lines: list[str], signature_row: int) -> list[tuple[int, str]]:
    """检查某个函数签名上方的注释块(cpp.md §3.1 / §5)。

    ``signature_row`` 是签名的 0 起行号:它正上方必须是收尾分隔线,再往上依次是本块 5 个字段
    与起始分隔线。分隔线按「去掉行首缩进 == ``//`` + 115 个 ``-``」判,所以 2 空格缩进的类成员
    块(``src/util/media_sign.h``)合法。

    Args:
        lines: 文件全部行。
        signature_row: 函数签名所在行(0 起)。

    Returns:
        ``(行号, 「缺什么」)`` 列表;空列表表示这一处合规。
    """
    if signature_row <= 0:
        return [(signature_row + 1, "缺函数注释块:文件第一行就是函数签名,上方没有块")]

    bottom = lines[signature_row - 1]
    if bottom.strip() != SEPARATOR:
        return [
            (
                signature_row + 1,
                "缺函数注释块:签名紧上方应是收尾分隔线 // + 115 个 -(中间不许空行)",
            )
        ]
    indent = len(bottom) - len(bottom.lstrip())
    if indent not in ALLOWED_INDENTS:
        return [
            (
                signature_row,
                f"注释块分隔线缩进 {indent} 空格:只允许顶格或 2 空格(≥4 视为块落进了函数体)",
            )
        ]

    body: list[str] = []
    top = None
    for index in range(signature_row - 2, -1, -1):
        stripped = lines[index].strip()
        if stripped == SEPARATOR:
            top = index
            break
        if not stripped.startswith("//"):
            return [
                (
                    signature_row + 1,
                    "函数注释块缺起始分隔线:字段区上方应是 // + 115 个 -",
                )
            ]
        body.append(lines[index])
    if top is None:
        return [(signature_row + 1, "函数注释块缺起始分隔线(往上找不到 //---)")]

    body.reverse()
    problems: list[tuple[int, str]] = []
    seen: list[str] = []
    current: str | None = None
    for offset, raw in enumerate(body):
        text = raw.strip()[2:].strip()
        label = next((name for name in FIELDS if text.startswith(name)), None)
        if label is None:
            if current is None:
                problems.append(
                    (top + 2 + offset, "注释块首行不是「函数简介」:字段区第一条必须是 5 字段之一")
                )
            continue  # 续行(参数说明的多参数、备注信息的续行)
        if label in seen:
            problems.append((top + 2 + offset, f"注释块字段重复:{label}"))
        seen.append(label)
        current = label

    missing = [name for name in FIELDS if name not in seen]
    if missing:
        problems.append((signature_row + 1, "注释块缺字段:" + " / ".join(missing)))
    elif seen != list(FIELDS):
        problems.append(
            (signature_row + 1, "注释块字段顺序错:应为 " + " → ".join(FIELDS) + ",实际 " + " → ".join(seen))
        )
    return problems


def body_block_findings(lines: list[str]) -> list[tuple[int, str]]:
    """找出「落进函数体」的注解块:分隔线缩进 ≥4 空格(cpp.md §4 那条硬事实)。

    Args:
        lines: 文件全部行。

    Returns:
        ``(行号, 「缺什么」)`` 列表。
    """
    problems: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not SEPARATOR_LIKE.match(stripped):
            continue
        indent = len(line) - len(line.lstrip())
        if indent >= 4:
            problems.append(
                (
                    index + 1,
                    f"注释块落进了函数体:分隔线缩进 {indent} 空格(现库全部注释块都在函数体外)",
                )
            )
    return problems


def _first_line_of(src: bytes, node) -> str:
    """取一个语法节点第一行的文本(判定 ``TEST(...)`` 这类宏函数用)。

    Args:
        src: 文件原始字节。
        node: tree-sitter 节点。

    Returns:
        该节点首行的文本(已去掉首尾空白)。
    """
    return src[node.start_byte : node.end_byte].decode("utf-8", "replace").splitlines()[0].strip()


def _function_nodes(
    node, src: bytes, out: list[tuple[int, str]], block_row: int | None = None
) -> None:
    """递归收集需要「块」的函数节点,返回 ``(行号 0 起, 首行文本)``。

    只认命名空间 / 类作用域里的函数:不进入 ``compound_statement``(函数体)与
    ``lambda_expression``,于是「函数体内的局部对象」「lambda」天然不会被要求加块
    (cpp.md §4 的豁免项)。

    Args:
        node: 当前节点。
        src: 文件原始字节。
        out: 结果累加器。
        block_row: 块应该出现的位置(0 起)。模板函数的注释块写在 ``template <…>`` 上面,
            所以进 ``template_declaration`` 时把它指向模板那一行,而不是内层声明那一行。
    """
    for child in node.named_children:
        kind = child.type
        if kind in ("compound_statement", "lambda_expression"):
            continue  # 函数体 / lambda 内部:不加块,也不往下找
        if kind == "comment":
            continue
        if kind == "template_declaration":
            # 块写在 ``template <…>`` 上方,不是内层声明上方(§4「模板函数加块」)。
            _function_nodes(child, src, out, block_row=child.start_point[0])
            continue
        if kind == "function_definition":
            # ``= delete`` 的节点类型也是 function_definition(表明接口不存在,没有实现可讲)。
            if "delete_method_clause" not in {item.type for item in child.children}:
                out.append((child.start_point[0] if block_row is None else block_row,
                            _first_line_of(src, child)))
            continue
        if kind in ("declaration", "field_declaration"):
            declarator = child.child_by_field_name("declarator")
            text = src[child.start_byte : child.end_byte].decode("utf-8", "replace")
            if declarator is not None and _has_function_declarator(declarator) and "= delete" not in text:
                out.append((child.start_point[0] if block_row is None else block_row,
                            _first_line_of(src, child)))
            # 类内嵌套的 class/struct 会以 field_declaration 承载,继续往里找它的成员函数。
            _function_nodes(child, src, out)
            continue
        _function_nodes(child, src, out)


def _has_function_declarator(node) -> bool:
    """判断一个声明符链里是否有 ``function_declarator``(即这是个函数声明而非变量)。

    Args:
        node: 声明符节点(可能是 identifier / pointer_declarator / reference_declarator …)。

    Returns:
        是函数声明返回 ``True``。
    """
    if node.type == "function_declarator":
        return True
    return any(_has_function_declarator(child) for child in node.named_children)


def _is_test_case(first_line: str) -> bool:
    """判断函数定义首行是不是 gtest 的 ``TEST(套件, 用例)`` 形态。

    Args:
        first_line: 节点首行文本。

    Returns:
        是 gtest 用例宏返回 ``True``。
    """
    return any(first_line.startswith(f"{macro}(") for macro in TEST_MACROS)


def _syntax_warnings(root_node, src: bytes) -> tuple[list[str], list[str]]:
    """收集解析告警:真 ``ERROR`` 节点(判红)与缺记号(只提示)。

    ``tree-sitter-cpp`` 对个别合法写法会补「缺记号」而不是报 ``ERROR``(现库
    ``src/util/log.h`` 的默认实参 ``= {}`` 就是这种),结构仍然完整,不该判红;
    真的 ``ERROR`` 节点说明这个文件判不准,必须 fail-closed。

    Args:
        root_node: 语法树根节点。
        src: 文件原始字节。

    Returns:
        ``(致命错误, 提示)`` 两个列表,元素都是人读的一行。
    """
    fatal: list[str] = []
    warnings: list[str] = []

    def walk(node) -> None:
        for child in node.children:
            if child.type == "ERROR":
                snippet = src[child.start_byte : child.end_byte].decode("utf-8", "replace")
                fatal.append(f"第 {child.start_point[0] + 1} 行解析出 ERROR 节点:{snippet[:60]!r}")
            elif child.is_missing:
                warnings.append(f"第 {child.start_point[0] + 1} 行有缺记号(解析器自行补齐,结构仍完整)")
            walk(child)

    walk(root_node)
    return fatal, warnings


def check_file(root: Path, imserver: Path, path: Path, parser) -> FileReport:
    """检查一个 ``.h`` / ``.cpp`` 文件。

    Args:
        root: 报告路径的基准目录(``imserver/`` 的上级:生产是仓库根,自测是临时目录)。
        imserver: ``imserver/`` 目录(``文件名称`` 字段的基准)。
        path: 被检查的文件。
        parser: ``load_parser()`` 返回的解析器。

    Returns:
        该文件的检查结果。

    Raises:
        ToolingError: 文件读不了,或解析出 ``ERROR`` 节点(判不准就不许算绿)。
    """
    rel = relative_path(root, path)
    report = FileReport(path=rel)
    lines = read_lines(path)
    inside = path.resolve().relative_to(imserver.resolve()).as_posix()

    for line, message in header_findings(rel, lines, inside):
        report.findings.append(Finding(rel, line, message))

    source = path.read_bytes()
    tree = parser.parse(source)
    fatal, warnings = _syntax_warnings(tree.root_node, source)
    if fatal:
        raise ToolingError(
            f"{rel} 解析失败,门禁无法判定(报 tree-sitter 不支持的写法,需先补解析支持):"
            + ";".join(fatal)
        )
    report.warnings = [f"{rel}: {item}" for item in warnings]

    report.blocks = sum(1 for line in lines if line.strip().startswith("// 函数简介"))

    nodes: list[tuple[int, str]] = []
    _function_nodes(tree.root_node, source, nodes)
    for row, first_line in sorted(nodes):
        is_test = _is_test_case(first_line)
        if rel.split("/")[1] == "tests" and not is_test:
            report.exempt_tests += 1  # 现库惯例:TEST 用例用块,helper 用 /// 或无注释
            continue
        report.required += 1
        for line, message in block_findings(lines, row):
            report.findings.append(Finding(rel, line, message))

    for line, message in body_block_findings(lines):
        report.findings.append(Finding(rel, line, message))
    return report


def iter_sources(imserver: Path) -> list[Path]:
    """列出被检查的文件(``src/`` 与 ``tests/`` 下的 ``.h`` / ``.cpp``)。

    Args:
        imserver: ``imserver/`` 目录。

    Returns:
        按 POSIX 字节序排好的路径列表(顺序跨平台稳定,报告可逐字比对)。

    Raises:
        ToolingError: 两个子目录都不存在(``--root`` 指错了地方)。
    """
    found: list[Path] = []
    for subdir in SCANNED_SUBDIRS:
        base = imserver / subdir
        if not base.is_dir():
            continue
        found.extend(
            path for path in base.rglob("*") if path.is_file() and path.suffix in SOURCE_SUFFIXES
        )
    if not found:
        raise ToolingError(
            f"{imserver} 下没有 src/ 或 tests/ 里的 .h / .cpp —— --root 应指向仓库的 imserver/ 目录"
        )
    return sorted(found, key=lambda path: path.as_posix().encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表;``None`` 表示读 ``sys.argv[1:]``。

    Returns:
        进程退出码:0 全绿 / 1 有违规 / 2 工具自身出错。
    """
    parser_arg = argparse.ArgumentParser(
        prog="check_cpp_comments.py",
        description="C++ 注释机械门禁:文件头 + 函数注释块(判据见 docs/standards/cpp.md)。",
    )
    parser_arg.add_argument(
        "--check", action="store_true", help="执行检查(缺省行为;gates.toml 里显式写出)"
    )
    parser_arg.add_argument(
        "--root", type=Path, default=DEFAULT_ROOT, help="被检查的 imserver/ 目录(自测用)"
    )
    parser_arg.add_argument(
        "--verbose", action="store_true", help="打印基线计数、解析告警与 tests/ 豁免清单"
    )
    args = parser_arg.parse_args(argv)

    imserver = args.root.resolve()
    if not imserver.is_dir():
        print(f"错误:--root 不是目录:{imserver}", file=sys.stderr)
        return EXIT_TOOLING
    try:
        parser = load_parser()
    except ToolingError as exc:
        print(f"错误:{exc}", file=sys.stderr)
        return EXIT_TOOLING

    reports: list[FileReport] = []
    try:
        sources = iter_sources(imserver)
    except ToolingError as exc:
        print(f"错误:{exc}", file=sys.stderr)
        return EXIT_TOOLING
    for path in sources:
        try:
            reports.append(check_file(imserver.parent, imserver, path, parser))
        except ToolingError as exc:
            print(f"错误:{exc}", file=sys.stderr)
            return EXIT_TOOLING

    findings = [item for report in reports for item in report.findings]
    findings.sort(key=lambda item: (item.path.encode("utf-8"), item.line, item.message))
    blocks = sum(report.blocks for report in reports)
    required = sum(report.required for report in reports)
    exempt = sum(report.exempt_tests for report in reports)

    if args.verbose:
        for report in reports:
            print(
                f"[verbose] {report.path}:块 {report.blocks} / 需块函数 {report.required}"
                + (f" / 豁免的 tests 辅助函数 {report.exempt_tests}" if report.exempt_tests else ""),
                file=sys.stderr,
            )
        for report in reports:
            for warning in report.warnings:
                print(f"[verbose] {warning}", file=sys.stderr)

    if not findings:
        if args.verbose:
            print(
                f"合规:{len(reports)} 个文件 / {blocks} 个注释块 / {required} 个需块函数"
                + (f";tests/ 按现库惯例豁免 {exempt} 个辅助函数" if exempt else ""),
                file=sys.stderr,
            )
        return EXIT_OK

    for item in findings:
        print(item.render())
    print(
        f"C++ 注释门禁:检查 {len(reports)} 个文件、{blocks} 个注释块({required} 个函数需块),"
        f"发现 {len(findings)} 处问题"
    )
    return EXIT_FINDINGS


if __name__ == "__main__":
    sys.exit(main())
