"""``@extend_schema`` 复用的响应信封与分页参数(D-5 第 2 步)。

设计要点:
    1. 本项目几乎全是 ``@api_view`` 函数视图,序列化器在函数体里临时构造,drf-spectacular
       推断不出请求/响应体,因此字段级契约必须用 ``@extend_schema`` 显式声明;
    2. 分页响应与分页参数在十几个接口里重复出现,集中在这里定义,避免每个视图各写一份
       而彼此漂移;
    3. 参数与信封都用**工厂函数**返回新对象,不共享模块级实例 —— 生成 schema 时库可能会
       就地补全 ``OpenApiParameter`` 的字段,共享实例容易互相污染。

文件信息:
    文件名称          config/schema_helpers.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from drf_spectacular.utils import OpenApiParameter, inline_serializer
from rest_framework import serializers


def _as_list(item) -> serializers.BaseSerializer:
    """把「序列化器类」或「序列化器实例」统一成 ``many=True`` 的列表序列化器。

    参数说明:
        item: 序列化器类(如 ``PostSerializer``)或实例(``inline_serializer`` 的返回值)。

    返回参数:
        ``many=True`` 的序列化器实例。

    使用示例:
        ``_as_list(PostSerializer)``

    备注信息:
        用 ``isinstance(item, type)`` 区分「类」与「实例」;两种情况都重新实例化一份,
        不复用调用方传进来的对象。
    """
    serializer_class = item if isinstance(item, type) else type(item)
    return serializer_class(many=True)


def cursor_page(name: str, item_serializer) -> serializers.Serializer:
    """构造游标分页响应信封(``config.cursor.paginated_response`` 的形状)。

    参数说明:
        name: 组件名(必须全项目唯一)。
        item_serializer: ``results[]`` 元素的序列化器(类或实例)。

    返回参数:
        ``{count, next_cursor, has_more, results}`` 的内联序列化器。

    使用示例:
        ``cursor_page("FeedPostPage", PostSerializer)``

    备注信息:
        ``next_cursor`` 允许为 null(最后一页没有下一页);
        组件名重名会让 OpenAPI 里后定义的覆盖先定义的,因此要求全项目唯一。
    """
    return inline_serializer(name, fields={
        "count": serializers.IntegerField(),
        "next_cursor": serializers.CharField(allow_null=True),
        "has_more": serializers.BooleanField(),
        "results": _as_list(item_serializer),
    })


def offset_page(name: str, item_serializer) -> serializers.Serializer:
    """构造 offset 分页响应信封(``DefaultLimitOffsetPagination`` 的形状)。

    参数说明:
        name: 组件名(必须全项目唯一)。
        item_serializer: ``results[]`` 元素的序列化器(类或实例)。

    返回参数:
        ``{count, next, previous, results}`` 的内联序列化器。

    使用示例:
        ``offset_page("OpsReportPage", ReportSerializer)``

    备注信息:
        ``next`` / ``previous`` 允许为 null;DRF 里它们是完整 URL 字符串,
        此处按字符串声明,不做 URL 校验。
    """
    return inline_serializer(name, fields={
        "count": serializers.IntegerField(),
        "next": serializers.CharField(allow_null=True),
        "previous": serializers.CharField(allow_null=True),
        "results": _as_list(item_serializer),
    })


def cursor_params() -> list[OpenApiParameter]:
    """游标分页接口的查询参数(``limit`` + ``before``)。

    参数说明:
        无。

    返回参数:
        两个 ``OpenApiParameter``;路径参数由库自动补,不在此声明。

    使用示例:
        ``@extend_schema(parameters=cursor_params())``

    备注信息:
        每次调用返回新对象:生成 schema 时库可能就地补全参数对象,共享模块级实例会互相污染。
    """
    return [
        OpenApiParameter("limit", int, OpenApiParameter.QUERY, required=False,
                         description="每页条数,默认 20,上限 100"),
        OpenApiParameter("before", str, OpenApiParameter.QUERY, required=False,
                         description="游标,首页不传;之后原样回传上一页的 next_cursor"),
    ]


def offset_params() -> list[OpenApiParameter]:
    """offset 分页接口的查询参数(``limit`` + ``offset``)。

    参数说明:
        无。

    返回参数:
        两个 ``OpenApiParameter``。

    使用示例:
        ``@extend_schema(parameters=offset_params())``

    备注信息:
        每次调用返回新对象,理由同 ``cursor_params``;
        参数本身不写默认值,默认 20 / 0 由视图的分页类兜底。
    """
    return [
        OpenApiParameter("limit", int, OpenApiParameter.QUERY, required=False,
                         description="每页条数,默认 20,上限 100"),
        OpenApiParameter("offset", int, OpenApiParameter.QUERY, required=False,
                         description="偏移量,默认 0"),
    ]
