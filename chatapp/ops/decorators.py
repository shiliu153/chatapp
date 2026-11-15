"""审核台的访问控制装饰器。

设计要点:
    审核台不走 DRF 权限体系,而是用这个装饰器逐个视图保护:
    未登录跳登录页(带 ``next`` 回跳),已登录但非 ``is_staff`` 直接 403。
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.urls import reverse


def staff_required(view):
    """要求当前用户是已登录的 ``is_staff`` 账号。

    参数说明:
        view: 被装饰的视图函数。

    返回参数:
        包装后的视图函数。

    使用示例:
        ``@staff_required`` 装饰在 ``ops/views.py`` 的 ``reports_list``、
        ``photos``、``allowlist_page`` 等视图上(路由见 ``ops/urls.py``)。

    备注信息:
        未登录跳登录页(带 ``next`` 回跳),已登录但非 ``is_staff`` 返回 403。
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        """检查登录状态与运营权限后调用原视图。

        参数说明:
            request: Django 请求对象。
            *args: 透传给原视图的位置参数。
            **kwargs: 透传给原视图的关键字参数。

        返回参数:
            原视图的响应;未登录时为登录页重定向,无权限时为 403。

        使用示例:
            ``return view(request, *args, **kwargs)``(本函数末尾,权限校验通过后)。

        备注信息:
            无特殊约束。
        """
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("ops:login"))
        if not request.user.is_staff:
            return HttpResponseForbidden("该账号无运营权限")
        return view(request, *args, **kwargs)
    return wrapper
