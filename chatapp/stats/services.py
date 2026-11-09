"""个人使用报告的周期口径与七项聚合。

设计要点:
    1. **周期一律是自然周期**:自然周(周一起)、自然月、自然年,时区取
       ``settings.TIME_ZONE``(``Asia/Shanghai``),与运营日报同口径;返回的
       ``start`` / ``end`` 是**含首含尾**的日期,查询时才换算成左闭右开的时刻区间;
    2. **七项指标全部落在 Django 自己的库里**。消息条数**不在其中**:消息在
       ``chatapp_im``(imserver 的库),Django 侧读不到,为此连一个跨库统计链路
       不划算;
    3. **七个计数压进同一条 SQL**:鉴权(会话版本)、资料与偏好已经固定占掉 4 条
       查询,七次独立 ``count()`` 会把单次请求顶到 11 条,超出 ``test_query_budget``
       给本接口的 8 条预算。这里把每个计数写成同一条 ``SELECT`` 里的标量子查询,
       既守住预算,也只有一个数据库往返。

注意事项:
    每个指标的口径是「**区间内的事件**」,不是「当前存量」:配对数按 ``created_at``
    (含事后被解除的配对),访客按 ``last_at``(一人一行,重复访问只刷新时间),
    关注按 ``Follow.created_at``。

关联文档:
    - 接口契约:docs/api/stats.md
"""

import calendar
from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, IntegerField, Q, Subquery, Value
from django.utils import timezone

from discovery.models import Match, Swipe, SwipeAction
from feed.models import Follow, Post, PostLike
from users.models import ProfileVisit

from .exceptions import InvalidPeriod

User = get_user_model()

PERIODS = ("week", "month", "year")
DEFAULT_PERIOD = "week"
# 指标名(即响应字段名)与顺序:接口契约里就是这七个,顺序固定便于客户端按序渲染
METRICS = ("matches", "likes_given", "likes_received", "visits",
           "posts", "post_likes", "new_followers")


def parse_period(raw) -> str:
    """校验并归一化查询参数 ``period``。

    Args:
        raw: 原始参数值,可能是 ``None`` / 空串 / 任意字符串。

    Returns:
        ``week`` / ``month`` / ``year``;缺省或空串时返回 ``DEFAULT_PERIOD``。

    Raises:
        InvalidPeriod: 取值不在三者之内。
    """
    value = (raw or "").strip().lower()
    if not value:
        return DEFAULT_PERIOD
    if value not in PERIODS:
        raise InvalidPeriod()
    return value


def period_bounds(period: str, today: date | None = None) -> tuple[date, date]:
    """算出一个自然周期的起止日期(含首含尾)。

    Args:
        period: ``week`` / ``month`` / ``year``。
        today: 参照日期;``None`` 表示取本地时区的今天(便于测试注入)。

    Returns:
        ``(start, end)`` 两个日期。``week`` 从周一算到周日,``month`` 是整月,
        ``year`` 是整年。

    Raises:
        ValueError: ``period`` 不是三个取值之一(视图层已用 ``parse_period`` 拦过,
            这里兜底防止内部调用传错)。
    """
    today = today or timezone.localdate()
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if period == "month":
        start = today.replace(day=1)
        days = calendar.monthrange(start.year, start.month)[1]
        return start, start + timedelta(days=days - 1)
    if period == "year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    raise ValueError(f"未知周期: {period}")


def period_window(period: str, today: date | None = None) -> tuple[datetime, datetime]:
    """把周期换算成带时区的左闭右开时刻区间。

    数据库里存的是 UTC 时间(``USE_TZ=True``),而「自然日」是本地时区的概念,
    所以边界必须先在 ``Asia/Shanghai`` 拼好再交给 Django 比较,不能直接拿
    ``date`` 去比对 ``DateTimeField``。

    Args:
        period: ``week`` / ``month`` / ``year``。
        today: 参照日期;``None`` 表示取本地时区的今天。

    Returns:
        ``(after, before)``:``after`` 含、``before`` 不含。
    """
    start, end = period_bounds(period, today)
    zone = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(start, time.min), zone),
            timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), zone))


def _count_subquery(rows) -> Subquery:
    """把已过滤好的查询集包成一个只返回整数的标量子查询。

    中间那句 ``annotate(_bucket=Value(1)).values("_bucket")`` 不是为了分组,而是绕开
    Django 的一条行为:只选注解时它会把主键塞进 ``GROUP BY``,``COUNT(*)`` 于是变成
    「每行 1」再被 ``LIMIT 1`` 截成一个恒为 1 的常数。显式按常量分组后才是整段
    ``COUNT(*)``。

    Args:
        rows: 已经带好过滤条件的查询集。

    Returns:
        返回单个整数的 ``Subquery``;``COUNT(*)`` 恒有结果,不需要 ``Coalesce``。
    """
    counted = (rows.order_by()
               .annotate(_bucket=Value(1)).values("_bucket")
               .annotate(total=Count("*")).values("total")[:1])
    return Subquery(counted, output_field=IntegerField())


def collect(user, period: str, today: date | None = None) -> dict[str, int]:
    """汇总当前用户在某个周期内的七项数字。

    Args:
        user: 当前登录用户;所有查询都以它为主体,不会返回他人数据。
        period: ``week`` / ``month`` / ``year``。
        today: 参照日期;``None`` 表示取本地时区的今天(便于测试注入)。

    Returns:
        七个字段的字典,键顺序与 ``METRICS`` 一致。
    """
    after, before = period_window(period, today)
    created = {"created_at__gte": after, "created_at__lt": before}
    sources = {
        # 我参与的配对:两个方向都要数(配对行按 id 升序存 user_a / user_b)
        "matches": Match.objects.filter(Q(user_a=user) | Q(user_b=user), **created),
        "likes_given": Swipe.objects.filter(swiper=user, action=SwipeAction.LIKE, **created),
        "likes_received": Swipe.objects.filter(target=user, action=SwipeAction.LIKE, **created),
        # 访客是「一人一行」的表(重复访问只刷新 last_at),所以这里数的是
        # 「区间内来看过我的人」,不是点击次数
        "visits": ProfileVisit.objects.filter(
            owner=user, last_at__gte=after, last_at__lt=before),
        "posts": Post.objects.filter(author=user, **created),
        "post_likes": PostLike.objects.filter(post__author=user, **created),
        "new_followers": Follow.objects.filter(followee=user, **created),
    }
    # 注解别名加 ``stat_`` 前缀:``posts`` / ``post_likes`` 是 User 上的反向关联名,
    # 直接用会与 Django 的字段检查冲突
    aliases = {name: f"stat_{name}" for name in sources}
    row = (User.objects.filter(pk=user.pk)
           .annotate(**{aliases[name]: _count_subquery(rows)
                        for name, rows in sources.items()})
           .values(*aliases.values()).get())
    return {name: row[aliases[name]] for name in METRICS}
