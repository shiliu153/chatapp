"""封禁权限:重封禁用户全域 403。

设计要点:
    1. 本权限类是 DRF 的全局默认权限之一(见 ``settings.REST_FRAMEWORK``),
       **新接口自动被覆盖**,不需要逐个视图声明;
    2. 白名单只放行 ``GET /users/me``(前端要展示封禁原因)与 ``GET /users/tags``;
    3. 轻封禁不在这里拦 —— 它只禁止滑卡,由 ``discovery.views.swipe`` 自己检查。

文件信息:
    文件名称          moderation/permissions.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from users.models import ProfileStatus
from users.services import get_profile

# (方法, 路径) 白名单:被封禁的人也要能读自己的资料(前端要展示封禁原因)和标签池
BAN_EXEMPT = {
    ("GET", "/api/v1/users/me"),
    ("GET", "/api/v1/users/tags"),
}


class IsNotHeavyBanned(BasePermission):
    """重封禁 → 全部业务接口 403;轻封禁只管滑卡(swipe 视图里另有检查)。

    参数说明:
        无(DRF 权限类由框架实例化,不接收构造参数)。

    返回参数:
        权限类本身;DRF 调 ``has_permission`` 决定放行(``True``)还是 403。

    使用示例:
        ``"DEFAULT_PERMISSION_CLASSES": ("moderation.permissions.IsNotHeavyBanned",)``

    备注信息:
        因为它挂在全局默认权限里,新增的业务接口**不用再声明**就自动受保护;
        只覆盖 ``banned_heavy``,``banned_light`` 只禁滑卡(见本文件模块 docstring)。
    """

    def has_permission(self, request, view):
        """检查当前用户是否被重封禁。

        参数说明:
            request: DRF 请求对象。
            view: 当前视图;本权限不使用。

        返回参数:
            未被重封禁(或在白名单内)时返回 ``True``。

        使用示例:
            ``IsNotHeavyBanned().has_permission(request, view)``

        备注信息:
            未登录请求直接放行 —— 登录/验证码/刷新 token 这些 ``AllowAny`` 接口不归本权限管;
            命中 ``BAN_EXEMPT``(``GET /api/v1/users/me``、``GET /api/v1/users/tags``)也放行,
            前者用于前端展示封禁原因,后者是标签池。
            重封禁时抛 ``PermissionDenied``,由 ``config.exceptions.api_exception_handler``
            包成 ``{code, message, request_id}`` 契约响应(403)。
        """
        if not request.user.is_authenticated:
            return True   # 登录/验证码/刷新 token 等 AllowAny 接口不归这里管
        if (request.method, request.path) in BAN_EXEMPT:
            return True
        if get_profile(request.user).status == ProfileStatus.BANNED_HEAVY:
            raise PermissionDenied("账号已被封禁,如有疑问请联系客服")
        return True
