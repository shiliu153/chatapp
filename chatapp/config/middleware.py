"""请求追踪中间件:接受/生成 X-Request-Id,写响应头 + 请求日志(带耗时)。"""

import logging
import time
import uuid

from django.conf import settings

from .request_id import set_request_id

logger = logging.getLogger("chatapp.request")


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
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
