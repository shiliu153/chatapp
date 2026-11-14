"""注释规范门禁:模块头与函数/类 docstring 的覆盖率检查。

判定规则见 docs/standards/python.md。本模块只依赖标准库,可直接命令行运行:

    python config/comment_coverage.py              # 全量检查
    python config/comment_coverage.py --app im     # 只检查某个 app
    python config/comment_coverage.py --warnings   # 附带口语词提示(不拦截)
    python config/comment_coverage.py --structure  # 附带 Args 小节提示(不拦截)

文件信息:
    文件名称          config/comment_coverage.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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
# 单字口语词仅在其前一字为「踩」时豁免 —— 「踩坑记录:docs/pitfalls/...」是规范模板要求的写法
CASUAL_RE = re.compile(r"(别用|别在|别把|别出|够用|我们|压根|悄悄|顺手|其实|干脆|偷懒|(?<!踩)坑)")

# unittest / Django 的测试生命周期钩子:由框架调用,不是对外 API
LIFECYCLE_NAMES = frozenset({"setUp", "tearDown", "setUpClass", "tearDownClass",
                             "setUpTestData", "asyncSetUp", "asyncTearDown"})

# 框架读取的声明式内部类:给 model+fields 这类配置写 docstring 只是样板
DECLARATIVE_CLASS_NAMES = frozenset({"Meta"})


def _is_exempt(node: ast.AST, inside_function: bool) -> bool:
    """判断节点是否豁免 docstring 要求(规则见 docs/standards/python.md §6)。

    参数说明:
        node: 待判定的函数或类节点。
        inside_function: 该节点是否嵌套在某个函数体内。

    返回参数:
        True 表示豁免。

    使用示例:
        ``_is_exempt(node, inside_function)``

    备注信息:
        豁免四类:嵌套在函数体内的闭包与局部类、``Meta`` 等声明式内部类、
        ``test_*`` 用例、``setUp`` / ``tearDown`` 等测试生命周期钩子。
        判定只看名称与嵌套形态,不看文件路径,避免门禁脚本按目录特判。
    """
    if inside_function:
        return True          # 闭包与局部类:所属函数的实现细节,不是对外 API
    if isinstance(node, ast.ClassDef) and node.name in DECLARATIVE_CLASS_NAMES:
        return True          # Meta 等声明式内部类:框架读取,docstring 是样板
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name.startswith("test_") or node.name in LIFECYCLE_NAMES:
            return True
    return False


def _iter_symbols(node: ast.AST,
                  inside_function: bool = False) -> Iterator[tuple[ast.AST, bool]]:
    """递归产出文件中的全部函数与类,并标记其是否嵌套在函数体内。

    参数说明:
        node: 当前遍历到的 AST 节点。
        inside_function: 当前节点是否已处于某个函数体内。

    返回参数:
        生成器,逐个产出 ``(函数或类节点, 是否嵌套在函数体内)``。

    使用示例:
        ``for node, nested in _iter_symbols(tree): ...``

    备注信息:
        只有走进函数体才会置位嵌套标记,类体内的普通方法因此仍算顶层符号;
        标记只向下传递,不会因回到类作用域而复位。
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

    参数说明:
        path: 待展示的文件路径。

    返回参数:
        相对 chatapp/ 的路径;不在其下时(单元测试用临时目录)降级为文件名。

    使用示例:
        ``_display_path(Path("chatapp/config/logging.py"))``

    备注信息:
        路径分隔符统一成 ``/``,保证 Windows 本地与 Linux CI 输出的报错完全一致。
    """
    try:
        return path.relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        return path.name


def iter_target_files(root: Path = BACKEND_ROOT, app: str | None = None) -> Iterator[Path]:
    """产出需要检查的 .py 文件。

    跳过 migrations、缓存目录与空白文件(空的 __init__.py 无内容可写)。

    参数说明:
        root: 后端根目录,默认 chatapp/。
        app: 只检查该 app 子目录;None 表示全量。

    返回参数:
        生成器,逐个产出待检查的文件路径,按路径升序。

    使用示例:
        ``for path in iter_target_files(app="config"): ...``

    备注信息:
        ``SKIP_DIRS`` 按路径片段匹配,``migrations`` 出现在任意层级都会被跳过;
        判空按全文 ``strip()``,只含空白字符的文件同样不计入。
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

    参数说明:
        path: 待检查的 .py 文件。

    返回参数:
        缺口描述列表,格式 ``相对路径:行号 说明``;空列表表示通过。

    使用示例:
        ``problems = check_file(Path("chatapp/config/logging.py"))``

    备注信息:
        只报两类缺口:模块/符号缺 docstring、docstring 里出现 emoji 一类装饰符号
        (``DECORATION_RE``)。文件语法错误时 ``ast.parse`` 直接抛出,不做兜底。
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

    参数说明:
        path: 待扫描的 .py 文件。

    返回参数:
        生成器,逐个产出 ``(行号, 注释原文)``;无法 tokenize 时结束产出。

    使用示例:
        ``for lineno, text in _iter_comments(path): ...``

    备注信息:
        走 ``tokenize`` 而不是按行找井号,因此字符串字面量里的井号不会被误当成注释;
        ``tokenize.TokenError`` 视为文件末尾,不向上抛。
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

    参数说明:
        root: 后端根目录,默认 chatapp/。
        app: 只检查该 app 子目录;None 表示全量。

    返回参数:
        缺口描述列表;空列表表示全部通过。

    使用示例:
        ``problems = find_problems(app="config")``

    备注信息:
        门禁断言读的就是本函数(``config/tests.py::CommentCoverageTests``);
        报告顺序与 ``iter_target_files`` 的路径升序一致。
    """
    problems: list[str] = []
    for path in iter_target_files(root, app):
        problems.extend(check_file(path))
    return problems


def find_tone_warnings(root: Path = BACKEND_ROOT, app: str | None = None) -> list[str]:
    """汇总口语词命中项(只提示,不参与门禁断言)。

    黑名单会有误报(如「兜底」在技术语境里合法),因此只报告不拦截。

    参数说明:
        root: 后端根目录,默认 chatapp/。
        app: 只检查该 app 子目录;None 表示全量。

    返回参数:
        形如 ``相对路径:行号 口语词「命中词」`` 的提示列表。

    使用示例:
        ``warnings = find_tone_warnings()``

    备注信息:
        docstring 与井号注释两处都扫,同一处命中多个词只报第一个。
        单字「坑」仅在其前一字为「踩」时豁免(规范模板要求写「踩坑记录:docs/pitfalls/...」)。
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


