"""个人使用报告接口:一次返回当前用户在某个自然周期内的七项数字。

关联文档:
    - 接口契约:docs/api/stats.md

文件信息:
    文件名称          stats/views.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .services import PERIODS, collect, parse_period, period_bounds

STATS_SCHEMA = inline_serializer("MyStats", fields={
    "period": serializers.CharField(),
    "start": serializers.DateField(),
    "end": serializers.DateField(),
    "matches": serializers.IntegerField(),
    "likes_given": serializers.IntegerField(),
    "likes_received": serializers.IntegerField(),
    "visits": serializers.IntegerField(),
    "posts": serializers.IntegerField(),
    "post_likes": serializers.IntegerField(),
    "new_followers": serializers.IntegerField(),
})


@extend_schema(parameters=[OpenApiParameter(
    "period", str, OpenApiParameter.QUERY, required=False, enum=list(PERIODS),
    description="统计周期:week(自然周,周一起)/ month(自然月)/ year(自然年),缺省 week")],
    responses={200: STATS_SCHEMA})
@api_view(["GET"])
def my_stats(request):
    """个人使用报告(GET /api/v1/stats/me)。

    口径是「区间内发生的事件」:配对数按创建时间(解除过的也算),访客数按最近访问
    时间(一人一行去重),关注数按关注关系创建时间。**不含消息条数** —— 消息在
    imserver 的库里,Django 读不到。

    参数说明:
        request: DRF 请求对象,支持 ``period`` 查询参数(``week`` / ``month`` / ``year``)。

    返回参数:
        ``{period, start, end, matches, likes_given, likes_received, visits, posts,
        post_likes, new_followers}``;``start`` / ``end`` 是含首含尾的日期字符串。

    使用示例:
        ``GET /api/v1/stats/me?period=month``

    备注信息:
        接口路径 ``GET /api/v1/stats/me``(路由见 ``stats/urls.py``),只读、无请求体、
        无分页。``period`` 缺省或空串按 ``week``;取值非法抛 ``InvalidPeriod``
        (HTTP 400 + 业务码 ``40005``),未带令牌 401 由鉴权层拦下。七项数字全部来自
        Django 自己的库,计算逻辑在 ``stats.services.collect``;响应里的 ``start`` /
        ``end`` 是含首含尾的**日期**(不是时刻),与 ``period_bounds`` 同口径。
    """
    period = parse_period(request.query_params.get("period"))
    start, end = period_bounds(period)
    return Response({
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        **collect(request.user, period),
    })
