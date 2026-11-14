"""每日运营指标的口径与落库:一天一行,幂等 upsert。

``manage.py metrics_daily`` 的唯一算数入口;看板(``/ops/metrics/``)只读这里写出的
``DailyMetric``,不在页面里算实时指标。

设计要点:
    1. **一天 = ``settings.TIME_ZONE``(``Asia/Shanghai``)自然日 ``[00:00, 次日 00:00)``**;
       换算成查询用的左闭右开 aware datetime 一律走 :func:`day_range`,不要用
       ``datetime.now()`` 或按 UTC 切日;
    2. **留存按「首日注册 cohort」算**:分母是当日注册用户的 id 集合,分子是这批人里
       目标日仍然活跃的人数。不要拿「当日活跃」反推 —— 分母不同,数字没法解释;
    3. ``None`` 表示「当天没采到」(Redis 集合不存在 / IM 库读不到),与「采到了 0」
       严格区分,看板据此渲染 ``—``。

注意事项:
    ``profiles_completed`` 只能按**当前** ``Profile.status`` 近似 —— ``Profile`` 没有
    ``completed_at``,回填历史日期时算的是「这些人**现在**完善没完善」;这是已知近似。
    DAU / 活跃时段 / 留存依赖 ``users.activity`` 的 45 天 TTL,更早的日期回填不出来。

关联文档:
    - 运维手册:docs/ops/runbook.md §9「每日运营指标快照」

文件信息:
    文件名称          stats/metrics.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from discovery.models import Match, Swipe, SwipeAction
from users import activity
from users.models import Profile, ProfileStatus

from . import im_source
from .models import DailyMetric

User = get_user_model()

RETENTION_FIELDS = {"retention_d1": 1, "retention_d7": 7}
DEFAULT_RECENT_DAYS = 30


def day_range(day: date) -> tuple:
    """把 ``Asia/Shanghai`` 自然日换算成左闭右开的 aware datetime 区间。

    参数说明:
        day: 本地自然日。

    返回参数:
        ``(start, end)``:当日 ``00:00`` 与次日 ``00:00``(均为带时区的时刻)。

    使用示例:
        ``day_range(date(2026, 11, 2))``

    备注信息:
        时区取 ``timezone.get_current_timezone()``(即 ``settings.TIME_ZONE``,
        ``Asia/Shanghai``),直接用 ``datetime.combine(..., tzinfo=tz)`` 挂上时区,
        不再走 ``make_aware``;区间**左闭右开**,``end`` 是次日零点、不含。所有按日切分的
        查询都必须经过本函数 —— 用 ``datetime.now()`` 或按 UTC 切日会把 23:00 之后的
        数据算到另一天。
    """
    tz = timezone.get_current_timezone()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


def _active_users(day: date) -> set | None:
    """取某一天的活跃用户集合,区分「没采到」与「采到了但是 0 人」。

    参数说明:
        day: 本地自然日。

    返回参数:
        账号 id 集合;当天没有活动记录(Redis 集合不存在)返回 ``None``。

    使用示例:
        ``_active_users(date(2026, 11, 2))``

    备注信息:
        先问 ``activity.daily_count(day)``:它对「当天没有任何记录」返回 ``None``
        (Redis 集合没有「存在但为空」这种状态,``SCARD == 0`` 即视为没采到),只有它
        不是 ``None`` 时才去取集合 —— 这一步是 ``dau`` 能区分「没采到」与「采到了但是
        0 人」的唯一依据。数据落在 Redis(``users.activity``,``ACTIVITY_TTL_SECONDS``
        = 45 天),更早的日期回填不出来。
    """
    if activity.daily_count(day) is None:
        return None
    return activity.daily_users(day)


def _cohort(day: date) -> set:
    """取某一天注册的用户 id 集合(留存的分母)。

    参数说明:
        day: 本地自然日。

    返回参数:
        当日注册用户的账号 id 集合。

    使用示例:
        ``_cohort(date(2026, 11, 2))``

    备注信息:
        按 ``User.date_joined`` 落 ``[当日 00:00, 次日 00:00)`` 取,不用 ``Profile`` 的
        创建时间 —— 留存的分母必须是「当天注册的账号」。同一个 cohort 被 ``new_users`` /
        ``profiles_completed`` / 两个留存字段共用,``build_snapshot`` 里只查一次。
    """
    start, end = day_range(day)
    return set(
        User.objects.filter(date_joined__gte=start, date_joined__lt=end)
        .values_list("id", flat=True)
    )


def _retention(cohort: set, target_day: date) -> int | None:
    """算 cohort 在目标日的留存人数。

    参数说明:
        cohort: 首日注册的用户 id 集合。
        target_day: 目标日(次日 / 第 7 日)。

    返回参数:
        ``len(cohort ∩ 目标日活跃)``;目标日没有活动记录返回 ``None``。

    使用示例:
        ``_retention(_cohort(day), day + timedelta(days=1))``

    备注信息:
        分子只数 cohort 里在目标日仍然活跃的人,**不能**拿目标日的活跃总数或
        「当日活跃里有多少老用户」反推 —— 分母不同,数字没法解释。目标日活跃集合
        采不到时返回 ``None`` 而不是 0(看板据此显示 ``—``)。
    """
    active = _active_users(target_day)
    if active is None:
        return None
    return len(cohort & active)


def build_snapshot(day: date) -> dict:
    """算出某一天的全部指标(只算不写库)。

    参数说明:
        day: 本地自然日。

    返回参数:
        可直接交给 ``DailyMetric`` 的字段字典;采不到的字段为 ``None``。

    使用示例:
        ``build_snapshot(date(2026, 11, 2))``

    备注信息:
        数据来源分三处:滑卡 / 配对 / 注册 / 资料走 Django 自己的 MySQL(``swipes_like``
        与 ``swipes_pass`` 用一次 ``aggregate`` 取回,配对按 ``Match.created_at``、
        含事后被解除的);``dau`` / ``active_hours`` / 两个留存走 Redis 的
        ``users.activity``;``messages`` 走 :func:`stats.im_source.count_messages`
        (imserver 的 ``chatapp_im`` 库)。``profiles_completed`` 只能按**当前**
        ``Profile.status`` 近似,``Profile`` 没有 ``completed_at``。采不到的字段一律
        ``None``,与「采到了 0」严格区分。
    """
    start, end = day_range(day)
    cohort = _cohort(day)
    swipe_counts = Swipe.objects.filter(created_at__gte=start, created_at__lt=end).aggregate(
        like=Count("id", filter=Q(action=SwipeAction.LIKE)),
        passed=Count("id", filter=Q(action=SwipeAction.PASS)),
    )
    active = _active_users(day)
    return {
        "dau": len(active) if active is not None else None,
        "new_users": len(cohort),
        "profiles_completed": Profile.objects.filter(
            user_id__in=cohort, status=ProfileStatus.COMPLETE,
        ).count(),
        "swipes_like": swipe_counts["like"] or 0,
        "swipes_pass": swipe_counts["passed"] or 0,
        "matches": Match.objects.filter(created_at__gte=start, created_at__lt=end).count(),
        "messages": im_source.count_messages(day),
        "active_hours": activity.hourly_counts(day),
        "retention_d1": _retention(cohort, day + timedelta(days=1)),
        "retention_d7": _retention(cohort, day + timedelta(days=7)),
    }


def save_snapshot(day: date, snapshot: dict | None = None) -> DailyMetric:
    """算出并写入某一天的快照(``update_or_create``,同一天重跑覆盖而不新增)。

    参数说明:
        day: 本地自然日。
        snapshot: 已算好的字段字典;``None`` 表示现算。命令传进来复用一次计算,
            免得同一天算两遍(消息量还要连一次 IM 库)。

    返回参数:
        写入后的 ``DailyMetric`` 行。

    使用示例:
        ``save_snapshot(date(2026, 11, 2))``

    备注信息:
        幂等靠 ``DailyMetric.date`` 上的唯一约束:同一天跑几次都只有一行,``defaults``
        整字典覆盖旧值(不是增量累加),所以数据修正后直接重跑即可。``snapshot`` 传入时
        原样写库,不做键校验 —— 多一个 ``DailyMetric`` 上没有的键会直接抛
        ``TypeError``,少键则用字段缺省值。
    """
    row, _created = DailyMetric.objects.update_or_create(
        date=day, defaults=snapshot if snapshot is not None else build_snapshot(day),
    )
    return row


def fill_retention(day: date, field: str) -> bool:
    """给**已存在**的那一行补留存(「每天只跑昨天」时维持存的唯一途径)。

    参数说明:
        day: 待补留存的那一行对应的本地自然日。
        field: ``retention_d1`` 或 ``retention_d7``。

    返回参数:
        是否真的更新了;行不存在返回 ``False``(不为补留存凭空造行)。

    使用示例:
        ``fill_retention(date(2026, 11, 2), "retention_d1")``

    备注信息:
        「每天只跑昨天」时,昨天的次日留存要等后天那次运行才算得出来,而那次运行的窗口
        里没有昨天 —— 所以命令在窗口之外单独补一次,入口就是本函数。只 ``update`` 目标
        字段(``retention_d1`` 补完不动 ``retention_d7``);目标日仍无活跃记录时把该字段
        写成 ``None``。``field`` 不在 ``RETENTION_FIELDS`` 里抛 ``ValueError``,防止把
        任意列名拼进 ``update(**{field: value})``。
    """
    if field not in RETENTION_FIELDS:
        raise ValueError(f"未知的留存字段:{field}")
    if not DailyMetric.objects.filter(date=day).exists():
        return False
    value = _retention(_cohort(day), day + timedelta(days=RETENTION_FIELDS[field]))
    DailyMetric.objects.filter(date=day).update(**{field: value})
    return True


def recent_rows(days: int = DEFAULT_RECENT_DAYS) -> list:
    """取最近 ``days`` 天的快照(看板用,一条 SQL 取完)。

    参数说明:
        days: 取多少行,缺省 30。

    返回参数:
        ``DailyMetric`` 列表,按日期倒序。

    使用示例:
        ``recent_rows(7)``

    备注信息:
        倒序来自 ``DailyMetric.Meta.ordering = ["-date"]``,本函数不再拼 ``order_by``;
        切片直接变成 ``LIMIT``,只发一条 SQL。取的是「最近 N **行**」,不是「最近 N 天」:
        中间缺采的日子会少一行,不补空行。
    """
    return list(DailyMetric.objects.all()[:days])


def match_rate(row: DailyMetric) -> float | None:
    """算配对率 ``matches / swipes_like``。

    参数说明:
        row: 一行快照。

    返回参数:
        比值(``0.0`` 起,可能大于 1);分母为 0 时返回 ``None``(看板显示 ``—``)。

    使用示例:
        ``match_rate(row)``

    备注信息:
        分子是当天新建配对数、分母是当天的「喜欢」数,两者口径不同 —— 一次配对可能由
        对方的喜欢促成,所以比值会大于 1,不要当百分比直接乘 100 展示;分母为 0(当天
        没人喜欢)时返回 ``None`` 而不是 0,避免看板出现「0% 配对率」的误导。
    """
    if not row.swipes_like:
        return None
    return row.matches / row.swipes_like
