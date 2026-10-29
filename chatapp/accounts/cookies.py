"""Web 端 refresh token 的 HttpOnly Cookie 读写。

设计要点:
    1. **只有带 ``X-Client: web`` 的请求才走 Cookie**,App 的响应体协议保持不变;
    2. Cookie 的 ``Path`` 收到 ``/api/v1/auth/``,只在刷新与注销两个请求上携带,
       其他接口看不到它,缩小暴露面;
    3. ``Secure`` 跟 ``HTTPS_ENABLED`` 联动 —— 本地 http 调试时加 Secure 会被浏览器丢弃。

关联文档:
    - 设计:docs/superpowers/specs/2026-10-28-token-hardening-design.md
    - 接口契约:docs/api/auth.md
"""

from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.response import Response

WEB_CLIENT_HEADER = "X-Client"
WEB_CLIENT_VALUE = "web"


def wants_cookie(request) -> bool:
    """判断本次请求是否走 Cookie 分支(Web 客户端)。

    Args:
        request: DRF 请求对象。

    Returns:
        请求头 ``X-Client`` 为 ``web`` 时返回 ``True``;App 与其它调用方返回 ``False``。
    """
    return request.headers.get(WEB_CLIENT_HEADER, "").strip().lower() == WEB_CLIENT_VALUE


def same_origin(request) -> bool:
    """Cookie 分支的 CSRF 兜底:``Origin`` 存在时必须与 ``Host`` 同源。

    ``SameSite=Strict`` 已经挡住跨站表单,这里再校验一次 ``Origin``,覆盖
    「同站子域」与浏览器实现差异。本地 ``DEBUG`` 直接放行 —— Vite 代理用了
    ``changeOrigin``,``Host`` 会变成 127.0.0.1 而浏览器 ``Origin`` 是 localhost,
    强校验会把本地开发误杀。

    Args:
        request: DRF 请求对象。

    Returns:
        同源(或没有 ``Origin``、或 ``DEBUG``)返回 ``True``。
    """
    if settings.DEBUG:
        return True
    origin = (request.headers.get("Origin") or "").strip()
    if not origin:
        return True
    parsed = urlsplit(origin)
    return parsed.netloc.lower() == request.get_host().lower()


def _cookie_kwargs() -> dict:
    """拼出 ``set_cookie`` 的公共参数。"""
    return {
        "path": settings.REFRESH_COOKIE_PATH,
        "secure": bool(getattr(settings, "HTTPS_ENABLED", False)),
        "httponly": True,
        "samesite": "Strict",
    }


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    """把 refresh token 写入 HttpOnly Cookie。

    Args:
        response: 待返回的 DRF 响应对象(原地修改)。
        raw_token: 刚签发或刚轮换出的 refresh token 原文。
    """
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        **_cookie_kwargs(),
    )


def clear_refresh_cookie(response: Response) -> None:
    """清除 refresh Cookie(注销时调用)。

    Args:
        response: 待返回的 DRF 响应对象(原地修改)。
    """
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        samesite="Strict",
    )
