"""运营后台的访问控制:IP 白名单 + 强制 TOTP。

设计要点:
    1. 只保护 ``/admin/`` 与 ``/ops/``;API 与普通用户页面完全不受影响;
    2. 登录/登出/OTP 页本身必须放行,否则会无限重定向;
    3. IP 白名单在放行登录页之前判断 —— 后台登录页也不该对公网敞开;
    4. 未完成第二因子的运营账号一律跳到 ``/ops/otp/``,``next`` 保留原路径。
"""

from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from config.net import client_ip

from .otp import is_verified

PROTECTED_PREFIXES = ("/admin/", "/ops/")
EXEMPT_PREFIXES = (
    "/ops/login/", "/ops/logout/", "/ops/otp/",
    "/admin/login/", "/admin/logout/", "/admin/static/",
    "/static/", "/media/",
)


class StaffSecurityMiddleware:
    """给 ``/admin/``、``/ops/`` 加 IP 白名单与 TOTP 门禁。"""

    def __init__(self, get_response):
        """按 Django 中间件协议保存下游处理链。

        Args:
            get_response: Django 传入的下一层处理函数。
        """
        self.get_response = get_response

    def __call__(self, request):
        """检查白名单与第二因子,必要时短路返回。

        Args:
            request: Django 请求对象。

        Returns:
            下游响应,或 403 / 跳转到 OTP 页。
        """
        path = request.path
        if not path.startswith(PROTECTED_PREFIXES):
            return self.get_response(request)

        allowed = [ip.strip() for ip in settings.OPS_ALLOWED_IPS.split(",") if ip.strip()]
        if allowed and client_ip(request) not in allowed:
            return HttpResponseForbidden("IP 不在白名单内")

        if path.startswith(EXEMPT_PREFIXES):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if (settings.OPS_OTP_REQUIRED and user is not None and user.is_authenticated
                and user.is_staff and not is_verified(request)):
            return redirect(f"/ops/otp/?next={quote(request.get_full_path())}")
        return self.get_response(request)
