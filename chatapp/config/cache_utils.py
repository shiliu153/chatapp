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

文件信息:
    文件名称          config/cache_utils.py
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
import random
import time

from django.core.cache import cache

from . import metrics

logger = logging.getLogger("chatapp.cache")

# 空值哨兵:用字符串而不是 None,避免与「未命中」混淆(django-redis 会 pickle 它)。
NULL = "__null__"


def version(name: str) -> int:
    """读取一个版本号(不存在视为 0)。

    参数说明:
        name: 版本名,如 ``disc:ver:42``。

    返回参数:
        当前版本;Redis 异常时返回 0(等价于退化为无缓存版本)。

    使用示例:
        ``version("disc:ver:42")``

    备注信息:
        缓存里存的是字符串或整数都能转;异常被吞掉只记一次
        ``cache_errors_total{name="version"}``,不向上抛。
    """
    try:
        return int(cache.get(name) or 0)
    except Exception:  # noqa: BLE001  Redis 抖动不应该让请求失败
        metrics.CACHE_ERRORS.labels(name="version").inc()
        return 0


def bump_version(name: str) -> int:
    """版本号 +1;键不存在时先原子地建到 0 再 INCR。

    参数说明:
        name: 版本名。

    返回参数:
        递增后的版本;Redis 异常时返回 0(调用方无需感知)。

    使用示例:
        ``bump_version("disc:ver:42")``

    备注信息:
        注意不能「先 get 再 set」:并发首次写入时多个线程会各自 ``set 1``,
        把别人已经加上去的计数覆盖掉(经典丢失更新)。``cache.add`` 是原子的,
        只有第一个线程能建成,之后的线程都走 INCR。
        建成后不带过期时间,版本键常驻;异常时记 ``cache_errors_total{name="bump"}``
        并打一条 ``bump_version_failed`` 警告。
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

    参数说明:
        ttl: 基础 TTL(秒)。
        ratio: 抖动比例,0.1 表示 ±10%。

    返回参数:
        抖动后的 TTL,至少 1 秒。

    使用示例:
        ``ttl_with_jitter(300)``

    备注信息:
        结果取整到秒,TTL 传 0 或负数时也会返回 1,不会写出不过期的键;
        抖动均匀分布在 ``[-ttl*ratio, +ttl*ratio]`` 区间。
    """
    delta = ttl * ratio
    return max(1, int(round(ttl + random.uniform(-delta, delta))))


def get_or_load(key: str, ttl: int, loader, name: str = "default"):
    """Cache-Aside 读取:命中返回缓存,未命中回填并返回。

    参数说明:
        key: 缓存键(调用方负责把版本号拼进去)。
        ttl: 基础过期时间(秒),实际写入时加抖动。
        loader: 未命中时的查库函数,返回任意可 pickle 的值。
        name: 指标标签(如 ``candidates``)。

    返回参数:
        ``loader`` 的返回值;缓存了空值哨兵时返回 ``None``。

    使用示例:
        ``get_or_load(key, 300, lambda: list(queryset), name="candidates")``

    备注信息:
        命中与未命中分别记 ``cache_hits_total`` / ``cache_misses_total``;
        回填前抢 ``lock:<key>``(``SETNX``,5 秒过期),没抢到的等最多 250ms
        取别人的结果,等不到就自己查库(宁可重复一次,也不拖慢请求);
        Redis 任何一步异常都回退到直接调用 ``loader``,即 fail-open。
        ``loader`` 返回 ``None`` 时写空值哨兵 ``NULL``,下次命中直接返回 ``None``。
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
