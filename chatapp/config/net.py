"""客户端 IP 的解析:限流、后台 IP 白名单共用。

设计要点:
    nginx 反代后 ``REMOTE_ADDR`` 恒为 127.0.0.1,必须取它追加的真实 IP;
    ``X-Forwarded-For`` 取**最后一段**(nginx 用 ``$proxy_add_x_forwarded_for``
    追加,最后一段才是直连客户端),``X-Real-IP`` 优先。
"""


def client_ip(request) -> str:
    """取请求的真实客户端 IP。

    Args:
        request: Django/DRF 请求对象;可为 ``None``。

    Returns:
        IP 字符串;拿不到时返回空串。
    """
    if request is None:
        return ""
    meta = request.META
    real = meta.get("HTTP_X_REAL_IP", "").strip()
    if real:
        return real
    forwarded = meta.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return meta.get("REMOTE_ADDR", "")
