"""在线状态(最后活跃):Redis 时间戳,认证请求即刷新。

设计要点:
    不依赖腾讯 IM 的在线状态能力(需付费套餐,且没有「最后活跃时间」)。
    「在线」= 最近 ``ONLINE_WINDOW_SECONDS`` 秒内有过认证请求 —— 客户端 45 秒一次
    心跳,窗口取 2 倍多一点留余量。

注意事项:
    在线状态是**公开信息**,不依赖配对关系,任何登录用户都能查询他人。
    所有读写都吞异常只记日志:presence 是点缀,绝不能拖累业务请求。

文件信息:
    文件名称          users/presence.py
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
import time
from datetime import datetime, timezone as dt_timezone

from django.core.cache import cache
from django.utils import timezone as dj_timezone

from . import activity

logger = logging.getLogger(__name__)

PRESENCE_TTL_SECONDS = 7 * 24 * 3600   # 最后活跃最多记 7 天,更久视为未知
ONLINE_WINDOW_SECONDS = 120            # 最近 2 分钟内有活动 = 在线(45s 心跳 ×2 + 余量)
PRESENCE_MAX_IDS = 100                 # 单次批量查询上限


def _key(user_id: int) -> str:
    """拼出该用户的在线状态缓存键。

    参数说明:
        user_id: 账号 id。

    返回参数:
        Redis 键名。

    使用示例:
        ``_key(42)``

    备注信息:
        走 ``django.core.cache`` 的键前缀与序列化(与 ``activity`` 的直连风格不同),
        不要拿它去拼裸 Redis 命令。
    """
    return f"presence:{user_id}"


def touch(user_id: int) -> None:
    """记一次活跃;失败只记日志 —— presence 是点缀,绝不拖累业务请求。

    这是全项目**唯一**「有认证请求」的证据点(``accounts.authentication`` 认证通过即
    调它),因此日活 / 活跃时段的记录也接在这里(见 ``users.activity``):口径天然一致,
    不必再改 ``authentication.py``。

    参数说明:
        user_id: 账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``touch(user.id)``

    备注信息:
        写的是 Unix 秒时间戳,TTL 7 天;末尾顺手调 ``activity.touch``(它自己吞异常,
        这里不重复包 try)。
    """
    try:
        cache.set(_key(user_id), int(time.time()), timeout=PRESENCE_TTL_SECONDS)
    except Exception:
        logger.warning("presence 写入失败 user_id=%s", user_id, exc_info=True)
    # activity.touch 内部自己吞异常,这里不需要再包一层
    activity.touch(user_id)


def clear(user_id: int) -> None:
    """注销账号时抹掉在线痕迹;失败只记日志。

    参数说明:
        user_id: 账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``clear(user.id)``

    备注信息:
        由 ``users.services.delete_account`` 在事务提交后调用;
        这里只清 presence 键,``activity`` 的按日集合按 TTL 自然过期。
    """
    try:
        cache.delete(_key(user_id))
    except Exception:
        logger.warning("presence 清理失败 user_id=%s", user_id, exc_info=True)


def get_presence(user_ids: list[int]) -> dict[int, dict]:
    """批量查:{user_id: {"online": bool, "last_active_at": iso|None}}。

    无记录 / Redis 不可用 → online=False、last_active_at=None(前端不显示)。

    参数说明:
        user_ids: 待查询的账号 id 列表。

    返回参数:
        以账号 id 为键的在线状态字典;每个 id 都有条目。

    使用示例:
        ``get_presence([8, 21])``

    备注信息:
        用一次 ``cache.get_many`` 批量取,不逐 id 查询;``last_active_at`` 是带
        ``+08:00`` 的 ISO 字符串,Redis 不可用时整个结果按「全部离线」返回。
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
    """把 Unix 时间戳转成本地时区 ISO 字符串(+08:00)。

    参数说明:
        ts: Unix 秒时间戳。

    返回参数:
        带时区偏移的 ISO 8601 字符串。

    使用示例:
        ``_iso(1763000000)``

    备注信息:
        前端 ``DateTime.parse`` 可直接解析;偏移取 ``settings.TIME_ZONE``,
        与「在线」的 120 秒窗口口径无关。
    """
    return dj_timezone.localtime(
        datetime.fromtimestamp(ts, tz=dt_timezone.utc)).isoformat()
