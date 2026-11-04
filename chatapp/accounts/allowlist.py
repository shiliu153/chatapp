"""准入名单的读侧:一份带短 TTL 的快照 + 写路径的显式失效。

为什么要有这一层(而不是在 ``services.ensure_phone_allowed`` 里直接查库):
    白名单闸门在「发码」与「校验」两个入口各跑一次,每次请求都查一次
    ``accounts.PhoneAllowlist`` 没必要。这里把整张表读成两个集合(启用 / 停用)
    缓存在 Django cache 里,一次请求零查询。

「立刻生效」靠什么保证:
    不靠 TTL,靠写路径调用 :func:`invalidate` —— ``/ops/`` 的加号/停用与
    种子导入命令都会显式清缓存。TTL 只是兜底(手改数据库、多进程缓存不同步时)。

注意事项:
    缓存不可用(Redis 抖动)时**不能**因此放行或拒绝:这里退化为直接查库,
    准入判断永远以数据库为准。宁可慢一次,不可漏一个人。
"""

import logging

from django.conf import settings
from django.core.cache import cache

from .models import PhoneAllowlist

logger = logging.getLogger(__name__)

# 快照缓存键;写路径一律用 invalidate() 清,不要自己去拼这个键。
ALLOWLIST_CACHE_KEY = "sms:allowlist:snapshot"


def _query_snapshot():
    """直接查库,把名单拆成「启用集合」与「停用集合」。

    Returns:
        ``(active, disabled)`` 两个 ``frozenset``;表为空时都是空集。
    """
    active = set()
    disabled = set()
    for phone, is_active in PhoneAllowlist.objects.values_list("phone", "is_active"):
        (active if is_active else disabled).add(phone)
    return frozenset(active), frozenset(disabled)


def snapshot():
    """取名单快照(优先读缓存,未命中则查库并回填)。

    Returns:
        ``(active, disabled)`` 两个 ``frozenset``。

    Raises:
        django.db.Error: 缓存未命中且数据库不可读时向上抛 —— 发码链路本就依赖
            Redis 与数据库,这里不做「出错就放行」的兜底。
    """
    try:
        cached = cache.get(ALLOWLIST_CACHE_KEY)
    except Exception:      # 缓存后端故障不影响准入判断,退化为查库
        logger.warning("[白名单] 快照缓存读取失败,改为直查数据库", exc_info=True)
        cached = None
    if isinstance(cached, tuple) and len(cached) == 2:
        return cached
    result = _query_snapshot()
    try:
        cache.set(ALLOWLIST_CACHE_KEY, result, settings.SMS_ALLOWLIST_CACHE_TTL)
    except Exception:      # 写缓存失败只影响下一次请求的性能,不影响正确性
        logger.warning("[白名单] 快照缓存写入失败", exc_info=True)
    return result


def invalidate():
    """清掉名单快照,让下一次判定立刻按最新数据库内容走。

    所有写名单的路径(``/ops/`` 加号、启停、种子导入命令)都必须调用。
    """
    try:
        cache.delete(ALLOWLIST_CACHE_KEY)
    except Exception:      # 清不掉只能靠 TTL 兜底,但要留下痕迹
        logger.warning("[白名单] 快照缓存清除失败,将依赖 TTL 兜底", exc_info=True)
