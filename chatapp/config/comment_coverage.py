"""注释规范门禁:模块头与函数/类 docstring 的覆盖率检查。

判定规则见 docs/standards/python.md。本模块只依赖标准库,可直接命令行运行:

    python config/comment_coverage.py              # 全量检查
    python config/comment_coverage.py --app im     # 只检查某个 app
    python config/comment_coverage.py --warnings   # 附带口语词提示(不拦截)
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tokenize
from collections.abc import Iterator
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"migrations", "__pycache__"}

DECORATION_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u26A0]")
CASUAL_RE = re.compile(r"(别用|别在|别把|别出|够用|我们|压根|悄悄|顺手|其实|干脆|偷懒|坑)")

# unittest / Django 的测试生命周期钩子:由框架调用,不是对外 API
LIFECYCLE_NAMES = frozenset({"setUp", "tearDown", "setUpClass", "tearDownClass",
                             "setUpTestData", "asyncSetUp", "asyncTearDown"})


def _is_exempt(node: ast.AST, inside_function: bool) -> bool:
    """判断节点是否豁免 docstring 要求(规则见 docs/standards/python.md §6)。

    Args:
        node: 待判定的函数或类节点。
        inside_function: 该节点是否嵌套在某个函数体内。

    Returns:
        True 表示豁免。
    """
    if inside_function:
        return True          # 闭包与局部类:所属函数的实现细节,不是对外 API
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name.startswith("test_") or node.name in LIFECYCLE_NAMES:
            return True
    return False


def _iter_symbols(node: ast.AST,
                  inside_function: bool = False) -> Iterator[tuple[ast.AST, bool]]:
    """递归产出文件中的全部函数与类,并标记其是否嵌套在函数体内。

    Args:
        node: 当前遍历到的 AST 节点。
        inside_function: 当前节点是否已处于某个函数体内。

    Yields:
        ``(函数或类节点, 是否嵌套在函数体内)``。
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield child, inside_function
            deeper = inside_function or isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef))
            yield from _iter_symbols(child, deeper)
        else:
            yield from _iter_symbols(child, inside_function)


def _display_path(path: Path) -> str:
    """给出门禁报错用的展示路径。

    Args:
        path: 待展示的文件路径。

    Returns:
        相对 chatapp/ 的路径;不在其下时(单元测试用临时目录)降级为文件名。
    """
    try:
        return path.relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        return path.name


def iter_target_files(root: Path = BACKEND_ROOT, app: str | None = None) -> Iterator[Path]:
    """产出需要检查的 .py 文件。

    跳过 migrations、缓存目录与空白文件(空的 __init__.py 无内容可写)。

    Args:
        root: 后端根目录,默认 chatapp/。
        app: 只检查该 app 子目录;None 表示全量。

    Yields:
        待检查的文件路径,按路径升序。
    """
    base = root / app if app else root
    for path in sorted(base.rglob("*.py")):
        if SKIP_DIRS & set(path.parts):
            continue
        if not path.read_text(encoding="utf-8").strip():
            continue
        yield path


def check_file(path: Path) -> list[str]:
    """检查单个文件的注释覆盖情况。

    Args:
        path: 待检查的 .py 文件。

    Returns:
        缺口描述列表,格式 ``相对路径:行号 说明``;空列表表示通过。
    """
    problems: list[str] = []
    rel = _display_path(path)
    tree = ast.parse(path.read_text(encoding="utf-8"))

    module_doc = ast.get_docstring(tree)
    if module_doc is None:
        problems.append(f"{rel}:1 缺少模块 docstring")
    elif DECORATION_RE.search(module_doc):
        problems.append(f"{rel}:1 模块 docstring 含装饰符号")

    for node, inside_function in _iter_symbols(tree):
        if _is_exempt(node, inside_function):
            continue
        name = node.name
        doc = ast.get_docstring(node)
        if doc is None:
            problems.append(f"{rel}:{node.lineno} {name} 缺少 docstring")
        elif DECORATION_RE.search(doc):
            problems.append(f"{rel}:{node.lineno} {name} 的 docstring 含装饰符号")
    return problems


def _iter_comments(path: Path) -> Iterator[tuple[int, str]]:
    """产出文件中的 # 注释。

    Args:
        path: 待扫描的 .py 文件。

    Yields:
        ``(行号, 注释原文)``;无法 tokenize 时结束产出。
    """
    with path.open(encoding="utf-8") as handle:
        try:
            for token in tokenize.generate_tokens(handle.readline):
                if token.type == tokenize.COMMENT:
                    yield token.start[0], token.string
        except tokenize.TokenError:
            return


def find_problems(root: Path = BACKEND_ROOT, app: str | None = None) -> list[str]:
    """汇总全部注释缺口。

    Args:
        root: 后端根目录,默认 chatapp/。
        app: 只检查该 app 子目录;None 表示全量。

    Returns:
        缺口描述列表;空列表表示全部通过。
    """
    problems: list[str] = []
    for path in iter_target_files(root, app):
        problems.extend(check_file(path))
    return problems


def find_tone_warnings(root: Path = BACKEND_ROOT, app: str | None = None) -> list[str]:
    """汇总口语词命中项(只提示,不参与门禁断言)。

    黑名单会有误报(如「兜底」在技术语境里合法),因此只报告不拦截。

    Args:
        root: 后端根目录,默认 chatapp/。
        app: 只检查该 app 子目录;None 表示全量。

    Returns:
        形如 ``相对路径:行号 口语词「命中词」`` 的提示列表。
    """
    warnings: list[str] = []
    for path in iter_target_files(root, app):
        rel = _display_path(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                match = CASUAL_RE.search(doc) if doc else None
                if match:
                    warnings.append(
                        f"{rel}:{getattr(node, 'lineno', 1)} 口语词「{match.group(1)}」")
        for lineno, text in _iter_comments(path):
            match = CASUAL_RE.search(text)
            if match:
                warnings.append(f"{rel}:{lineno} 口语词「{match.group(1)}」")
    return warnings


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表;None 表示取 sys.argv。

    Returns:
        进程退出码:0 表示通过,1 表示存在缺口。
    """
    parser = argparse.ArgumentParser(description="检查 Python 注释规范覆盖情况")
    parser.add_argument("--app", default=None, help="只检查指定 app 子目录")
    parser.add_argument("--warnings", action="store_true",
                        help="附带口语词提示(不拦截)")
    args = parser.parse_args(argv)

    if args.warnings:
        for warning in find_tone_warnings(app=args.app):
            print(f"[提示] {warning}")

    problems = find_problems(app=args.app)
    if problems:
        print(f"发现 {len(problems)} 处注释缺口:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print("无缺口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
