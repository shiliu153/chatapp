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

文件信息:
    文件名称          stats/services.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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

    参数说明:
        raw: 原始参数值,可能是 ``None`` / 空串 / 任意字符串。

    返回参数:
        ``week`` / ``month`` / ``year``;缺省或空串时返回 ``DEFAULT_PERIOD``。

    使用示例:
        ``parse_period(request.query_params.get("period"))``

    备注信息:
        先 ``strip().lower()`` 再比对,所以 ``" Week "`` 与 ``"WEEK"`` 都算合法;
        ``None`` / 空串一律回落 ``DEFAULT_PERIOD``(``week``),不报错。取值不在
        ``PERIODS`` 之内抛 ``InvalidPeriod``(HTTP 400 + 业务码 ``40005``),由
        ``config.exceptions`` 统一转成错误信封。
    """
    value = (raw or "").strip().lower()
    if not value:
        return DEFAULT_PERIOD
    if value not in PERIODS:
        raise InvalidPeriod()
    return value


def period_bounds(period: str, today: date | None = None) -> tuple[date, date]:
    """算出一个自然周期的起止日期(含首含尾)。

    参数说明:
        period: ``week`` / ``month`` / ``year``。
        today: 参照日期;``None`` 表示取本地时区的今天(便于测试注入)。

    返回参数:
        ``(start, end)`` 两个日期。``week`` 从周一算到周日,``month`` 是整月,
        ``year`` 是整年。

    使用示例:
        ``period_bounds("week", date(2026, 11, 9))``

    备注信息:
        返回的是**日期**且含首含尾,换算成查询用的时刻区间由
        :func:`period_window` 负责。``week`` 用 ``today.weekday()`` 回退到周一
        (周一为 0,周日为 6);``month`` 用 ``calendar.monthrange`` 取当月天数,
        闰年 2 月自然得到 29;``year`` 固定 01-01 到 12-31。``today=None`` 时取
        ``timezone.localdate()``(本地时区的今天),测试注入固定日期即可复现。
        ``period`` 不是三个取值之一抛 ``ValueError`` —— 视图层已用
        :func:`parse_period` 拦过,这里兜底内部调用传错。
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

    参数说明:
        period: ``week`` / ``month`` / ``year``。
        today: 参照日期;``None`` 表示取本地时区的今天。

    返回参数:
        ``(after, before)``:``after`` 含、``before`` 不含。

    使用示例:
        ``period_window("month", date(2026, 11, 9))``

    备注信息:
        右边界是 ``period_bounds`` 给出末日的**次日零点**(``end + 1 天`` 的 ``00:00``),
        因此整个末日都在区间内;两个边界都用 ``timezone.make_aware`` 挂上当前时区
        (``Asia/Shanghai``)。查询侧一律写 ``created_at__gte=after, created_at__lt=before``,
        写成 ``__lte=end`` 会漏掉末日整天。
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

    参数说明:
        rows: 已经带好过滤条件的查询集。

    返回参数:
        返回单个整数的 ``Subquery``;``COUNT(*)`` 恒有结果,不需要 ``Coalesce``。

    使用示例:
        ``_count_subquery(Swipe.objects.filter(swiper=user))``

    备注信息:
        必须先 ``order_by()`` 清掉模型的默认排序:``Swipe`` / ``Match`` / ``Post`` /
        ``ProfileVisit`` 都带 ``Meta.ordering``,不清会把排序字段塞进 ``GROUP BY``,
        常量分组就退化成「每组一行」,``COUNT(*)`` 又被压成 1。``[:1]`` 让子查询最多返回
        一行,才能当标量用;``output_field=IntegerField()`` 必填,否则 Django 推断不出
        子查询类型。
    """
    counted = (rows.order_by()
               .annotate(_bucket=Value(1)).values("_bucket")
               .annotate(total=Count("*")).values("total")[:1])
    return Subquery(counted, output_field=IntegerField())


def collect(user, period: str, today: date | None = None) -> dict[str, int]:
    """汇总当前用户在某个周期内的七项数字。

    参数说明:
        user: 当前登录用户;所有查询都以它为主体,不会返回他人数据。
        period: ``week`` / ``month`` / ``year``。
        today: 参照日期;``None`` 表示取本地时区的今天(便于测试注入)。

    返回参数:
        七个字段的字典,键顺序与 ``METRICS`` 一致。

    使用示例:
        ``collect(request.user, "week")``

    备注信息:
        七个计数被压进**同一条 SQL**:外层 ``User.objects.filter(pk=user.pk)`` 加七个
        标量子查询,只发一次查询 —— 鉴权(会话版本)、资料与偏好已占掉 4 条,七次独立
        ``count()`` 会顶到 11 条、超出 ``test_query_budget`` 给本接口的 8 条预算。
        口径是「区间内发生的事件」而非当前存量:``matches`` 两个方向都数(配对行按 id
        升序存 ``user_a`` / ``user_b``)、含事后被解除的;``visits`` 按 ``last_at`` 落区间,
        访客表一人一行,数的是「区间内来看过我的人」而不是点击次数;``follows`` 按
        ``Follow.created_at``。注解别名加 ``stat_`` 前缀,``posts`` / ``post_likes``
        直接用会撞 ``User`` 上的反向关联名。消息条数**不在其中**:消息在 imserver 的库里。
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
