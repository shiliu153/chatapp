"""缓存三防 + 版本化失效。

设计要点:
    1. **Cache-Aside**:读时回填;写路径「升版本 + 删 key」。
    2. **版本号是主失效手段**:缓存键里带版本,写路径只把版本 +1,旧键立刻不可达,
       不存在「删了 key 又被并发读回填一份脏数据」的窗口;删除只是顺手回收内存。
    3. **三防**:
       - 穿透:查库为空也缓存一个空值哨兵(短 TTL),避免同一个空结果反复打库;
       - 击穿:回填前抢 Redis 的 ``SETNX`` 锁,只有一个请求查库,其余短暂等待;
       - 雪崩:TTL 加 ±10% 抖动,避免同一批键同时过期。
    4. **fail-open**:Redis 不可用时直接查库。缓存是加速手段,不能把可用性拖下水。
"""

import logging
import random
import time

from django.core.cache import cache

from . import metrics

logger = logging.getLogger("chatapp.cache")

# 空值哨兵:用字符串而不是 None,避免与「未命中」混淆(django-redis 会 pickle 它)。
NULL = "__null__"


def version(name: str) -> int:
    """读取一个版本号(不存在视为 0)。

    Args:
        name: 版本名,如 ``disc:ver:42``。

    Returns:
        当前版本;Redis 异常时返回 0(等价于退化为无缓存版本)。
    """
    try:
        return int(cache.get(name) or 0)
    except Exception:  # noqa: BLE001  Redis 抖动不应该让请求失败
        metrics.CACHE_ERRORS.labels(name="version").inc()
        return 0


def bump_version(name: str) -> int:
    """版本号 +1;键不存在时先原子地建到 0 再 INCR。

    注意不能「先 get 再 set」:并发首次写入时多个线程会各自 ``set 1``,
    把别人已经加上去的计数覆盖掉(经典丢失更新)。``cache.add`` 是原子的,
    只有第一个线程能建成,之后的线程都走 INCR。

    Args:
        name: 版本名。

    Returns:
        递增后的版本;Redis 异常时返回 0(调用方无需感知)。
    """
    try:
        cache.add(name, 0, None)
        return int(cache.incr(name))
    except Exception:  # noqa: BLE001
        metrics.CACHE_ERRORS.labels(name="bump").inc()
        logger.warning("bump_version_failed", extra={"name": name})
        return 0


def ttl_with_jitter(ttl: int, ratio: float = 0.1) -> int:
    """给 TTL 加 ±ratio 的抖动,防止同批键同时过期(雪崩)。

    Args:
        ttl: 基础 TTL(秒)。
        ratio: 抖动比例,0.1 表示 ±10%。

    Returns:
        抖动后的 TTL,至少 1 秒。
    """
    delta = ttl * ratio
    return max(1, int(round(ttl + random.uniform(-delta, delta))))


def get_or_load(key: str, ttl: int, loader, name: str = "default"):
    """Cache-Aside 读取:命中返回缓存,未命中回填并返回。

    Args:
        key: 缓存键(调用方负责把版本号拼进去)。
        ttl: 基础过期时间(秒),实际写入时加抖动。
        loader: 未命中时的查库函数,返回任意可 pickle 的值。
        name: 指标标签(如 ``candidates``)。

    Returns:
        ``loader`` 的返回值;缓存了空值哨兵时返回 ``None``。
    """
    try:
        cached = cache.get(key)
    except Exception:  # noqa: BLE001
        metrics.CACHE_ERRORS.labels(name=name).inc()
        return loader()

    if cached is not None:
        if cached == NULL:
            metrics.CACHE_HITS.labels(name=name).inc()
            return None
        metrics.CACHE_HITS.labels(name=name).inc()
        return cached

    metrics.CACHE_MISSES.labels(name=name).inc()

    # 击穿保护:抢到锁的请求去查库,没抢到的短暂等待别人的结果。
    lock_key = f"lock:{key}"
    try:
        acquired = cache.add(lock_key, 1, 5)
    except Exception:  # noqa: BLE001
        metrics.CACHE_ERRORS.labels(name=name).inc()
        return loader()

    if acquired:
        try:
            value = loader()
            try:
                cache.set(key, NULL if value is None else value, ttl_with_jitter(ttl))
            except Exception:  # noqa: BLE001
                metrics.CACHE_ERRORS.labels(name=name).inc()
            return value
        finally:
            try:
                cache.delete(lock_key)
            except Exception:  # noqa: BLE001
                pass

    # 等回填:最多 250ms;等不到就自己查一次(宁可重复,不可拖慢请求)。
    for _ in range(25):
        time.sleep(0.01)
        try:
            cached = cache.get(key)
        except Exception:  # noqa: BLE001
            break
        if cached is not None:
            metrics.CACHE_HITS.labels(name=name).inc()
            return None if cached == NULL else cached
    return loader()
