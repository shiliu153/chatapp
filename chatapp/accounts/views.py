import logging

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenRefreshView

from im import tasks as im_tasks
from notifications.tasks import send_sms_code

from . import services
from .exceptions import SingleDeviceSessionConflict, SmsServiceUnavailable
from .serializers import PhoneSerializer, SmsVerifySerializer
from .throttles import SmsSendThrottle
from .tokens import SessionRefreshToken

User = get_user_model()

logger = logging.getLogger(__name__)


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
    phone = serializer.validated_data["phone"]
    code = services.issue_code(phone)
    try:
        send_sms_code.delay(phone, code)
    except Exception:
        # 入队失败用户拿不到码:回滚占位与码并 fail-closed,否则用户被 60 秒间隔卡死
        services.rollback_send(phone)
        logger.exception("短信任务入队失败 phone=%s", phone)
        raise SmsServiceUnavailable()
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([AllowAny])
def sms_verify(request):
    serializer = SmsVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data["phone"]
    services.check_code(phone, serializer.validated_data["code"])

    user, created = User.objects.get_or_create(phone=phone)
    # 单设备登录:版本 +1 作废旧令牌;IM 建号/踢旧会话交给队列(响应路径不做外部调用)
    previous_version = user.session_version
    user.session_version = previous_version + 1
    user.save(update_fields=["session_version"])

    def _after_commit():
        # robust=True:broker 抖动不会把已提交的登录拖成 500
        if created:
            im_tasks.import_account.delay(user.id)
        else:
            # 单设备:标记「待踢旧 IM 会话」,由新设备在 /im/user_sig 拉签名前同步踢
            # (踢必须早于新会话建立;延迟任务只兜底 App 不来拉签名的情况)
            cache.set(im_tasks.kick_pending_key(user.id), 1, im_tasks.KICK_PENDING_TTL)
            im_tasks.kick_pending.apply_async(
                args=[user.id], countdown=im_tasks.KICK_BACKSTOP_DELAY)

    transaction.on_commit(_after_commit, robust=True)

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
