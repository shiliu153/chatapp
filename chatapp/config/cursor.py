"""复合游标(keyset)分页:游标 = (排序时间字段, 主键),编码成一个不透明字符串。

为什么不用 ``limit/offset``
--------------------------
广场动态流、喜欢我的人、谁看过我、配对列表都是「按时间倒序、头部持续插入」的列表。
offset 分页在这种列表上必然出错:第 1 页读完、对方发了一条新动态,第 2 页
(``offset=20``)就会把第 1 页的最后一条再吐一次,同时漏掉真正该出现的那一条;
而且深翻页时 MySQL 仍要跳读前 N 行(2026-11-03 实测 ``offset`` 越深越慢)。
游标记住「上一页最后一行是谁」,下一页从它之后开始,与页深无关、与期间插入无关。

协议
----
- 请求:``?limit=20&before=<不透明游标>``(首页不带 ``before``);
- 响应:``{"count": 137, "next_cursor": "…" | null, "has_more": true, "results": […]}`;
- ``count`` 仍然保留:App 与网页端都拿它算「还有没有下一页」和入口角标;
- **``offset`` 保留兼容**:请求里带 ``offset`` 且不带 ``before`` 时走旧的
  ``LimitOffsetPagination`` 路径,响应形状也保持 ``count/next/previous/results``。
  这样还在用老版本客户端的设备不会在翻页时卡死(新客户端一律用游标)。

游标为什么是 base64
-------------------
明文 ``<created_at>_<id>`` 有两个坑:ISO 时间里的 ``+08:00`` 放进 query 会被解码成空格;
``_`` 分隔也会诱导客户端自己拼游标。base64url 之后它就是一段「原样回传」的票据,
客户端不需要、也不应该解析它。
"""

import base64
import binascii
from datetime import datetime, timezone
from typing import NamedTuple

from django.db.models import Q
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .pagination import DefaultLimitOffsetPagination
from .params import int_param

INVALID_CURSOR_MESSAGE = "分页游标无效,请从第一页重新拉取"


def _invalid_cursor() -> ValidationError:
    """构造一个 400 游标错误(由全局异常处理转成统一错误信封)。"""
    return ValidationError(INVALID_CURSOR_MESSAGE)


def encode_cursor(value: datetime, pk: int) -> str:
    """把「排序时间 + 主键」编码成不透明游标。

    Args:
        value: 该行的排序字段值(如 ``created_at`` / ``last_at``)。
        pk: 该行主键,时间相同时用它定序。

    Returns:
        base64url 字符串(去掉 ``=`` 填充,可安全放进 query)。
    """
    if value is not None and value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    raw = f"{value.isoformat() if value is not None else ''}|{pk}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(raw: str) -> tuple[datetime, int]:
    """解析 :func:`encode_cursor` 产出的游标。

    Args:
        raw: 客户端原样回传的游标字符串。

    Returns:
        ``(排序时间, 主键)``。

    Raises:
        ValidationError: 游标不是 base64、结构不对、时间或主键不合法(统一 400)。
    """
    padded = raw + "=" * (-len(raw) % 4)
    try:
        text = base64.urlsafe_b64decode(padded).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise _invalid_cursor() from error
    value_text, separator, pk_text = text.rpartition("|")
    if not separator:
        raise _invalid_cursor()
    try:
        return datetime.fromisoformat(value_text), int(pk_text)
    except (TypeError, ValueError) as error:
        raise _invalid_cursor() from error


def raw_param(request, name: str):
    """读取原始查询参数(兼容 DRF 请求与普通 Django 请求)。

    Args:
        request: DRF 请求(有 ``query_params``)或 Django 请求(只有 ``GET``)。
        name: 参数名。

    Returns:
        原始字符串;不存在时返回 ``None``。
    """
    source = getattr(request, "query_params", None)
    if source is None:
        source = request.GET
    return source.get(name)


def wants_legacy_offset(request) -> bool:
    """判断这次请求是否走旧的 offset 分页(老客户端兼容口径)。

    只有「带了 ``offset`` 且没带 ``before``」才算旧客户端:新客户端首页两个都不带。

    Args:
        request: DRF/Django 请求对象。

    Returns:
        需要走 ``LimitOffsetPagination`` 时返回 ``True``。
    """
    return raw_param(request, "before") in (None, "") and raw_param(request, "offset") is not None


