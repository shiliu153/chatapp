from rest_framework.views import exception_handler


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
    response = exception_handler(exc, context)
    if response is None:
        return None
    # 异常自带业务码(如单设备登录的 40101)时透传,否则用 HTTP 状态码作业务码
    detail_code = getattr(exc, "detail_code", None)
    response.data = {
        "code": detail_code if detail_code is not None else response.status_code,
        "message": _first_message(response.data),
    }
    return response
