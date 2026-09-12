from django.conf import settings
from django.core.cache import cache
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .client import ensure_account, kick_user
from .signature import gen_user_sig
from .tasks import kick_pending_key

IMPORTED_FLAG_TTL = 30 * 24 * 3600   # 30 天;Redis 清空后下次调用会幂等重建


@api_view(["POST"])
def user_sig(request):
    # 重封禁由全局权限类 IsNotHeavyBanned 拦下,这里不再重复检查
    user = request.user
    # IM 账号供给归 IM 域自己保证:首次调用同步建号(幂等,7015 视为成功),
    # 失败不置标记,下次调用再试;这样鉴权路径永远不碰腾讯 REST
    imported_flag = f"im:imported:{user.id}"
    if not cache.get(imported_flag) and ensure_account(user.im_user_id):
        cache.set(imported_flag, 1, IMPORTED_FLAG_TTL)

    # 单设备:本次登录作废了旧会话(verify 时打了标记)→ 先踢旧 IM 会话再发签名。
    # ⚠️ 顺序不能反:踢发生在新会话建立之前才安全,否则会把本机刚建的会话一起踢掉,
    # 客户端收到 KickOffline 会误报「账号已在其他设备登录」(2026-09-12 手测回归)
    kick_flag = kick_pending_key(user.id)
    if cache.get(kick_flag) and kick_user(user.im_user_id):
        cache.delete(kick_flag)

    return Response({
        "user_sig": gen_user_sig(user.im_user_id),
        "sdkappid": settings.IM_SDKAPPID,
        "im_user_id": user.im_user_id,
        "expire": settings.IM_SIG_EXPIRE,
    })
