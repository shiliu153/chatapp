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
        if not request.user.is_authenticated:
            return True   # 登录/验证码/刷新 token 等 AllowAny 接口不归这里管
        if (request.method, request.path) in BAN_EXEMPT:
            return True
        if get_profile(request.user).status == ProfileStatus.BANNED_HEAVY:
            raise PermissionDenied("账号已被封禁,如有疑问请联系客服")
        return True
