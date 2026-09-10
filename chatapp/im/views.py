from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from users.models import ProfileStatus
from users.services import get_profile

from .signature import gen_user_sig


@api_view(["POST"])
def user_sig(request):
    profile = get_profile(request.user)
    if profile.status == ProfileStatus.BANNED_HEAVY:
        raise PermissionDenied("账号已被封禁")
    return Response({
        "user_sig": gen_user_sig(request.user.im_user_id),
        "sdkappid": settings.IM_SDKAPPID,
        "im_user_id": request.user.im_user_id,
        "expire": settings.IM_SIG_EXPIRE,
    })
