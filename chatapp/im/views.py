from django.conf import settings
from django.core.cache import cache
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .client import ensure_account
from .signature import gen_user_sig

IMPORTED_FLAG_TTL = 30 * 24 * 3600   # 30 天;Redis 清空后下次调用会幂等重建


@api_view(["POST"])
def user_sig(request):
    # 重封禁由全局权限类 IsNotHeavyBanned 拦下,这里不再重复检查
    user = request.user
    # IM 账号供给归 IM 域自己保证:首次调用同步建号(幂等,7015 视为成功),
    # 失败不置标记,下次调用再试;这样鉴权路径永远不碰腾讯 REST
    flag = f"im:imported:{user.id}"
    if not cache.get(flag) and ensure_account(user.im_user_id):
        cache.set(flag, 1, IMPORTED_FLAG_TTL)
    return Response({
        "user_sig": gen_user_sig(user.im_user_id),
        "sdkappid": settings.IM_SDKAPPID,
        "im_user_id": user.im_user_id,
        "expire": settings.IM_SIG_EXPIRE,
    })
