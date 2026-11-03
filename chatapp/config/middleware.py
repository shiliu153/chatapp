"""请求追踪中间件:接受/生成 X-Request-Id,写响应头 + 请求日志(带耗时)。

以及 Prometheus 指标中间件(HTTP RED + 在途数)。
"""

import logging
import re
import time
import uuid

from django.conf import settings

from . import metrics
from .request_id import set_request_id

logger = logging.getLogger("chatapp.request")

# 客户端传来的 ID 只接受「短、无空白、无控制字符」的安全字符集;
# 否则日志里可能被注入换行/终端转义序列(L2)。
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIdMiddleware:
    """为每个请求确定追踪 ID,并写进日志与响应头。

    设计要点:
        ID 优先取客户端传入的 ``X-Request-Id``(便于前后端对账),没有则新生成;
        请求处理完毕后必定清理上下文变量,避免 ID 串到同线程的下一个请求。
    """

    def __init__(self, get_response):
        """按 Django 中间件协议保存下游处理链。

        Args:
            get_response: Django 传入的下一层处理函数。
        """
        self.get_response = get_response

    def __call__(self, request):
        """处理单个请求:注入追踪 ID、记访问日志、回写响应头。

        Args:
            request: Django 请求对象。

        Returns:
            下游返回的响应对象,已带上 ``X-Request-Id`` 头。
        """
        raw_request_id = request.headers.get("X-Request-Id", "")
        request_id = (raw_request_id if _REQUEST_ID_RE.fullmatch(raw_request_id)
                      else uuid.uuid4().hex)
        request.request_id = request_id
        set_request_id(request_id)
        start = time.monotonic()
        try:
            response = self.get_response(request)
            duration_ms = (time.monotonic() - start) * 1000
            # 慢请求升 WARNING(阈值 REQUEST_SLOW_MS 可调);日志里带 request_id 便于两端对账
            level = logging.WARNING if duration_ms >= settings.REQUEST_SLOW_MS else logging.INFO
            logger.log(level, "%s %s -> %s %.0fms",
                       request.method, request.path, response.status_code, duration_ms,
                       extra=self._log_fields(request, response, duration_ms))
            response["X-Request-Id"] = request_id
            return response
        finally:
            set_request_id(None)

    @staticmethod
    def _log_fields(request, response, duration_ms: float) -> dict:
        """拼出结构化日志字段(JSON 模式下直接成为顶层字段)。

        Args:
            request: Django 请求对象。
            response: 下游响应。
            duration_ms: 耗时(毫秒)。

        Returns:
            ``extra`` 字典;``sql_count`` 只在 DEBUG 下采集(生产不开 SQL 记录)。
        """
        user = getattr(request, "user", None)
        authenticated = getattr(user, "is_authenticated", False)
        fields = {
            "user_id": getattr(user, "id", None) if authenticated else None,
            "route": metrics.route_label(request),
            "status": response.status_code,
            "duration_ms": round(duration_ms, 1),
        }
        if settings.DEBUG:
            from django.db import connection
            fields["sql_count"] = len(connection.queries)
        return fields


class MetricsMiddleware:
    """记录每个请求的 RED 指标;``/metrics`` 自身不计数。

    设计要点:
        1. 标签用路由模板而非真实路径,避免时间序列基数爆炸;
        2. 异常上抛前也记一次 500,否则「报错的请求」在指标里是隐形的;
        3. ``/metrics`` 与静态路径跳过,防止抓取请求污染延迟分布。
    """

    def __init__(self, get_response):
        """按 Django 中间件协议保存下游处理链。

        Args:
            get_response: Django 传入的下一层处理函数。
        """
        self.get_response = get_response

    def __call__(self, request):
        """处理单个请求并记录指标。

        Args:
            request: Django 请求对象。

        Returns:
            下游返回的响应对象(原样透传)。
        """
        if request.path == "/metrics":
            return self.get_response(request)

        metrics.INFLIGHT.inc()
        start = time.monotonic()
        try:
            response = self.get_response(request)
        except Exception:
            # 未预期异常:记一次 500 再上抛,交给 Django/DRF 的 500 处理。
            metrics.observe(request.method, metrics.route_label(request), 500,
                            time.monotonic() - start)
            raise
        finally:
            metrics.INFLIGHT.dec()

        metrics.observe(request.method, metrics.route_label(request),
                        response.status_code, time.monotonic() - start)
        return response
