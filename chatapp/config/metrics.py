"""Prometheus 指标:HTTP RED(rate / errors / duration)与在途请求数。

设计要点:
    1. **只按路由模板打标签**(``request.resolver_match.route``),不用真实路径 ——
       否则 ``/users/123`` 这类路径会把时间序列基数打爆;
    2. 自建 ``CollectorRegistry``:测试里模块会被反复导入/重载,用默认注册表会抛
       ``Duplicated timeseries``;
    3. ``/metrics`` 自身不计数,否则每次抓取都会污染延迟分布;
    4. 只做进程内聚合,不落库、不发网络请求(响应路径禁止第三方调用的约定)。
"""

import hmac
import ipaddress

from django.conf import settings
from django.http import HttpResponse
from prometheus_client import (CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge,
                               Histogram, generate_latest)

REGISTRY = CollectorRegistry(auto_describe=True)

REQUESTS = Counter(
    "http_requests_total",
    "HTTP 请求数(按方法/路由模板/状态码)",
    ["method", "route", "status"],
    registry=REGISTRY,
)

DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求耗时(秒,按方法/路由模板)",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

INFLIGHT = Gauge(
    "http_inflight",
    "当前正在处理的请求数",
    registry=REGISTRY,
)

# --- 缓存指标:命中率是「加缓存到底有没有用」的唯一证据 ---
CACHE_HITS = Counter(
    "cache_hits_total",
    "缓存命中次数(按用途)",
    ["name"],
    registry=REGISTRY,
)
CACHE_MISSES = Counter(
    "cache_misses_total",
    "缓存未命中次数(按用途)",
    ["name"],
    registry=REGISTRY,
)
CACHE_ERRORS = Counter(
    "cache_errors_total",
    "缓存操作异常次数(Redis 抖动/不可用)",
    ["name"],
    registry=REGISTRY,
)

# --- 客户端错误:前端白屏/崩溃在服务端 5xx 里看不见,只能靠前端主动上报 ---
CLIENT_ERRORS = Counter(
    "client_errors_total",
    "前端上报的未捕获异常数(按端)",
    ["platform"],
    registry=REGISTRY,
)

# --- 队列指标:积压是「削峰是否生效」的直接读数 ---
CELERY_QUEUE_DEPTH = Gauge(
    "celery_queue_depth",
    "各 Celery 队列的待处理任务数",
    ["queue"],
    registry=REGISTRY,
)

QUEUES = ("critical", "default", "notify", "bulk")


def refresh_queue_depths() -> None:
    """从 broker 读取各队列长度并刷新 gauge。

    只在抓取 ``/metrics`` 时调用(15 秒一次),不在请求路径上。
    Redis 不可用时静默跳过,保留上一次的值。
    """
    try:
        import redis

        from django.conf import settings

        client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=1)
        try:
            for queue in QUEUES:
                CELERY_QUEUE_DEPTH.labels(queue=queue).set(client.llen(queue))
        finally:
            client.close()
    except Exception:  # noqa: BLE001  broker 抖动不能影响抓取
        CACHE_ERRORS.labels(name="queue_depth").inc()


def route_label(request) -> str:
    """取用于打标签的路由模板。

    Args:
        request: Django 请求对象。

    Returns:
        路由模板(如 ``users/<int:user_id>``);未匹配到路由时为 ``unmatched``。
    """
    match = getattr(request, "resolver_match", None)
    route = getattr(match, "route", "") if match is not None else ""
    return route or "unmatched"


def observe(method: str, route: str, status: int, seconds: float) -> None:
    """记录一次请求的计数与耗时。

    Args:
        method: HTTP 方法。
        route: 路由模板(已归一,不含真实 id)。
        status: HTTP 状态码。
        seconds: 耗时(秒)。
    """
    REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    DURATION.labels(method=method, route=route).observe(seconds)


def render() -> bytes:
    """渲染 Prometheus 文本格式的指标快照。

    Returns:
        exposition 格式的字节串。
    """
    return generate_latest(REGISTRY)


def token_matches(supplied: str, expected: str) -> bool:
    """常量时间比较抓取令牌,避免按字符比较泄漏长度信息。

    Args:
        supplied: 请求头里带的令牌。
        expected: 配置的令牌。

    Returns:
        是否一致;``expected`` 为空时恒为 False(调用方应先判断是否启用)。
    """
    return bool(expected) and hmac.compare_digest(supplied or "", expected)


def _is_loopback(addr: str) -> bool:
    """判断地址是否回环。

    Args:
        addr: 对端 IP 字符串。

    Returns:
        True 表示回环地址;非法或空地址一律 False。
    """
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def metrics_view(request):
    """``/metrics`` 抓取入口:默认只允许回环直连,配了令牌则按令牌放行。

    设计要点:
        nginx 反代后 ``REMOTE_ADDR`` 恒为 127.0.0.1,所以**回环判断挡不住公网**;
        生产必须配 ``METRICS_TOKEN``(Prometheus 用 ``X-Metrics-Token`` 或
        ``Authorization: Bearer`` 抓取),并在 nginx 上显式拒绝 ``/metrics``。

    Args:
        request: Django 请求对象。

    Returns:
        Prometheus 文本快照;未授权时 403(配了令牌)或 404(未配令牌且非回环)。
    """
    expected = getattr(settings, "METRICS_TOKEN", "")
    if expected:
        supplied = request.headers.get("X-Metrics-Token", "")
        if not supplied:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                supplied = auth[len("Bearer "):]
        if not token_matches(supplied, expected):
            return HttpResponse(status=403)
    elif not _is_loopback(request.META.get("REMOTE_ADDR", "")):
        # 不暴露「这里有个指标端点」:未配令牌时对非回环一律 404。
        return HttpResponse(status=404)
    refresh_queue_depths()
    return HttpResponse(render(), content_type=CONTENT_TYPE_LATEST)
