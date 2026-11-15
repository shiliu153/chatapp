"""封禁权限:重封禁用户全域 403。

设计要点:
    1. 本权限类是 DRF 的全局默认权限之一(见 ``settings.REST_FRAMEWORK``),
       **新接口自动被覆盖**,不需要逐个视图声明;
    2. 白名单只放行 ``GET /users/me``(前端要展示封禁原因)与 ``GET /users/tags``;
    3. 轻封禁不在这里拦 —— 它只禁止滑卡,由 ``discovery.views.swipe`` 自己检查。
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
    """重封禁 → 全部业务接口 403;轻封禁只管滑卡(swipe 视图里另有检查)。"""

    def has_permission(self, request, view):
        """检查当前用户是否被重封禁。

        参数说明:
            request: DRF 请求对象。
            view: 当前视图;本权限不使用。

        返回参数:
            未被重封禁(或在白名单内)时返回 ``True``。

        使用示例:
            ``self.client.get("/api/v1/discovery/candidates")`` 在重封禁下返回 403(见
            ``moderation/tests.py`` 的
            ``IsNotHeavyBannedTests.test_heavy_banned_blocked_across_business_endpoints``)

        备注信息:
            主动抛出 ``PermissionDenied``:用户处于重封禁状态且访问的不是白名单接口
            (``BAN_EXEMPT``,只放行 ``GET /users/me`` 与 ``GET /users/tags``)。未登录请求
            直接返回 ``True``,AllowAny 接口(登录/验证码/刷新 token)不归这里管;
            轻封禁不在这里拦,只由 ``discovery.views.swipe`` 自己检查。
        """
        if not request.user.is_authenticated:
            return True   # 登录/验证码/刷新 token 等 AllowAny 接口不归这里管
        if (request.method, request.path) in BAN_EXEMPT:
            return True
        if get_profile(request.user).status == ProfileStatus.BANNED_HEAVY:
            raise PermissionDenied("账号已被封禁,如有疑问请联系客服")
        return True
