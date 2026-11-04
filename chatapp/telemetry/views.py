"""客户端错误上报接口。

关联文档:
    - 接口契约:docs/api/telemetry.md
"""

import logging

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from config import metrics

from .serializers import ClientErrorSerializer
from .throttles import ClientErrorThrottle

logger = logging.getLogger("chatapp.client_error")


@extend_schema(request=ClientErrorSerializer, responses={204: None})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ClientErrorThrottle])
def report_client_error(request):
    """接收一条前端未捕获异常(POST /api/v1/client-errors)。

    允许匿名:登录页白屏、启动即崩这类最有价值的错误发生时,客户端还没有令牌。

    Args:
        request: DRF 请求对象,body 见 ``ClientErrorSerializer``。

    Returns:
        204 空响应(上报是 fire-and-forget,不回业务数据)。
    """
    serializer = ClientErrorSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    # 字段名不能叫 message / levelname 这类 LogRecord 保留字,否则 logging 会抛异常
    logger.error(
        "client_error",
        extra={
            "platform": data["platform"],
            "client_message": data["message"],
            "client_stack": data["stack"] or "-",
            "client_route": data["route"] or "-",
            "app_version": data["app_version"] or "-",
            "client_request_id": data["request_id"] or "-",
            "user_agent": (request.META.get("HTTP_USER_AGENT") or "-")[:300],
            "user_id": request.user.id if request.user.is_authenticated else None,
        },
    )
    metrics.CLIENT_ERRORS.labels(platform=data["platform"]).inc()
    return Response(status=204)
