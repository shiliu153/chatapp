"""OpenAPI 契约 ↔ ``docs/api`` 分册的字段级双向比对(D-5 第 2 步)。

设计要点:
    1. **人读文档也是事实来源**:``docs/api/*.md`` 每个接口小节里的「请求参数 / 响应参数」
       表格就是对外承诺的字段清单,``openapi.yml`` 是从代码生成的机器契约 ——
       两边任一侧多一个或少一个字段都算不一致,所以是**双向**比对。
    2. **只比顶层字段**:嵌套结构(``tags[]`` / ``photos[]``)在文档里以「结构见
       users.md §2.1」引用,逐层比对等于把同一张嵌套表比两遍,收益低、噪音大。
       真出事故的是「顶层字段改名/删除」,顶层已经能覆盖。
    3. **分页信封不参与比对**:``count / next_cursor / has_more / results`` 是
       ``conventions.md`` 里定义的公共形状,接口小节只写 ``results[]`` 的字段,
       因此比对前先把 ``results`` 解开。
    4. **路径参数算「请求参数」**:本项目文档把 ``post_id`` / ``photo_id`` 这类路径参数
       写进「请求参数」表,所以请求侧取「parameters(任意 in)∪ requestBody 字段」。

注意事项:
    本模块只负责解析与比对,门禁断言在 ``config/test_schema_contract.py``;
    字段级契约本身写在视图的 ``@extend_schema`` 上。
"""

from __future__ import annotations

import re
from pathlib import Path

from config.api_doc_coverage import DOCS_DIR, FENCE_RE, INFO_LINE_RE, LINE_DECORATION_RE

# 表格首行(表头)必须以「参数名称」开头;错误码表(首列「错误码」)因此被自动跳过
TABLE_HEADER_RE = re.compile(r"^\|\s*参数名称\s*\|")
# 小节内的表格类型标记:``**请求参数**(Query)`` / ``**响应参数**``
KIND_MARKER_RE = re.compile(r"^\*\*(请求|响应)参数\*\*")
# 数据行首列:字段名只允许 ASCII 标识符(``user_id`` / ``avatar_url``);
# 允许连字符是为了 ``X-Original-URI`` 这类请求头参数
FIELD_CELL_RE = re.compile(r"^\|\s*`?([A-Za-z_][A-Za-z0-9_-]*)`?\s*\|")
# 小节标题:``### 5.1 动态流``
HEADING_RE = re.compile(r"^###\s+(\d+\.\d+)\s")
# 字段继承引用:``同 [5.1 动态流](#51-动态流)。``
REF_LINE_RE = re.compile(r"^同\s*\[(\d+\.\d+)")

# 分页信封字段:由 conventions.md 统一描述,不出现在单接口的响应参数表里
ENVELOPE_FIELDS = frozenset({"count", "next_cursor", "has_more", "next", "previous", "results"})
# 认信封用的是「兄弟字段」:只有 results 没有 count/has_more 之类的,是业务字段而不是分页
PAGE_SIBLINGS = ENVELOPE_FIELDS - {"results"}

# 成功响应里可能是 200 也可能是 201
SUCCESS_CODES = ("200", "201")

# 文档里写了、但 OpenAPI 3.0 无法表达的字段。目前只有一种情况:
# **DELETE 请求体** —— OpenAPI 3.0 没有定义 DELETE body,drf-spectacular 直接丢弃
# (``_get_request_body``: only PUT/PATCH/POST can have a body)。账号注销要求 body 带
# ``phone`` 二次确认,只能在文档里描述。新增条目必须写明原因,且只允许 DELETE。
SCHEMA_INEXPRESSIBLE: dict[tuple[str, str], set[str]] = {
    ("DELETE", "/api/v1/users/me"): {"phone"},
}


def docs_fields(docs_dir: Path = DOCS_DIR) -> dict[tuple[str, str], dict[str, set[str]]]:
    """从 ``docs/api`` 各分册解析出每个接口声明的请求/响应字段。

    Args:
        docs_dir: 文档目录,默认 ``docs/api``。

    Returns:
        ``{(HTTP 方法, 路径): {"request": {...}, "response": {...}}}``。
        没有参数表的接口(如 ``health``)返回空集合,表示「文档声明它没有字段」。
    """
    parsed: dict[tuple[str, str], dict[str, set[str]]] = {}
    for md in sorted(Path(docs_dir).rglob("*.md")):
        _parse_doc_file(md, parsed)
    return parsed


