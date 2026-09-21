"""接口文档覆盖率:URLconf 与 docs/api 信息行的双向比对(逻辑层,门禁测试在 tests.py)。"""

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
    return ROUTE_PARAM_RE.sub(r"{\1}", route)


def _methods_of(view) -> list[str]:
    """DRF 视图(@api_view 或 as_view())的 cls 上,只有被声明的方法才是可调用属性。"""
    cls = getattr(view, "cls", None)
    if cls is None:
        return []
    return [m.upper() for m in METHODS if callable(getattr(cls, m, None))]


def endpoints_from_urlconf() -> set[tuple[str, str]]:
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
    """产出 (行号, 行内容);跳过 ``` 代码围栏内的内容。"""
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield lineno, line


def endpoints_from_docs(docs_dir: Path = DOCS_DIR) -> dict[tuple[str, str], str]:
    documented: dict[tuple[str, str], str] = {}
    for md in sorted(Path(docs_dir).rglob("*.md")):
        for lineno, line in _iter_doc_lines(md.read_text(encoding="utf-8")):
            stripped = LINE_DECORATION_RE.sub("", line).replace("`", "").strip()
            match = INFO_LINE_RE.match(stripped)
            if match:
                documented[(match.group(1), match.group(2))] = f"{md.name}:{lineno}"
    return documented


def find_problems(docs_dir: Path | None = None) -> list[str]:
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
