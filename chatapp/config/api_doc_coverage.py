"""接口文档覆盖率:URLconf 与 ``docs/api`` 信息行的双向比对。

本模块只负责解析与比对逻辑,门禁断言在 ``config/tests.py::ApiDocsCoverageTests``。

设计要点:
    「信息行」指 ``> `GET` `/api/v1/...` · ...`` 形式的引用行。解析时会剥离
    markdown 装饰符(``>``、反引号、加粗星号)并跳过 ``` 代码围栏,避免
    ``docs/api/README.md`` 里的模板样例被误当成真实接口记录。

文件信息:
    文件名称          config/api_doc_coverage.py
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

import re
from pathlib import Path

from django.conf import settings
from django.urls import URLPattern, URLResolver

DOCS_DIR = Path(settings.BASE_DIR).parent / "docs" / "api"

METHODS = ("get", "post", "patch", "delete")

# 信息行(剥离 ">"、反引号、空白后)以「方法 空格 /api/v1/...」开头
INFO_LINE_RE = re.compile(r"^(GET|POST|PATCH|DELETE) (/api/v1/\S+)")
# Django 路径参数:<int:photo_id> / <str:code> / <photo_id> 统一成 {photo_id}
ROUTE_PARAM_RE = re.compile(r"<(?:\w+:)?(\w+)>")
# 行首的 markdown 装饰:引用符、空白、加粗/斜体星号
LINE_DECORATION_RE = re.compile(r"^[\s>*]+")
# 代码围栏:围栏内的示例代码不算文档标记(README 的模板样例就放在围栏里)
FENCE_RE = re.compile(r"^\s*```")


def normalize_route(route: str) -> str:
    """把 Django 路径参数统一成文档里使用的 ``{name}`` 写法。

    参数说明:
        route: URLconf 里的原始路径,如 ``me/photos/<int:photo_id>``。

    返回参数:
        归一化后的路径,如 ``me/photos/{photo_id}``。

    使用示例:
        ``normalize_route("me/photos/<int:photo_id>")``

    备注信息:
        转换类型前缀(<int:>/<str:>)一并去掉,只留参数名。
        URLconf 侧与文档侧的路径都经它归一化,比对才能对齐。
    """
    return ROUTE_PARAM_RE.sub(r"{\1}", route)


def _methods_of(view) -> list[str]:
    """DRF 视图(@api_view 或 as_view())的 cls 上,只有被声明的方法才是可调用属性。

    参数说明:
        view: URLconf 里登记的视图回调(``@api_view`` 包装后的函数)。

    返回参数:
        该视图声明的方法名列表,已转大写,如 ``["GET", "POST"]``;
        没有 ``cls`` 属性的非 DRF 视图返回空列表。

    使用示例:
        ``_methods_of(pattern.callback)``

    备注信息:
        只看 ``cls`` 上的小写同名属性是否可调用,与 DRF 为 ``APIView`` 子类
        挂方法的机制一致;``METHODS`` 之外的动词(如 ``PUT``)不参与枚举。
    """
    cls = getattr(view, "cls", None)
    if cls is None:
        return []
    return [m.upper() for m in METHODS if callable(getattr(cls, m, None))]


def endpoints_from_urlconf() -> set[tuple[str, str]]:
    """枚举 URLconf 中全部可调用的接口。

    参数说明:
        无。

    返回参数:
        ``{(HTTP 方法, 归一化路径)}`` 集合,仅含 ``/api/v1`` 下的接口。

    使用示例:
        ``endpoints_from_urlconf()``

    备注信息:
        ``config.api_urls`` 在函数体内导入,避免模块导入期就构建 URL 表;
        递归展开 ``URLResolver``,前缀按 ``str(pattern)`` 原样拼接;只处理
        ``URLPattern`` 与 ``URLResolver`` 两种节点。
    """
    from config import api_urls

    found: set[tuple[str, str]] = set()

    def walk(patterns, prefix: str) -> None:
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, prefix + str(pattern.pattern))
            elif isinstance(pattern, URLPattern):
                for method in _methods_of(pattern.callback):
                    found.add((method, normalize_route("/api/v1/" + prefix + str(pattern.pattern))))

    walk(api_urls.urlpatterns, "")
    return found


def _iter_doc_lines(text: str):
    """产出 (行号, 行内容);跳过 ``` 代码围栏内的内容。

    参数说明:
        text: 分册全文。

    返回参数:
        生成器,逐个产出 ``(行号, 行内容)``;行号从 1 开始,围栏行与围栏内的内容都不产出。

    使用示例:
        ``list(_iter_doc_lines(md.read_text(encoding="utf-8")))``

    备注信息:
        围栏按行首 ``` 切换开关(``FENCE_RE``),因此要求围栏单独成行;
        ``docs/api/README.md`` 里的模板样例正因落在围栏内,才不会被当成真实接口记录。
    """
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield lineno, line


def endpoints_from_docs(docs_dir: Path = DOCS_DIR) -> dict[tuple[str, str], str]:
    """从 ``docs/api`` 各分册里解析出已记录的接口信息行。

    参数说明:
        docs_dir: 文档目录,默认 ``docs/api``。

    返回参数:
        ``{(HTTP 方法, 路径): "文件名:行号"}``,保留位置信息以便报错时直接定位。

    使用示例:
        ``endpoints_from_docs(Path("docs/api"))``

    备注信息:
        遍历目录下全部 ``*.md``(含子目录);解析前先剥掉引用符、加粗星号与反引号。
        同一接口被多个分册重复记录时,后写入的位置覆盖先写入的。
    """
    documented: dict[tuple[str, str], str] = {}
    for md in sorted(Path(docs_dir).rglob("*.md")):
        for lineno, line in _iter_doc_lines(md.read_text(encoding="utf-8")):
            stripped = LINE_DECORATION_RE.sub("", line).replace("`", "").strip()
            match = INFO_LINE_RE.match(stripped)
            if match:
                documented[(match.group(1), match.group(2))] = f"{md.name}:{lineno}"
    return documented


def find_problems(docs_dir: Path | None = None) -> list[str]:
    """双向比对 URLconf 与文档,列出全部不一致。

    参数说明:
        docs_dir: 文档目录;``None`` 表示使用默认的 ``docs/api``。

    返回参数:
        问题描述列表;空列表表示文档与接口完全对齐。

    使用示例:
        ``problems = find_problems()``

    备注信息:
        方向一「接口有、文档无」提示补到 ``docs/api/<分册>.md``;方向二「文档有、接口无」
        附带文档位置,便于直接定位到要删的那一行。两个方向都按方法名与路径升序输出。
    """
    real = endpoints_from_urlconf()
    documented = endpoints_from_docs(docs_dir or DOCS_DIR)

    problems = [
        f"接口 {method} {path} 未写文档,请补到 docs/api/<分册>.md"
        for method, path in sorted(real - set(documented))
    ]
    problems += [
        f"文档记录的 {method} {path}({documented[(method, path)]})在 URLconf 中已不存在,请删除或修正"
        for method, path in sorted(set(documented) - real)
    ]
    return problems
