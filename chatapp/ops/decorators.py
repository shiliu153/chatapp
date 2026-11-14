"""审核台的访问控制装饰器。

设计要点:
    审核台不走 DRF 权限体系,而是用这个装饰器逐个视图保护:
    未登录跳登录页(带 ``next`` 回跳),已登录但非 ``is_staff`` 直接 403。

文件信息:
    文件名称          ops/decorators.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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
        包装后的视图函数,签名与原视图一致。

    使用示例:
        ``@staff_required``

    备注信息:
        未登录时用 ``redirect_to_login`` 跳到 ``ops:login`` 并把当前完整路径作为
        ``next``;已登录但非 ``is_staff`` 直接返回 403,不跳登录页(普通用户
        反复登进来也进不去,重定向只会让人以为是密码错了)。
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
            ``wrapper(request, *args, **kwargs)``

        备注信息:
            先判登录再判 ``is_staff``:匿名请求拿不到可靠的 ``user.is_staff``,
            顺序反了会把未登录用户直接判 403 而不给登录入口;
            ``@wraps(view)`` 保留原视图的 ``__name__`` 与 ``__doc__``,便于反查与调试。
        """
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("ops:login"))
        if not request.user.is_staff:
            return HttpResponseForbidden("该账号无运营权限")
        return view(request, *args, **kwargs)
    return wrapper
