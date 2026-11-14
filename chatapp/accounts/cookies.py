"""Web 端 refresh token 的 HttpOnly Cookie 读写。

设计要点:
    1. **只有带 ``X-Client: web`` 的请求才走 Cookie**,App 的响应体协议保持不变;
    2. Cookie 的 ``Path`` 收到 ``/api/v1/auth/``,只在刷新与注销两个请求上携带,
       其他接口看不到它,缩小暴露面;
    3. ``Secure`` 跟 ``HTTPS_ENABLED`` 联动 —— 本地 http 调试时加 Secure 会被浏览器丢弃。

关联文档:
    - 设计:docs/superpowers/specs/2026-10-28-token-hardening-design.md
    - 接口契约:docs/api/auth.md

文件信息:
    文件名称          accounts/cookies.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.response import Response

WEB_CLIENT_HEADER = "X-Client"
WEB_CLIENT_VALUE = "web"


def wants_cookie(request) -> bool:
    """判断本次请求是否走 Cookie 分支(Web 客户端)。

    参数说明:
        request: DRF 请求对象。

    返回参数:
        请求头 ``X-Client`` 为 ``web`` 时返回 ``True``;App 与其它调用方返回 ``False``。

    使用示例:
        ``wants_cookie(request)``

    备注信息:
        取值先 ``strip`` 再转小写,``Web`` 与 `` web `` 同样算命中;头缺失按
        ``False`` 处理,因此老版本 App 的响应体协议不受影响。
    """
    return request.headers.get(WEB_CLIENT_HEADER, "").strip().lower() == WEB_CLIENT_VALUE


def same_origin(request) -> bool:
    """Cookie 分支的 CSRF 兜底:``Origin`` 存在时必须与 ``Host`` 同源。

    ``SameSite=Strict`` 已经挡住跨站表单,这里再校验一次 ``Origin``,覆盖
    「同站子域」与浏览器实现差异。本地 ``DEBUG`` 直接放行 —— Vite 代理用了
    ``changeOrigin``,``Host`` 会变成 127.0.0.1 而浏览器 ``Origin`` 是 localhost,
    强校验会把本地开发误杀。

    参数说明:
        request: DRF 请求对象。

    返回参数:
        同源(或没有 ``Origin``、或 ``DEBUG``)返回 ``True``。

    使用示例:
        ``same_origin(request)``

    备注信息:
        只比较 ``Origin`` 的 netloc 与 ``request.get_host()``,两侧都转小写;
        ``Origin`` 为空串按放行处理 —— 非浏览器客户端本来就不会带它。
    """
    if settings.DEBUG:
        return True
    origin = (request.headers.get("Origin") or "").strip()
    if not origin:
        return True
    parsed = urlsplit(origin)
    return parsed.netloc.lower() == request.get_host().lower()


def _cookie_kwargs() -> dict:
    """拼出 ``set_cookie`` 的公共参数。

    参数说明:
        无。

    返回参数:
        ``dict``,含 ``path`` / ``secure`` / ``httponly`` / ``samesite`` 四项。

    使用示例:
        ``response.set_cookie(key=settings.REFRESH_COOKIE_NAME, value=raw, **_cookie_kwargs())``

    备注信息:
        ``path`` 取 ``settings.REFRESH_COOKIE_PATH``;``secure`` 跟随
        ``HTTPS_ENABLED``(本地 http 调试带 Secure 会被浏览器直接丢弃);
        ``httponly`` 恒为 ``True``,``samesite`` 恒为 ``Strict``。
    """
    return {
        "path": settings.REFRESH_COOKIE_PATH,
        "secure": bool(getattr(settings, "HTTPS_ENABLED", False)),
        "httponly": True,
        "samesite": "Strict",
    }


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    """把 refresh token 写入 HttpOnly Cookie。

    参数说明:
        response: 待返回的 DRF 响应对象(原地修改)。
        raw_token: 刚签发或刚轮换出的 refresh token 原文。

    使用示例:
        ``set_refresh_cookie(response, raw_token)``

    返回参数:
        无返回值(原地修改 ``response``)。

    备注信息:
        ``max_age`` 取 ``SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]`` 的秒数,与令牌
        自身寿命同源;Cookie 里存原文而不是摘要 —— 刷新时后端要拿它回查黑名单。
    """
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        **_cookie_kwargs(),
    )


def clear_refresh_cookie(response: Response) -> None:
    """清除 refresh Cookie(注销时调用)。

    参数说明:
        response: 待返回的 DRF 响应对象(原地修改)。

    返回参数:
        无返回值(原地修改 ``response``)。

    使用示例:
        ``clear_refresh_cookie(response)``

    备注信息:
        ``path`` 必须与写入时一致,否则浏览器删不掉同一个 Cookie;``samesite``
        同样保持 ``Strict``,与 ``set_refresh_cookie`` 对齐。
    """
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        samesite="Strict",
    )
