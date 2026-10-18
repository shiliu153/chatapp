"""在线状态(最后活跃):Redis 时间戳,认证请求即刷新。

设计要点:
    不依赖腾讯 IM 的在线状态能力(需付费套餐,且没有「最后活跃时间」)。
    「在线」= 最近 ``ONLINE_WINDOW_SECONDS`` 秒内有过认证请求 —— 客户端 45 秒一次
    心跳,窗口取 2 倍多一点留余量。

注意事项:
    在线状态是**公开信息**,不依赖配对关系,任何登录用户都能查询他人。
    所有读写都吞异常只记日志:presence 是点缀,绝不能拖累业务请求。
"""
import logging
import time
from datetime import datetime, timezone as dt_timezone

from django.core.cache import cache
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)

PRESENCE_TTL_SECONDS = 7 * 24 * 3600   # 最后活跃最多记 7 天,更久视为未知
ONLINE_WINDOW_SECONDS = 120            # 最近 2 分钟内有活动 = 在线(45s 心跳 ×2 + 余量)
PRESENCE_MAX_IDS = 100                 # 单次批量查询上限


def _key(user_id: int) -> str:
    """拼出该用户的在线状态缓存键。

    Args:
        user_id: 账号 id。

    Returns:
        Redis 键名。
    """
    return f"presence:{user_id}"


def touch(user_id: int) -> None:
    """记一次活跃;失败只记日志 —— presence 是点缀,绝不拖累业务请求。

    Args:
        user_id: 账号 id。
    """
    try:
        cache.set(_key(user_id), int(time.time()), timeout=PRESENCE_TTL_SECONDS)
    except Exception:
        logger.warning("presence 写入失败 user_id=%s", user_id, exc_info=True)


def clear(user_id: int) -> None:
    """注销账号时抹掉在线痕迹;失败只记日志。

    Args:
        user_id: 账号 id。
    """
    try:
        cache.delete(_key(user_id))
    except Exception:
        logger.warning("presence 清理失败 user_id=%s", user_id, exc_info=True)


def get_presence(user_ids: list[int]) -> dict[int, dict]:
    """批量查:{user_id: {"online": bool, "last_active_at": iso|None}}。

    无记录 / Redis 不可用 → online=False、last_active_at=None(前端不显示)。

    Args:
        user_ids: 待查询的账号 id 列表。

    Returns:
        以账号 id 为键的在线状态字典;每个 id 都有条目。
    """
    now_ts = int(time.time())
    result = {uid: {"online": False, "last_active_at": None} for uid in user_ids}
    try:
        values = cache.get_many([_key(uid) for uid in user_ids])
    except Exception:
        logger.warning("presence 查询失败", exc_info=True)
        return result
    for uid in user_ids:
        ts = values.get(_key(uid))
        if ts is None:
            continue
        ts = int(ts)
        result[uid] = {
            "online": now_ts - ts <= ONLINE_WINDOW_SECONDS,
            "last_active_at": _iso(ts),
        }
    return result


def _iso(ts: int) -> str:
    """本地时区 ISO(+08:00),前端 DateTime.parse 直接可用。"""
    return dj_timezone.localtime(
        datetime.fromtimestamp(ts, tz=dt_timezone.utc)).isoformat()
