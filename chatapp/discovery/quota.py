"""每日喜欢额度(批次 O):按「自然日(``Asia/Shanghai``)」在 Redis 里计数的配额。

设计要点:
    1. **默认关闭**:``settings.SWIPE_DAILY_LIKE_LIMIT`` 为 0(或负数)时不计数、不读键、
       不拦请求 —— 线上不配这个值就等于「没有这个功能」,与加额度前的行为逐字节一致;
    2. **键按自然日切分**:``swipe_like:{user_id}:{yyyymmdd}``,TTL 对齐到次日 00:00,
       到点自己消失,不需要定时任务,也不需要「先删后写」;
    3. **先 INCR 再判超限**:并发时两个请求都会看到「还剩 1 次」,只有 Redis 侧的
       原子自增能裁定谁超了;被拒的那次立刻 DECR 回滚,保证「被拒的请求不计数」;
    4. **Redis 不可用时 fail-open**:额度只是防脚本的软约束,不能因为缓存抖动让所有人
       都滑不了卡(与 ``config/cache_utils.py`` 同口径),此时记一条 warning 后放行;
    5. **只给「新产生的喜欢」计数**:幂等重放(同一目标第二次提交)与 ``action=pass``
       都不占额度;撤销会把那次喜欢同时退回,否则「撤销后重滑」会被自己的额度挡住。

关联文档:
    - 接口契约:docs/api/discovery.md §3.2 / §3.9 / §3.10
    - 错误码:docs/api/errors.md(``42904``)

文件信息:
    文件名称          discovery/quota.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .exceptions import SwipeLikeQuotaExceeded

logger = logging.getLogger(__name__)


def daily_like_limit() -> int:
    """读取每日喜欢上限。

    参数说明:
        无。

    返回参数:
        上限值;``<= 0`` 表示不限(额度功能整体关闭)。

    使用示例:
        ``daily_like_limit()``

    备注信息:
        ``settings.SWIPE_DAILY_LIKE_LIMIT`` 缺失、为 ``None`` 或为空串时一律按 0 处理,即整体关闭。
    """
    return int(getattr(settings, "SWIPE_DAILY_LIKE_LIMIT", 0) or 0)


def _now() -> datetime:
    """当前时间(项目时区 ``Asia/Shanghai`` 的 aware datetime)。

    单独抽成函数是为了让测试能把「现在」挪到隔天,验证自然日切分。

    参数说明:
        无。

    返回参数:
        带时区的当前时间。

    使用示例:
        ``_now()``

    备注信息:
        ``timezone.localtime()`` 依赖 ``settings.USE_TZ`` 与 ``settings.TIME_ZONE``,
        两者一变,「自然日」的边界跟着变。
    """
    return timezone.localtime()


def _day_key(user_id: int, now: datetime) -> str:
    """当日计数键。

    参数说明:
        user_id: 账号 id。
        now: 当前时间(决定「自然日」是哪一天)。

    返回参数:
        Redis 键名 ``swipe_like:{user_id}:{yyyymmdd}``;django-redis 会自动加
        ``chatapp:2:`` 前缀与版本号,业务侧只用这一个名字。

    使用示例:
        ``_day_key(42, _now())``

    备注信息:
        键里带日期,跨自然日即换键;旧键不主动删除,靠写入时设置的 TTL 自行消失。
    """
    return f"swipe_like:{user_id}:{now.strftime('%Y%m%d')}"


def _seconds_until_tomorrow(now: datetime) -> int:
    """距次日 00:00 的秒数(至少 1)。

    参数说明:
        now: 当前时间。

    返回参数:
        秒数,用作计数键的 TTL 与 ``Retry-After``。

    使用示例:
        ``_seconds_until_tomorrow(_now())``

    备注信息:
        按 ``now`` 所在时区算次日零点;结果下限取 1,避免 TTL 为 0 让计数键立刻失效。
    """
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


def likes_used(user_id: int) -> int:
    """今天已经用掉的喜欢次数。

    参数说明:
        user_id: 账号 id。

    返回参数:
        已用次数;额度关闭或 Redis 不可用时为 0。

    使用示例:
        ``likes_used(42)``

    备注信息:
        额度关闭时不读键直接返回 0;Redis 异常记 ``swipe_quota_read_failed`` 后同样返回 0(fail-open)。
    """
    if daily_like_limit() <= 0:
        return 0
    try:
        return int(cache.get(_day_key(user_id, _now())) or 0)
    except Exception:  # noqa: BLE001  Redis 抖动不该让查询接口失败
        logger.warning("swipe_quota_read_failed", extra={"user_id": user_id})
        return 0


def quota_snapshot(user_id: int) -> dict:
    """当前账号的额度快照(``GET /discovery/quota`` 直接返回它)。

    只读一次 Redis:``likes_remaining`` 由已用次数推出,不再单独查一遍计数。

    参数说明:
        user_id: 账号 id。

    返回参数:
        ``{"like_limit": int, "likes_used": int, "likes_remaining": int|None}``;
        额度关闭时 ``likes_used`` 为 0、``likes_remaining`` 为 ``None``。

    使用示例:
        ``quota_snapshot(42)``

    备注信息:
        ``likes_remaining`` 下限取 0:回滚与并发自增交错时已用次数可能短暂超过上限。
    """
    limit = daily_like_limit()
    used = likes_used(user_id)
    return {
        "like_limit": limit,
        "likes_used": used,
        "likes_remaining": None if limit <= 0 else max(0, limit - used),
    }


def consume_like(user_id: int) -> None:
    """占用一次喜欢额度;已用完则抛 :class:`SwipeLikeQuotaExceeded`。

    调用点必须在「真正写入 Swipe 行之前」:超限的请求不落库,客户端重试也不会
    变成一条被计入额度的记录。

    参数说明:
        user_id: 账号 id。

    返回参数:
        无返回值;超限以异常形式抛出。

    使用示例:
        ``consume_like(request.user.id)``

    备注信息:
        先 INCR 再判超限,被拒时立刻 DECR 回滚,保证「被拒的请求不计数」。
        额度关闭(``<= 0``)时直接返回;Redis 异常记 ``swipe_quota_unavailable`` 后放行(fail-open)。
        当日额度用完抛 ``SwipeLikeQuotaExceeded``(``429`` + ``42904``,带 ``Retry-After``)。
    """
    limit = daily_like_limit()
    if limit <= 0:
        return
    now = _now()
    key = _day_key(user_id, now)
    ttl = _seconds_until_tomorrow(now)
    try:
        # add 只在键不存在时写入,保证 TTL 落在「当天」这个边界上;
        # 之后的 incr 不会改 TTL(Redis INCR 保留过期时间)。
        cache.add(key, 0, ttl)
        used = int(cache.incr(key))
    except Exception:  # noqa: BLE001
        logger.warning("swipe_quota_unavailable", extra={"user_id": user_id})
        return
    if used > limit:
        try:
            cache.decr(key)     # 回滚:被拒的这次不计数,否则重试永远进不来
        except Exception:  # noqa: BLE001
            logger.warning("swipe_quota_rollback_failed", extra={"user_id": user_id})
        raise SwipeLikeQuotaExceeded(wait=ttl)


def refund_like(user_id: int) -> None:
    """把一次喜欢额度还回去(撤销滑卡时调用)。

    只减到 0 为止:撤销可能跨越自然日(划在 23:59:59、撤在 00:00:01),
    此时当天键里本来就没有这一笔,扣成负数会让「今天的剩余次数」凭空变多。

    参数说明:
        user_id: 账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``refund_like(request.user.id)``

    备注信息:
        额度关闭时不读键直接返回;Redis 异常记 ``swipe_quota_refund_failed`` 后忽略,不影响主流程。
    """
    if daily_like_limit() <= 0:
        return
    try:
        key = _day_key(user_id, _now())
        if int(cache.get(key) or 0) <= 0:
            return
        cache.decr(key)
    except Exception:  # noqa: BLE001
        logger.warning("swipe_quota_refund_failed", extra={"user_id": user_id})