def _parse_doc_file(md: Path, parsed: dict[tuple[str, str], dict[str, set[str]]]) -> None:
    """解析单个分册:接口小节 → 请求/响应字段,并就地展开 ``同 [X.Y]`` 引用。

    Args:
        md: markdown 分册路径。
        parsed: 汇总结果(跨分册共享,原地写入)。

    Notes:
        每个「请求参数 / 响应参数」标记后**只取第一张表**。``users.md §2.1`` 在响应表后面
        还有 ``tags[]`` / ``photos[]`` 两张子结构表,它们不是顶层字段,混进来会让门禁误报。
    """
    sections: dict[str, tuple[str, str]] = {}
    refs: dict[tuple[str, str], str] = {}

    current: tuple[str, str] | None = None
    section = ""
    kind = "request"
    in_table = False
    tables_seen = {"request": 0, "response": 0}
    in_fence = False

    for line in md.read_text(encoding="utf-8").splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading = HEADING_RE.match(line)
        if heading:
            section = heading.group(1)
            current = None
            continue

        stripped = LINE_DECORATION_RE.sub("", line).replace("`", "").strip()
        info = INFO_LINE_RE.match(stripped)
        if info:
            current = (info.group(1), info.group(2))
            parsed.setdefault(current, {"request": set(), "response": set()})
            sections[section] = current
            kind = "request"
            in_table = False
            tables_seen = {"request": 0, "response": 0}
            continue
        if current is None:
            continue

        marker = KIND_MARKER_RE.match(line.strip())
        if marker:
            kind = "request" if marker.group(1) == "请求" else "response"
            in_table = False
            continue

        reference = REF_LINE_RE.match(line.strip())
        if reference and kind == "response":
            refs[current] = reference.group(1)
            continue

        if TABLE_HEADER_RE.match(line.strip()):
            tables_seen[kind] += 1
            in_table = tables_seen[kind] == 1
            continue
        if not in_table:
            continue
        if not line.strip().startswith("|"):
            in_table = False
            continue
        cell = FIELD_CELL_RE.match(line.strip())
        if cell:
            parsed[current][kind].add(cell.group(1))

    for endpoint, number in refs.items():
        target = sections.get(number)
        if target is not None and not parsed[endpoint]["response"]:
            parsed[endpoint]["response"] = set(parsed[target]["response"])


def _resolve(schema: dict, document: dict) -> dict:
    """把 ``$ref`` 解析成组件定义(只处理本文件用到的单层引用链)。

    Args:
        schema: 可能带 ``$ref`` 的 schema 片段。
        document: 整份 OpenAPI 文档(取 ``components.schemas``)。

    Returns:
        解析后的 schema 字典;引用不存在时返回空字典。
    """
    seen: set[str] = set()
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen:      # 循环引用:防御性退出,避免死循环
            return {}
        seen.add(ref)
        name = ref.rsplit("/", 1)[-1]
        schema = document.get("components", {}).get("schemas", {}).get(name, {})
    return schema if isinstance(schema, dict) else {}


def _object_fields(schema: dict, document: dict) -> set[str]:
    """取出一个 schema 片段的顶层字段名(数组会先解开成元素)。

    Args:
        schema: schema 片段(可能是对象、数组或 ``$ref``)。
        document: 整份 OpenAPI 文档。

    Returns:
        顶层属性名集合;不是对象时返回空集合。
    """
    resolved = _resolve(schema, document)
    if resolved.get("type") == "array":
        resolved = _resolve(resolved.get("items", {}), document)
    properties = resolved.get("properties")
    return set(properties) if isinstance(properties, dict) else set()


def _request_fields(operation: dict, document: dict) -> set[str]:
    """取出一个操作「能收到的字段」:路径/查询/请求头参数 + 请求体字段。

    Args:
        operation: OpenAPI 的 operation 对象(某个方法)。
        document: 整份 OpenAPI 文档。

    Returns:
        字段名集合。
    """
    names = {param["name"] for param in operation.get("parameters", []) if "name" in param}
    body = operation.get("requestBody", {}).get("content", {})
    for media in body.values():
        names |= _object_fields(media.get("schema", {}), document)
    return names