def read_before(request) -> tuple[datetime, int] | None:
    """取出请求里的游标(没有游标返回 ``None``,表示第一页)。

    Args:
        request: DRF/Django 请求对象。

    Returns:
        ``(排序时间, 主键)`` 或 ``None``。

    Raises:
        ValidationError: 游标格式不合法(400)。
    """
    raw = raw_param(request, "before")
    if raw is None or raw == "":
        return None
    return decode_cursor(raw)


def apply_before(queryset, field: str, cursor: tuple[datetime, int]):
    """把游标条件加到查询集上(``(field, pk) < (值, 主键)`` 的 keyset 语义)。

    Args:
        queryset: 已按 ``-field, -pk`` 排序的查询集。
        field: 排序时间字段名。
        cursor: :func:`read_before` 返回的游标。

    Returns:
        只保留「排在游标之后」的行的查询集。
    """
    value, pk = cursor
    return queryset.filter(Q(**{f"{field}__lt": value})
                           | Q(**{field: value, "pk__lt": pk}))


class CursorPage(NamedTuple):
    """一页游标分页的结果。

    Attributes:
        rows: 当页的行(最多 ``limit`` 条)。
        next_cursor: 下一页的游标;没有下一页时为 ``None``。
        has_more: 是否还有下一页。
    """

    rows: list
    next_cursor: str | None
    has_more: bool


def slice_page(request, queryset, *, field: str = "created_at", default_limit: int = 20,
               max_limit: int = 100) -> CursorPage:
    """按游标切一页出来(多取一条判断 ``has_more``)。

    Args:
        request: DRF 请求对象,提供 ``limit`` 与 ``before``。
        queryset: **已经排序**的查询集(必须是 ``-field, -pk``,否则游标会漏行)。
        field: 排序时间字段名,游标取它的值与主键。
        default_limit: 缺省每页条数。
        max_limit: 单页上限(越界收敛,不报错)。

    Returns:
        当页的 ``CursorPage``。
    """
    limit = int_param(request, "limit", default=default_limit, minimum=1, maximum=max_limit)
    before = read_before(request)
    if before is not None:
        queryset = apply_before(queryset, field, before)
    rows = list(queryset[:limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(getattr(last, field), last.pk)
    return CursorPage(rows=rows, next_cursor=next_cursor, has_more=has_more)


def cursor_body(results, *, count: int, next_cursor: str | None, has_more: bool) -> dict:
    """拼出游标分页的响应体(统一形状,便于「两段式取数」的接口复用)。

    Args:
        results: 已序列化的当页数据。
        count: 该列表的可见总数。
        next_cursor: 下一页游标,没有下一页时为 ``None``。
        has_more: 是否还有下一页。

    Returns:
        ``{"count": …, "next_cursor": …, "has_more": …, "results": …}``。
    """
    return {"count": count, "next_cursor": next_cursor, "has_more": has_more,
            "results": results}


def paginated_response(request, queryset, serialize, *, field: str = "created_at",
                       default_limit: int = 20, max_limit: int = 100) -> Response:
    """游标分页的标准响应(带老的 offset 兼容分支)。

    Args:
        request: DRF 请求对象。
        queryset: 已排序的查询集。
        serialize: 把「当页行列表」转成可序列化数据的回调(通常是序列化器)。
        field: 排序时间字段名。
        default_limit: 缺省每页条数。
        max_limit: 单页上限。

    Returns:
        游标模式下是 ``{count, next_cursor, has_more, results}``;
        ``offset`` 兼容模式下是 ``{count, next, previous, results}``。
    """
    if wants_legacy_offset(request):
        paginator = DefaultLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(serialize(page))
    page = slice_page(request, queryset, field=field, default_limit=default_limit,
                      max_limit=max_limit)
    return Response(cursor_body(serialize(page.rows), count=queryset.count(),
                                next_cursor=page.next_cursor, has_more=page.has_more))
