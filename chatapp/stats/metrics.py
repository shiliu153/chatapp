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

    Args:
        day: 本地自然日。

    Returns:
        ``(start, end)``:当日 ``00:00`` 与次日 ``00:00``(均为带时区的时刻)。
    """
    tz = timezone.get_current_timezone()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


def _active_users(day: date) -> set | None:
    """取某一天的活跃用户集合,区分「没采到」与「采到了但是 0 人」。

    Args:
        day: 本地自然日。

    Returns:
        账号 id 集合;当天没有活动记录(Redis 集合不存在)返回 ``None``。
    """
    if activity.daily_count(day) is None:
        return None
    return activity.daily_users(day)


def _cohort(day: date) -> set:
    """取某一天注册的用户 id 集合(留存的分母)。

    Args:
        day: 本地自然日。

    Returns:
        当日注册用户的账号 id 集合。
    """
    start, end = day_range(day)
    return set(
        User.objects.filter(date_joined__gte=start, date_joined__lt=end)
        .values_list("id", flat=True)
    )


def _retention(cohort: set, target_day: date) -> int | None:
    """算 cohort 在目标日的留存人数。

    Args:
        cohort: 首日注册的用户 id 集合。
        target_day: 目标日(次日 / 第 7 日)。

    Returns:
        ``len(cohort ∩ 目标日活跃)``;目标日没有活动记录返回 ``None``。
    """
    active = _active_users(target_day)
    if active is None:
        return None
    return len(cohort & active)


def build_snapshot(day: date) -> dict:
    """算出某一天的全部指标(只算不写库)。

    Args:
        day: 本地自然日。

    Returns:
        可直接交给 ``DailyMetric`` 的字段字典;采不到的字段为 ``None``。
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

    Args:
        day: 本地自然日。
        snapshot: 已算好的字段字典;``None`` 表示现算。命令传进来复用一次计算,
            免得同一天算两遍(消息量还要连一次 IM 库)。

    Returns:
        写入后的 ``DailyMetric`` 行。
    """
    row, _created = DailyMetric.objects.update_or_create(
        date=day, defaults=snapshot if snapshot is not None else build_snapshot(day),
    )
    return row


def fill_retention(day: date, field: str) -> bool:
    """给**已存在**的那一行补留存(「每天只跑昨天」时维持存的唯一途径)。

    Args:
        day: 待补留存的那一行对应的本地自然日。
        field: ``retention_d1`` 或 ``retention_d7``。

    Returns:
        是否真的更新了;行不存在返回 ``False``(不为补留存凭空造行)。

    Raises:
        ValueError: ``field`` 不是留存字段。
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

    Args:
        days: 取多少行,缺省 30。

    Returns:
        ``DailyMetric`` 列表,按日期倒序。
    """
    return list(DailyMetric.objects.all()[:days])


def match_rate(row: DailyMetric) -> float | None:
    """算配对率 ``matches / swipes_like``。

    Args:
        row: 一行快照。

    Returns:
        比值(``0.0`` 起,可能大于 1);分母为 0 时返回 ``None``(看板显示 ``—``)。
    """
    if not row.swipes_like:
        return None
    return row.matches / row.swipes_like