def _response_fields(operation: dict, document: dict) -> set[str]:
    """取出一个操作成功响应的顶层字段(分页信封会解到 ``results[]`` 的条目)。

    Args:
        operation: OpenAPI 的 operation 对象(某个方法)。
        document: 整份 OpenAPI 文档。

    Returns:
        字段名集合;204 等无响应体时为空集合。
    """
    responses = operation.get("responses", {})
    for code in SUCCESS_CODES:
        content = responses.get(code, {}).get("content", {})
        if "application/json" not in content:
            continue
        schema = _resolve(content["application/json"].get("schema", {}), document)
        if schema.get("type") == "array":
            return _object_fields(schema, document)
        properties = schema.get("properties", {})
        # 只有「results + count/has_more/next 之类兄弟字段」才是分页信封;
        # 像 ``GET /presence`` 那样只有 results 一个字段的,results 就是业务字段本身。
        if "results" in properties and PAGE_SIBLINGS & set(properties):
            return _object_fields(properties["results"], document)
        return set(properties)
    return set()


def schema_fields(schema: dict) -> dict[tuple[str, str], dict[str, set[str]]]:
    """从 OpenAPI 文档里取出每个操作的请求/响应字段。

    Args:
        schema: 整份 OpenAPI 文档(``SchemaGenerator.get_schema()`` 的返回值)。

    Returns:
        ``{(HTTP 方法, 路径): {"request": {...}, "response": {...}}}``。
    """
    found: dict[tuple[str, str], dict[str, set[str]]] = {}
    for path, item in schema.get("paths", {}).items():
        for method, operation in item.items():
            if method.lower() not in ("get", "post", "patch", "put", "delete"):
                continue
            found[(method.upper(), path)] = {
                "request": _request_fields(operation, schema),
                "response": _response_fields(operation, schema),
            }
    return found


def generate_schema() -> dict:
    """在进程内生成 OpenAPI 文档(不落盘、不碰数据库)。

    Returns:
        OpenAPI 3.0 文档字典。
    """
    from drf_spectacular.generators import SchemaGenerator

    return SchemaGenerator().get_schema(request=None, public=True)


def _diff(declared: set[str], generated: set[str]) -> tuple[set[str], set[str]]:
    """比较文档声明与生成结果,分别返回「缺的」与「多的」。

    Args:
        declared: 文档声明的字段集合。
        generated: 代码生成出来的字段集合。

    Returns:
        ``(文档有但 schema 没有, schema 有但文档没有)``。
    """
    return declared - generated, generated - declared


def find_problems(docs_dir: Path | None = None, schema: dict | None = None) -> list[str]:
    """双向比对文档字段与生成字段,列出全部不一致。

    Args:
        docs_dir: 文档目录;``None`` 表示使用默认的 ``docs/api``。
        schema: 已生成好的 OpenAPI 文档;``None`` 表示现场生成。

    Returns:
        问题描述列表;空列表表示字段级完全对齐。
    """
    declared = docs_fields(docs_dir or DOCS_DIR)
    generated = schema_fields(schema if schema is not None else generate_schema())

    problems: list[str] = []
    for key in sorted(set(declared) | set(generated)):
        method, path = key
        if key not in generated:
            problems.append(f"{method} {path}: 文档有记录,但 OpenAPI 里没有这个操作")
            continue
        if key not in declared:
            problems.append(f"{method} {path}: OpenAPI 有操作,但文档没有对应小节")
            continue
        for side, label in (("request", "请求参数"), ("response", "响应参数")):
            missing, extra = _diff(declared[key][side], generated[key][side])
            if side == "request":
                missing -= SCHEMA_INEXPRESSIBLE.get(key, set())
            problems += [
                f"{method} {path}: {label}「{name}」文档里有、OpenAPI 里没有"
                for name in sorted(missing)
            ]
            problems += [
                f"{method} {path}: {label}「{name}」OpenAPI 里有、文档里没有"
                for name in sorted(extra - ENVELOPE_FIELDS)
            ]
    return problems
