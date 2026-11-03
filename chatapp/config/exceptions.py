"""DRF 全局异常处理:把任何失败响应统一成 ``{code, message, request_id}`` 信封。

设计要点:
    1. ``code`` 优先取异常自带的 ``detail_code``(如单设备登录冲突的 40101),
       没有则退化为 HTTP 状态码;
    2. ``request_id`` 取自请求上下文,便于与访问日志、客户端上报三方对账;
    3. **未预期异常也必须返回 JSON**(P2-4):DRF 默认会 re-raise,Django 在
       ``DEBUG=0`` 时回 HTML 500 页,客户端按 JSON 解析会二次报错。这里统一转成
       错误契约,同时用 ``logger.exception`` 保留完整堆栈 —— 只是换了响应格式,
       没有吞掉故障;
    4. ``server_error`` 是 Django 层的兜底(非 DRF 路径,如中间件异常),
       由 ``config/urls.py`` 的 ``handler500`` 挂载。
"""

import logging

from django.http import HttpResponse, JsonResponse
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .request_id import current_request_id

logger = logging.getLogger("chatapp.request")


def _first_message(data):
    """从 DRF 各种形状的错误数据里取第一条可读信息。"""
    if isinstance(data, dict):
        if "detail" in data:
            return str(data["detail"])
        for value in data.values():
            message = _first_message(value)
            if message:
                return message
        return "请求无效"
    if isinstance(data, (list, tuple)):
        for item in data:
            message = _first_message(item)
            if message:
                return message
        return "请求无效"
    return str(data)


def api_exception_handler(exc, context):
    """把 DRF 的异常响应改写成本项目的统一错误信封。

    Args:
        exc: 抛出的异常实例。
        context: DRF 提供的上下文(含 view 与 request)。

    Returns:
        改写后的 Response;未预期异常返回 500 JSON,不再交回 Django。
    """
    response = exception_handler(exc, context)
    if response is None:
        # 未预期异常(DB 宕机、代码 bug)。用 logger.exception 保留堆栈,
        # 否则「返回了 JSON」会让真正的故障在日志里消失。
        logger.exception(
            "unhandled_exception",
            extra={"path": getattr(context.get("request"), "path", "")},
        )
        return Response(
            {"code": 500, "message": "服务器内部错误", "request_id": current_request_id()},
            status=500,
        )
    # 异常自带业务码(如单设备登录的 40101)时透传,否则用 HTTP 状态码作业务码
    detail_code = getattr(exc, "detail_code", None)
    response.data = {
        "code": detail_code if detail_code is not None else response.status_code,
        "message": _first_message(response.data),
        "request_id": current_request_id(),
    }
    return response


def server_error(request, *args, **kwargs):
    """Django 层 500 兜底:接口路径返回 JSON 契约,其余路径返回纯文本。

    只有非 DRF 路径(中间件、模板视图)才会走到这里;DRF 视图的未预期异常
    在 ``api_exception_handler`` 里已经转成 JSON。

    Args:
        request: 触发 500 的请求。
        *args: Django 预留的位置参数。
        **kwargs: Django 预留的关键字参数。

    Returns:
        ``/api/`` 或 ``/ops/`` 下是 JSON 响应,其余是纯文本 500。
    """
    request_id = current_request_id()
    logger.error("django_500", extra={"path": request.path, "request_id": request_id})
    if request.path.startswith(("/api/", "/ops/")):
        return JsonResponse(
            {"code": 500, "message": "服务器内部错误", "request_id": request_id},
            status=500,
        )
    return HttpResponse("服务器内部错误", status=500,
                        content_type="text/plain; charset=utf-8")
