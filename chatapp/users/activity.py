"""日活与活跃时段记录:按自然日去重的 Redis 集合,供每日运营指标快照。

``users.presence`` 只留「最后活跃时间戳」(7 天 TTL),事后**回填不出**任何一天的
DAU;这里另存按天 / 按小时的成员集合,``manage.py metrics_daily`` 才有数据可查。

设计要点:
    1. 一律用 ``get_redis_connection("default")`` 直连,**不要**混用 ``cache`` ——
       后者会套 ``chatapp:2:`` 前缀与 JSON 序列化器,``SADD`` / ``SCARD`` 写读的
       根本不是同一个键,而且这种错只在真 Redis 上才现形;
    2. 键形如 ``activity:dau:{YYYYMMDD}`` 与 ``activity:dau:{YYYYMMDD}:{HH}``,
       一律 45 天 TTL(``ACTIVITY_TTL_SECONDS``);
    3. 「一天」= ``settings.TIME_ZONE``(``Asia/Shanghai``)的自然日,切片前先把时刻
       换算到本地时区,**不要**按 UTC 切日。

注意事项:
    ``touch()`` 挂在认证热路径上(每个认证请求一次 pipeline),所有读写都吞异常只记
    warning —— 活动记录是点缀,绝不能拖累业务请求。
    45 天 TTL ⇒ DAU / 活跃时段 / 留存最多只能回看 45 天,更早的日期没有数据。
"""

import logging
from datetime import date, datetime

from django.utils import timezone as dj_timezone
from django_redis import get_redis_connection

logger = logging.getLogger(__name__)

ACTIVITY_TTL_SECONDS = 45 * 24 * 3600   # 45 天:够回填与留存计算,又不无限涨
HOURS_PER_DAY = 24


def _client():
    """取默认 Redis 连接(与缓存共用一个 DB,但键名不带缓存前缀)。

    Returns:
        django_redis 的连接对象。
    """
    return get_redis_connection("default")


def _local(at: datetime | None) -> datetime:
    """把时刻换算成 ``Asia/Shanghai`` 本地时间。

    Args:
        at: 目标时刻;``None`` 表示「现在」。naive 值按当前时区补齐。

    Returns:
        带时区的本地时刻。
    """
    if at is None:
        return dj_timezone.localtime()
    if dj_timezone.is_naive(at):
        at = dj_timezone.make_aware(at, dj_timezone.get_current_timezone())
    return dj_timezone.localtime(at)


def day_key(day: date) -> str:
    """拼出当日活跃集合的键。

    Args:
        day: 本地自然日。

    Returns:
        ``activity:dau:{YYYYMMDD}``。
    """
    return f"activity:dau:{day:%Y%m%d}"


def hour_key(day: date, hour: int) -> str:
    """拼出某个小时的活跃集合的键。

    Args:
        day: 本地自然日。
        hour: 小时(0–23),两位补零。

    Returns:
        ``activity:dau:{YYYYMMDD}:{HH}``。
    """
    return f"activity:dau:{day:%Y%m%d}:{hour:02d}"


def touch(user_id: int, at: datetime | None = None) -> None:
    """记一次活跃:往当日集合与当小时集合各 ``SADD`` 一次。

    两条 ``SADD`` 与两条 ``EXPIRE`` 压进同一个 pipeline(一个往返);失败只记日志。

    Args:
        user_id: 账号 id。
        at: 记录用的时刻,``None`` 取现在。**只为测试造历史数据**,生产路径不要传。
    """
    try:
        local = _local(at)
        day = local.date()
        dkey = day_key(day)
        hkey = hour_key(day, local.hour)
        pipe = _client().pipeline()
        pipe.sadd(dkey, int(user_id))
        pipe.expire(dkey, ACTIVITY_TTL_SECONDS)
        pipe.sadd(hkey, int(user_id))
        pipe.expire(hkey, ACTIVITY_TTL_SECONDS)
        pipe.execute()
    except Exception:
        logger.warning("activity 写入失败 user_id=%s", user_id, exc_info=True)


def daily_users(day: date) -> set:
    """取某一天的活跃用户集合。

    Args:
        day: 本地自然日。

    Returns:
        账号 id 集合;集合不存在或 Redis 不可用时是**空集**(本函数不抛异常)。
    """
    try:
        members = _client().smembers(day_key(day))
    except Exception:
        logger.warning("activity 读取失败 day=%s", day, exc_info=True)
        return set()
    return {int(member) for member in members}


def daily_count(day: date) -> int | None:
    """取某一天的活跃人数。

    区分「当天没采到」与「采到了 0 人」:键不存在返回 ``None``,看板据此显示 ``—``。
    Redis 的集合没有「存在但为空」这种状态,因此 ``SCARD == 0`` 等价于键不存在。

    Args:
        day: 本地自然日。

    Returns:
        去重人数;当天没有记录(或 Redis 不可用)返回 ``None``。
    """
    try:
        count = int(_client().scard(day_key(day)))
    except Exception:
        logger.warning("activity 计数失败 day=%s", day, exc_info=True)
        return None
    return count or None


def hourly_counts(day: date) -> list[int] | None:
    """取某一天 24 个小时各自的活跃人数。

    24 条 ``SCARD`` 走一次 pipeline;24 个键全不存在(当天没采到)返回 ``None``。

    Args:
        day: 本地自然日。

    Returns:
        长度 24 的整数列表(下标即小时);无数据或 Redis 不可用返回 ``None``。
    """
    try:
        pipe = _client().pipeline()
        for hour in range(HOURS_PER_DAY):
            pipe.scard(hour_key(day, hour))
        counts = [int(value) for value in pipe.execute()]
    except Exception:
        logger.warning("activity 小时分布读取失败 day=%s", day, exc_info=True)
        return None
    return counts if any(counts) else None
