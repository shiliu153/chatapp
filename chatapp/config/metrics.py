"""Prometheus 指标:HTTP RED(rate / errors / duration)、在途请求、缓存与业务计数。

设计要点:
    1. **只按路由模板打标签**(``request.resolver_match.route``),不用真实路径 ——
       否则 ``/users/123`` 这类路径会把时间序列基数打爆;
    2. 自建 ``CollectorRegistry``:测试里模块会被反复导入/重载,用默认注册表会抛
       ``Duplicated timeseries``;
    3. ``/metrics`` 自身不计数,否则每次抓取都会污染延迟分布;
    4. **多进程(gunicorn 2 个 worker)必须开 ``PROMETHEUS_MULTIPROC_DIR``**:
       计数器默认是进程内的,各 worker 各记一份,而 Prometheus 每次抓取只落在一个 worker 上
       —— 实测 20 次请求后两个 worker 分别是 10 / 12,抓取结果在两者之间跳,``rate()`` 还会
       把「另一个 worker 的数更小」当成计数器重置。配好该目录后各 worker 写共享 mmap 文件,
       抓取时用 ``MultiProcessCollector`` 合并(见 ``chatapp/gunicorn.conf.py``);
    5. 只做进程内聚合,不落库、不发网络请求(响应路径禁止第三方调用的约定)。

文件信息:
    文件名称          config/metrics.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import hmac
import ipaddress
import logging
import os

from django.conf import settings
from django.http import HttpResponse
from prometheus_client import (CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge,
                               Histogram, generate_latest, multiprocess)

logger = logging.getLogger(__name__)

REGISTRY = CollectorRegistry(auto_describe=True)

# 多进程模式由环境变量开启(生产 .env 指向 /dev/shm 下的目录);未配置时保持单进程语义,
# 本地 runserver / 测试 / 单 worker 部署都不需要它。
MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR", "")


def multiprocess_enabled() -> bool:
    """是否启用 Prometheus 多进程合并。

    参数说明:
        无。

    返回参数:
        True 表示 ``PROMETHEUS_MULTIPROC_DIR`` 已配置且目录存在;否则 False(单进程语义)。

    使用示例:
        ``if multiprocess_enabled(): ...``

    备注信息:
        环境变量配了但目录不存在(如容器重启后 ``/dev/shm`` 被清空)时按单进程处理,
        避免抓取直接失败。
    """
    return bool(MULTIPROC_DIR) and os.path.isdir(MULTIPROC_DIR)


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
    # 多进程下「在途请求」要跨 worker 相加,否则合并后只剩某一个 worker 的读数。
    multiprocess_mode="livesum",
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

# --- 业务指标(2026-11-05,E-4 ③):只回答「今天有人在用吗、断在哪一步」 ---
# 不加用户 id / 手机号 / 目标 id 这类标签:基数会随用户数线性膨胀,Prometheus 撑不住。
# 漏斗口径:登录成功 → 滑卡(like/pass)→ 配对成功;IM 调用看 Django 这一侧的成与败
# (imserver 自己的 im_sends_total 只看传输层,看不到「Django 根本没发出请求」)。
LOGINS = Counter(
    "logins_total",
    "登录结果(成功 / 被拒:白名单、验证码、锁定)",
    ["result"],
    registry=REGISTRY,
)

SWIPES = Counter(
    "swipes_total",
    "滑卡次数(按动作)",
    ["action"],
    registry=REGISTRY,
)

MATCHES = Counter(
    "matches_total",
    "新增配对数(每建立一条配对计数一次)",
    registry=REGISTRY,
)

IM_CALLS = Counter(
    "im_calls_total",
    "Django 调 imserver 内部 API 的次数与成败(按端点)",
    ["endpoint", "result"],
    registry=REGISTRY,
)

# --- 推送指标(2026-11-05,C-1)---
# 「推了没有」不能只看 Celery 任务数:偏好关掉、被封禁、没设备都会静默返回,
# 必须分成 sent / skipped{reason} 两个读数,否则「没推送」和「推送失败」分不清。
PUSH_SENT = Counter(
    "push_sent_total",
    "推送投递结果(按通道与结果)",
    ["provider", "result"],
    registry=REGISTRY,
)

PUSH_SKIPPED = Counter(
    "push_skipped_total",
    "推送被短路的原因(无设备 / 偏好关闭 / 封禁 / 重复事件)",
    ["reason"],
    registry=REGISTRY,
)


def push_sent(provider: str, ok: bool) -> None:
    """记录一次推送投递。

    参数说明:
        provider: 通道名(``off`` / ``log`` / ``jpush``);基数固定,可安全当标签。
        ok: 通道是否接受(``off`` 通道也算 ok,它只是不发)。

    返回参数:
        无返回值。

    使用示例:
        ``push_sent("jpush", True)``

    备注信息:
        只累加 ``push_sent_total``,不判断偏好与封禁;被短路的情况走
        :func:`push_skipped`,两条读数合起来才能区分「没推送」与「推送失败」。
    """
    PUSH_SENT.labels(provider=provider, result="ok" if ok else "error").inc()


def push_skipped(reason: str) -> None:
    """记录一次「没有推送」及其原因。

    参数说明:
        reason: 短路原因,取值见 ``notifications.tasks.PUSH_SKIP_*`` 常量。

    返回参数:
        无返回值。

    使用示例:
        ``push_skipped("no_device")``

    备注信息:
        ``reason`` 必须来自固定常量集合,不要拼入用户 id 之类的高基数值。
    """
    PUSH_SKIPPED.labels(reason=reason).inc()

# --- 队列指标:积压是「削峰是否生效」的直接读数 ---
CELERY_QUEUE_DEPTH = Gauge(
    "celery_queue_depth",
    "各 Celery 队列的待处理任务数",
    ["queue"],
    registry=REGISTRY,
    # 抓取时由进程自己从 broker 读;多进程合并要取 max,取 sum 会变成「队列长度 × worker 数」。
    multiprocess_mode="max",
)

QUEUES = ("critical", "default", "notify", "bulk")


def im_call(endpoint: str, ok: bool) -> None:
    """记录一次「Django → imserver 内部 API」调用。

    参数说明:
        endpoint: 内部 API 路径(如 ``/internal/messages/send``);基数固定,可以安全当标签。
        ok: 调用是否成功(2xx)。

    返回参数:
        无返回值。

    使用示例:
        ``im_call("/internal/messages/send", True)``

    备注信息:
        imserver 自己的 ``im_sends_total`` 只看传输层,这个指标补的是
        「Django 有没有发出请求」以及调用成败。
    """
    IM_CALLS.labels(endpoint=endpoint, result="ok" if ok else "error").inc()


def refresh_queue_depths() -> None:
    """从 broker 读取各队列长度并刷新 gauge。

    只在抓取 ``/metrics`` 时调用(15 秒一次),不在请求路径上。
    Redis 不可用时静默跳过,保留上一次的值。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``refresh_queue_depths()``

    备注信息:
        每次调用都会新建一个 ``socket_timeout=1`` 的 Redis 连接,读完即关闭;
        broker 抛任何异常都被吞掉,只记一次 ``cache_errors_total{name="queue_depth"}``。
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

    参数说明:
        request: Django 请求对象。

    返回参数:
        路由模板(如 ``users/<int:user_id>``);未匹配到路由时为 ``unmatched``。

    使用示例:
        ``metrics.route_label(request)``

    备注信息:
        只取 ``resolver_match.route``,不含真实路径参数,这是标签基数可控的前提;
        404 等未匹配请求统一归到 ``unmatched``。
    """
    match = getattr(request, "resolver_match", None)
    route = getattr(match, "route", "") if match is not None else ""
    return route or "unmatched"


def observe(method: str, route: str, status: int, seconds: float) -> None:
    """记录一次请求的计数与耗时。

    参数说明:
        method: HTTP 方法。
        route: 路由模板(已归一,不含真实 id)。
        status: HTTP 状态码。
        seconds: 耗时(秒)。

    返回参数:
        无返回值。

    使用示例:
        ``metrics.observe("GET", "users/<int:user_id>", 200, 0.031)``

    备注信息:
        状态码转成字符串再当标签;一次调用同时累加 ``http_requests_total`` 与
        ``http_request_duration_seconds``,两个指标口径保持一致。
    """
    REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    DURATION.labels(method=method, route=route).observe(seconds)


def render() -> bytes:
    """渲染 Prometheus 文本格式的指标快照。

    多进程模式(``PROMETHEUS_MULTIPROC_DIR`` 已配置)下用 ``MultiProcessCollector`` 把各
    worker 的 mmap 文件合并成一份;合并失败时退回本进程视图并记一次 ``cache_errors_total``
    —— 抓取宁可少几个数,也不能返回 500 让整条监控链路哑掉。

    参数说明:
        无。

    返回参数:
        exposition 格式的字节串。

    使用示例:
        ``HttpResponse(render(), content_type=CONTENT_TYPE_LATEST)``

    备注信息:
        每次多进程渲染都新建临时 ``CollectorRegistry``,不复用模块级 ``REGISTRY``,
        避免多次注册同一批 collector 抛 ``Duplicated timeseries``。
    """
    if multiprocess_enabled():
        try:
            registry = CollectorRegistry(auto_describe=True)
            multiprocess.MultiProcessCollector(registry)
            return generate_latest(registry)
        except Exception:  # noqa: BLE001  mmap 目录被删/权限变化都不能让抓取失败
            logger.exception("多进程指标合并失败,退回本进程视图")
            CACHE_ERRORS.labels(name="metrics_multiprocess").inc()
    return generate_latest(REGISTRY)


def token_matches(supplied: str, expected: str) -> bool:
    """常量时间比较抓取令牌,避免按字符比较泄漏长度信息。

    参数说明:
        supplied: 请求头里带的令牌。
        expected: 配置的令牌。

    返回参数:
        是否一致;``expected`` 为空时恒为 False(调用方应先判断是否启用)。

    使用示例:
        ``token_matches(request.headers.get("X-Metrics-Token", ""), settings.METRICS_TOKEN)``

    备注信息:
        比较走 ``hmac.compare_digest``;``supplied`` 为 ``None`` 时按空串处理。
    """
    return bool(expected) and hmac.compare_digest(supplied or "", expected)


def _is_loopback(addr: str) -> bool:
    """判断地址是否回环。

    备注信息:
        非法或空地址一律 False(``ipaddress`` 解析失败直接吞掉),调用方无需预校验。
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

    参数说明:
        request: Django 请求对象。

    返回参数:
        Prometheus 文本快照;未授权时 403(配了令牌)或 404(未配令牌且非回环)。

    使用示例:
        ``path("metrics", metrics.metrics_view)``

    备注信息:
        配了令牌时先看 ``X-Metrics-Token``,没有再退回 ``Authorization: Bearer``,
        两者都不匹配即 403;未配令牌且非回环返回 404 而不是 403,不暴露端点存在。
        校验通过后先刷队列深度再渲染,保证同一次抓取里两类指标口径一致。
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