def find_structure_warnings(root: Path = BACKEND_ROOT, app: str | None = None) -> list[str]:
    """汇总公开函数的 参数说明 小节缺失项(只提示,不参与门禁断言)。

    AST 无法判断「这个参数是否显然到可以不写」,因此不做硬门禁;命中项供
    review 与 ``docs/standards/python.md`` 的人工检查使用。私有函数、``test_*``
    用例、无参函数、``@property`` 与函数内闭包不在检查范围内。

    参数说明:
        root: 后端根目录,默认 chatapp/。
        app: 只检查该 app 子目录;None 表示全量。

    返回参数:
        形如 ``相对路径:行号 函数名 缺少 参数说明 小节`` 的提示列表。

    使用示例:
        ``warnings = find_structure_warnings(app="config")``

    备注信息:
        小节判定兼容两种写法:带 ``参数说明:`` 或旧式 ``Args:`` 任一即视为已写,
        提示文案统一按新口径写「缺少 参数说明 小节」。
        ``*args`` / ``**kwargs`` 也算参数,带它们的公开函数同样要求写小节。
    """
    warnings: list[str] = []
    for path in iter_target_files(root, app):
        rel = _display_path(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node, inside_function in _iter_symbols(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _is_exempt(node, inside_function) or node.name.startswith("_"):
                continue
            if any(isinstance(item, ast.Name) and item.id == "property"
                   for item in node.decorator_list):
                continue
            params = [arg.arg for arg in node.args.posonlyargs + node.args.args
                      + node.args.kwonlyargs if arg.arg not in ("self", "cls")]
            if node.args.vararg:
                params.append(node.args.vararg.arg)
            if node.args.kwarg:
                params.append(node.args.kwarg.arg)
            if not params:
                continue
            doc = ast.get_docstring(node)
            if doc and "参数说明:" not in doc and "Args:" not in doc:
                warnings.append(f"{rel}:{node.lineno} {node.name} 缺少 参数说明 小节")
    return warnings


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 参数列表;None 表示取 sys.argv。

    返回参数:
        进程退出码:0 表示通过,1 表示存在缺口。

    使用示例:
        ``sys.exit(main(["--structure"]))``

    备注信息:
        ``--warnings`` / ``--structure`` 的提示先打印,再跑硬门禁;
        有缺口时逐条打印并返回 1,否则打印「无缺口」并返回 0。
    """
    parser = argparse.ArgumentParser(description="检查 Python 注释规范覆盖情况")
    parser.add_argument("--app", default=None, help="只检查指定 app 子目录")
    parser.add_argument("--warnings", action="store_true",
                        help="附带口语词提示(不拦截)")
    parser.add_argument("--structure", action="store_true",
                        help="附带公开函数 参数说明 小节提示(不拦截)")
    args = parser.parse_args(argv)

    if args.warnings:
        for warning in find_tone_warnings(app=args.app):
            print(f"[提示] {warning}")
    if args.structure:
        for warning in find_structure_warnings(app=args.app):
            print(f"[结构] {warning}")

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
