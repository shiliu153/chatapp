"""运营后台的访问控制:IP 白名单 + 强制 TOTP。

设计要点:
    1. 只保护 ``/admin/`` 与 ``/ops/``;API 与普通用户页面完全不受影响;
    2. 登录/登出/OTP 页本身必须放行,否则会无限重定向;
    3. IP 白名单在放行登录页之前判断 —— 后台登录页也不该对公网敞开;
    4. 未完成第二因子的运营账号一律跳到 ``/ops/otp/``,``next`` 保留原路径。

文件信息:
    文件名称          ops/middleware.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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
    """给 ``/admin/``、``/ops/`` 加 IP 白名单与 TOTP 门禁。

    参数说明:
        get_response: Django 传入的下一层中间件或视图函数。

    返回参数:
        中间件实例,由 Django 装配进 ``MIDDLEWARE`` 链。

    使用示例:
        ``"ops.middleware.StaffSecurityMiddleware"``

    备注信息:
        只保护 ``PROTECTED_PREFIXES`` 两个前缀,``/api/v1`` 与普通用户页面不受影响;
        两道门的先后顺序见 ``__call__``:白名单在豁免路径**之前**,第二因子在**之后**。
    """

    def __init__(self, get_response):
        """按 Django 中间件协议保存下游处理链。

        参数说明:
            get_response: Django 传入的下一层处理函数。

        返回参数:
            无返回值。

        使用示例:
            ``StaffSecurityMiddleware(get_response)``

        备注信息:
            由 Django 启动时实例化一次,同一实例要处理并发请求,因此不保存任何请求态。
        """
        self.get_response = get_response

    def __call__(self, request):
        """检查白名单与第二因子,必要时短路返回。

        参数说明:
            request: Django 请求对象。

        返回参数:
            下游响应;IP 不在白名单时为 403,未过第二因子时为跳 ``/ops/otp/`` 的重定向。

        使用示例:
            ``response = middleware(request)``

        备注信息:
            判定顺序固定为四步:① 路径不在 ``PROTECTED_PREFIXES`` 直接放行;
            ② ``OPS_ALLOWED_IPS`` 非空且 ``client_ip(request)`` 不在其中返回 403 ——
            这步在豁免判断**之前**,所以后台登录页本身也受白名单约束;
            ③ 命中 ``EXEMPT_PREFIXES``(登录、登出、OTP 与静态资源)放行,否则会无限重定向;
            ④ ``OPS_OTP_REQUIRED`` 为真、账号已登录且 ``is_staff``、但 ``is_verified`` 为假时
            跳 ``/ops/otp/?next=<原完整路径>``,``next`` 经 ``quote`` 转义。
            白名单每次请求都从 ``settings`` 重新解析,不做进程内缓存;``request.user``
            用 ``getattr`` 取,装配顺序里没有认证中间件时跳过第二因子判定。
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
