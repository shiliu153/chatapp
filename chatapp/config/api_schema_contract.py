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

文件信息:
    文件名称          config/api_schema_contract.py
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

    参数说明:
        docs_dir: 文档目录,默认 ``docs/api``。

    返回参数:
        ``{(HTTP 方法, 路径): {"request": {...}, "response": {...}}}``。
        没有参数表的接口(如 ``health``)返回空集合,表示「文档声明它没有字段」。

    使用示例:
        ``declared = docs_fields()``

    备注信息:
        实际的逐行解析在 ``_parse_doc_file``,本函数只负责遍历目录与汇总;
        分册按路径升序处理,``同 [X.Y]`` 引用因此能跨分册展开。
    """
    parsed: dict[tuple[str, str], dict[str, set[str]]] = {}
    for md in sorted(Path(docs_dir).rglob("*.md")):
        _parse_doc_file(md, parsed)
    return parsed


def _parse_doc_file(md: Path, parsed: dict[tuple[str, str], dict[str, set[str]]]) -> None:
    """解析单个分册:接口小节 → 请求/响应字段,并就地展开 ``同 [X.Y]`` 引用。

    参数说明:
        md: markdown 分册路径。
        parsed: 汇总结果(跨分册共享,原地写入)。

    返回参数:
        无返回值(结果写入 ``parsed``)。

    使用示例:
        ``_parse_doc_file(md, parsed)``

    备注信息:
        每个「请求参数 / 响应参数」标记后只取第一张表。``users.md §2.1`` 在响应表后面
        还有 ``tags[]`` / ``photos[]`` 两张子结构表,它们不是顶层字段,混进来会让门禁误报。
        代码围栏内的内容整段跳过;响应侧遇到 ``同 [X.Y]`` 时先记下引用,循环结束后
        用目标小节已解析的响应字段补齐当前接口(当前接口自己已有字段时不覆盖)。
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

    参数说明:
        schema: 可能带 ``$ref`` 的 schema 片段。
        document: 整份 OpenAPI 文档(取 ``components.schemas``)。

    返回参数:
        解析后的 schema 字典;引用不存在时返回空字典。

    使用示例:
        ``_resolve(schema, document)``

    备注信息:
        循环引用用 ``seen`` 集合防御:同一 ``$ref`` 第二次出现即返回空字典,避免死循环。
        组件名只取引用路径最后一段,因此不支持跨文件的外部引用。
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

    参数说明:
        schema: schema 片段(可能是对象、数组或 ``$ref``)。
        document: 整份 OpenAPI 文档。

    返回参数:
        顶层属性名集合;不是对象时返回空集合。

    使用示例:
        ``_object_fields(media.get("schema", {}), document)``

    备注信息:
        数组只解一层:元素本身仍是数组时不再往下解,本项目契约里没有嵌套数组;
        ``properties`` 不是字典时按空集合处理。
    """
    resolved = _resolve(schema, document)
    if resolved.get("type") == "array":
        resolved = _resolve(resolved.get("items", {}), document)
    properties = resolved.get("properties")
    return set(properties) if isinstance(properties, dict) else set()


def _request_fields(operation: dict, document: dict) -> set[str]:
    """取出一个操作「能收到的字段」:路径/查询/请求头参数 + 请求体字段。

    参数说明:
        operation: OpenAPI 的 operation 对象(某个方法)。
        document: 整份 OpenAPI 文档。

    返回参数:
        字段名集合。

    使用示例:
        ``_request_fields(operation, schema)``

    备注信息:
        ``parameters`` 不分 ``in``(path/query/header/cookie)全部计入 —— 本项目文档把
        ``post_id`` 这类路径参数写进「请求参数」表;请求体按 media type 逐个累加,
        同一字段出现在多份 media type 里只算一次。
    """
    names = {param["name"] for param in operation.get("parameters", []) if "name" in param}
    body = operation.get("requestBody", {}).get("content", {})
    for media in body.values():
        names |= _object_fields(media.get("schema", {}), document)
    return names


def _response_fields(operation: dict, document: dict) -> set[str]:
    """取出一个操作成功响应的顶层字段(分页信封会解到 ``results[]`` 的条目)。

    参数说明:
        operation: OpenAPI 的 operation 对象(某个方法)。
        document: 整份 OpenAPI 文档。

    返回参数:
        字段名集合;204 等无响应体时为空集合。

    使用示例:
        ``_response_fields(operation, schema)``

    备注信息:
        只认 ``SUCCESS_CODES``(200/201),按顺序命中第一个带 ``application/json`` 的就返回。
        只有「results 加 count/has_more/next 之类兄弟字段」才当分页信封拆开;
        像 ``GET /presence`` 那样只有 results 一个字段的,results 就是业务字段本身。
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

    参数说明:
        schema: 整份 OpenAPI 文档(``SchemaGenerator.get_schema()`` 的返回值)。

    返回参数:
        ``{(HTTP 方法, 路径): {"request": {...}, "response": {...}}}``。

    使用示例:
        ``generated = schema_fields(generate_schema())``

    备注信息:
        ``paths`` 下不是 HTTP 方法的键(如 ``parameters``)直接跳过;方法名统一转大写,
        与文档侧 ``INFO_LINE_RE`` 的口径一致。
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

    参数说明:
        无。

    返回参数:
        OpenAPI 3.0 文档字典。

    使用示例:
        ``schema = generate_schema()``

    备注信息:
        ``SchemaGenerator`` 在函数体内导入:只有门禁与测试要用生成器,放模块顶层会让
        每个引用本模块的地方都提前加载 drf-spectacular。
        传 ``request=None, public=True``,即不按请求上下文与权限过滤操作。
    """
    from drf_spectacular.generators import SchemaGenerator

    return SchemaGenerator().get_schema(request=None, public=True)


def _diff(declared: set[str], generated: set[str]) -> tuple[set[str], set[str]]:
    """比较文档声明与生成结果,分别返回「缺的」与「多的」。

    参数说明:
        declared: 文档声明的字段集合。
        generated: 代码生成出来的字段集合。

    返回参数:
        ``(文档有但 schema 没有, schema 有但文档没有)``。

    使用示例:
        ``missing, extra = _diff(declared[key]["request"], generated[key]["request"])``

    备注信息:
        只做集合差,不判空也不排序;排序与剔除豁免字段由 ``find_problems`` 负责。
    """
    return declared - generated, generated - declared


def find_problems(docs_dir: Path | None = None, schema: dict | None = None) -> list[str]:
    """双向比对文档字段与生成字段,列出全部不一致。

    参数说明:
        docs_dir: 文档目录;``None`` 表示使用默认的 ``docs/api``。
        schema: 已生成好的 OpenAPI 文档;``None`` 表示现场生成。

    返回参数:
        问题描述列表;空列表表示字段级完全对齐。

    使用示例:
        ``problems = find_problems(schema=generate_schema())``

    备注信息:
        三类问题分别报:操作只在一侧存在、请求/响应字段只在一侧存在。
        请求侧比对前先从「文档多出的」里剔除 ``SCHEMA_INEXPRESSIBLE`` 列出的字段
        (OpenAPI 3.0 表达不了 DELETE 请求体);两侧多出的字段里属于
        ``ENVELOPE_FIELDS`` 的也不算问题(分页信封由 ``conventions.md`` 统一描述)。
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
