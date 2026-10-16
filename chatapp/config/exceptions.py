"""DRF 全局异常处理:把任何失败响应统一成 ``{code, message, request_id}`` 信封。

设计要点:
    1. ``code`` 优先取异常自带的 ``detail_code``(如单设备登录冲突的 40101),
       没有则退化为 HTTP 状态码;
    2. ``request_id`` 取自请求上下文,便于与访问日志、客户端上报三方对账;
    3. 返回 ``None`` 表示该异常不归 DRF 处理(如未预期的 500),交回 Django,
       不要在这里吞掉它 —— 吞掉会让真正的故障在日志里消失。
"""

from rest_framework.views import exception_handler

from .request_id import current_request_id


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
        改写后的 Response;``None`` 表示不归 DRF 处理,交回 Django。
    """
    response = exception_handler(exc, context)
    if response is None:
        return None
    # 异常自带业务码(如单设备登录的 40101)时透传,否则用 HTTP 状态码作业务码
    detail_code = getattr(exc, "detail_code", None)
    response.data = {
        "code": detail_code if detail_code is not None else response.status_code,
        "message": _first_message(response.data),
        "request_id": current_request_id(),
    }
    return response
