"""在线状态(最后活跃):Redis 时间戳,认证请求即刷新。

不依赖腾讯 IM 在线状态能力(需付费套餐,且没有「最后活跃时间」)。
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
    return f"presence:{user_id}"


def touch(user_id: int) -> None:
    """记一次活跃;失败只记日志 —— presence 是点缀,绝不拖累业务请求。"""
    try:
        cache.set(_key(user_id), int(time.time()), timeout=PRESENCE_TTL_SECONDS)
    except Exception:
        logger.warning("presence 写入失败 user_id=%s", user_id, exc_info=True)


def get_presence(user_ids: list[int]) -> dict[int, dict]:
    """批量查:{user_id: {"online": bool, "last_active_at": iso|None}}。

    无记录 / Redis 不可用 → online=False、last_active_at=None(前端不显示)。
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
