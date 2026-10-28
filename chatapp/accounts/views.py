"""账号与鉴权接口:健康检查、发码、校验登录、刷新令牌。

设计要点:
    1. **响应路径不做任何第三方网络调用**:短信发送与 IM 建号/踢会话一律入队
       Celery 任务,避免第三方抖动拖垮接口响应;
    2. 登录成功即 ``session_version += 1``,旧设备令牌随即失效(单设备登录);
    3. 短信任务入队失败时回滚限流占位并返回 503(fail-closed)—— 否则用户会被
       60 秒重发间隔卡死,既拿不到码也不能重试。

关联文档:
    - 接口契约:docs/api/auth.md、docs/api/health.md
"""

import logging

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection, transaction
from django.db.models import F
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenRefreshView
from django_redis import get_redis_connection

from im import tasks as im_tasks
from notifications.tasks import send_sms_code

from . import services
from .exceptions import SingleDeviceSessionConflict, SmsServiceUnavailable
from .serializers import PhoneSerializer, SmsVerifySerializer
from .throttles import ProbeThrottle, SmsSendThrottle, SmsVerifyThrottle
from .tokens import SessionRefreshToken

User = get_user_model()

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([ProbeThrottle])
def health(request):
    """存活探针。

    Args:
        request: DRF 请求对象。

    Returns:
        固定 ``{"status": "ok"}``,不触碰数据库与 Redis。
    """
    return Response({"status": "ok"})


def _probe_db():
    """数据库探针:执行一次 ``SELECT 1``,失败时抛异常。"""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def _probe_redis():
    """Redis 探针:写入后读回并校验往返一致,失败时抛异常。"""
    conn = get_redis_connection("default")
    conn.set("readyz:probe", "1", ex=10)
    if conn.get("readyz:probe") != b"1":
        raise RuntimeError("redis round-trip mismatch")


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([ProbeThrottle])
def readyz(request):
    """就绪探针:逐项检查数据库与 Redis。

    Args:
        request: DRF 请求对象。

    Returns:
        全部依赖可用时返回 200 + ``{"status": "ok", "checks": {...}}``;
        任一依赖不可用时返回 503 + ``status="unavailable"``,便于负载均衡摘除实例。
    """
    checks = {}
    for name, probe in (("db", _probe_db), ("redis", _probe_redis)):
        try:
            probe()
            checks[name] = "ok"
        except Exception:
            logger.exception("readyz 探针失败: %s", name)
            checks[name] = "error"
    ok = all(v == "ok" for v in checks.values())
    return Response(
        {"status": "ok" if ok else "unavailable", "checks": checks},
        status=200 if ok else 503,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SmsSendThrottle])
def sms_send(request):
    """发送短信验证码(POST /api/v1/auth/sms/send)。

    先占用限流键并落库验证码,再入队发送任务;入队失败会回滚限流占位与验证码,
    让用户可以立刻重试。

    Args:
        request: DRF 请求对象,body 需带 ``phone``。

    Returns:
        ``{"status": "ok"}``。

    Raises:
        SmsSendTooFrequent: 距上次发送不足重发间隔。
        SmsServiceUnavailable: 短信任务入队失败(fail-closed)。
    """
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
@throttle_classes([SmsVerifyThrottle])
def sms_verify(request):
    """校验验证码并登录(POST /api/v1/auth/sms/verify)。

    号码未注册过则自动建号;登录成功即递增 ``session_version`` 使旧设备令牌失效,
    并在事务提交后入队 IM 建号或标记待踢旧会话。

    Args:
        request: DRF 请求对象,body 需带 ``phone`` 与 ``code``。

    Returns:
        ``{access, refresh, is_new_user, user_id}``。

    Raises:
        SmsCodeExpired: 验证码已过期或不存在。
        SmsCodeWrong: 验证码错误。
        SmsLocked: 连续错误次数超限。
    """
    serializer = SmsVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data["phone"]
    services.check_code(phone, serializer.validated_data["code"])

    user, created = User.objects.get_or_create(phone=phone)
    # 单设备登录:版本 +1 作废旧令牌;IM 建号/踢旧会话交给队列(响应路径不做外部调用)。
    # 用 F() 在数据库内自增,避免「读—加一—写」在并发登录时两个请求都拿到同一个旧版本,
    # 结果两台设备都以为自己是有效会话(M12)。
    User.objects.filter(pk=user.pk).update(session_version=F("session_version") + 1)
    user.refresh_from_db(fields=["session_version"])

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
        # 会话版本同步给 imserver:新设备即使不拉签名,旧 token 也会在任务完成后失效
        im_tasks.sync_session_version.delay(user.id)

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
        """校验 refresh token 的会话版本,再交给父类换发新令牌。

        Args:
            request: DRF 请求对象,body 需带 ``refresh``。
            *args: 透传给父类的位置参数。
            **kwargs: 透传给父类的关键字参数。

        Returns:
            父类返回的新 ``{access, refresh}``。

        Raises:
            SingleDeviceSessionConflict: 令牌格式合法但会话版本已过期,
                即该 refresh token 来自已被顶下线的设备。
        """
        try:
            token = SessionRefreshToken(request.data.get("refresh", ""))
        except Exception:
            return super().post(request, *args, **kwargs)   # 格式不合法等交给父类报错
        user = User.objects.filter(id=token.get("user_id")).first()
        if user is None or token.get("session_version") != user.session_version:
            raise SingleDeviceSessionConflict()
        return super().post(request, *args, **kwargs)
