"""个人使用报告接口:一次返回当前用户在某个自然周期内的七项数字。

关联文档:
    - 接口契约:docs/api/stats.md
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

    Args:
        request: DRF 请求对象,支持 ``period`` 查询参数(``week`` / ``month`` / ``year``)。

    Returns:
        ``{period, start, end, matches, likes_given, likes_received, visits, posts,
        post_likes, new_followers}``;``start`` / ``end`` 是含首含尾的日期字符串。

    Raises:
        InvalidPeriod: ``period`` 不在 ``week`` / ``month`` / ``year`` 之内。
    """
    period = parse_period(request.query_params.get("period"))
    start, end = period_bounds(period)
    return Response({
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        **collect(request.user, period),
    })
