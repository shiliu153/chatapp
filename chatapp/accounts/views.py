from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenRefreshView

from im.client import import_account, kick_and_logout

from . import services
from .exceptions import SingleDeviceSessionConflict
from .models import SESSION_VERSION_DEFAULT
from .serializers import PhoneSerializer, SmsVerifySerializer
from .throttles import SmsSendThrottle
from .tokens import SessionRefreshToken

User = get_user_model()


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SmsSendThrottle])
def sms_send(request):
    serializer = PhoneSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    services.send_code(serializer.validated_data["phone"])
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([AllowAny])
def sms_verify(request):
    serializer = SmsVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data["phone"]
    services.check_code(phone, serializer.validated_data["code"])

    user, created = User.objects.get_or_create(phone=phone)
    # 单设备登录:版本 +1 作废旧令牌;有旧会话则把旧 IM 会话登出+踢掉,
    # 否则旧实例在线状态还在,本机 IM 登录可能被服务端拒绝(实测 6206)
    previous_version = user.session_version
    user.session_version = previous_version + 1
    user.save(update_fields=["session_version"])
    if created:
        transaction.on_commit(lambda: import_account(user.im_user_id))
    elif previous_version > SESSION_VERSION_DEFAULT:
        transaction.on_commit(lambda: kick_and_logout(user.im_user_id))
    refresh = SessionRefreshToken.for_user(user)
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "is_new_user": created,
        "user_id": user.id,
    })


class SessionTokenRefreshView(TokenRefreshView):
    """刷新时也校验会话版本:旧设备的 refresh token 一并作废。"""

    def post(self, request, *args, **kwargs):
        try:
            token = SessionRefreshToken(request.data.get("refresh", ""))
        except Exception:
            return super().post(request, *args, **kwargs)   # 格式不合法等交给父类报错
        user = User.objects.filter(id=token.get("user_id")).first()
        if user is None or token.get("session_version") != user.session_version:
            raise SingleDeviceSessionConflict()
        return super().post(request, *args, **kwargs)
