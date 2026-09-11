from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .signature import gen_user_sig


@api_view(["POST"])
def user_sig(request):
    # 重封禁由全局权限类 IsNotHeavyBanned 拦下,这里不再重复检查
    return Response({
        "user_sig": gen_user_sig(request.user.im_user_id),
        "sdkappid": settings.IM_SDKAPPID,
        "im_user_id": request.user.im_user_id,
        "expire": settings.IM_SIG_EXPIRE,
    })
