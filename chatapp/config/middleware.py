"""请求追踪中间件:接受/生成 X-Request-Id,写响应头 + 请求日志(带耗时)。"""

import logging
import time
import uuid

from django.conf import settings

from .request_id import set_request_id

logger = logging.getLogger("chatapp.request")


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
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request.request_id = request_id
        set_request_id(request_id)
        start = time.monotonic()
        try:
            response = self.get_response(request)
            duration_ms = (time.monotonic() - start) * 1000
            # 慢请求升 WARNING(阈值 REQUEST_SLOW_MS 可调);日志里带 request_id 便于两端对账
            level = logging.WARNING if duration_ms >= settings.REQUEST_SLOW_MS else logging.INFO
            logger.log(level, "%s %s -> %s %.0fms",
                       request.method, request.path, response.status_code, duration_ms)
            response["X-Request-Id"] = request_id
            return response
        finally:
            set_request_id(None)
