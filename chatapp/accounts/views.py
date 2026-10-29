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

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.db.models import F
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import (AuthenticationFailed, ParseError,
                                       PermissionDenied)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenBackendError, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.state import token_backend
from rest_framework_simplejwt.views import TokenRefreshView
from django_redis import get_redis_connection

from im import tasks as im_tasks
from notifications.tasks import send_sms_code

from . import services
from .cookies import (clear_refresh_cookie, same_origin, set_refresh_cookie,
                      wants_cookie)
from .exceptions import SingleDeviceSessionConflict, SmsServiceUnavailable
from .serializers import PhoneSerializer, SmsVerifySerializer
from .throttles import (LogoutThrottle, ProbeThrottle, SmsSendThrottle,
                        SmsVerifyThrottle)
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
        ``{access, is_new_user, user_id}``;带 ``X-Client: web`` 的请求不返回
        ``refresh``,改为下发 HttpOnly Cookie(App 分支保持原样)。

    Raises:
        SmsCodeExpired: 验证码已过期或不存在。
        SmsCodeWrong: 验证码错误。
        SmsLocked: 连续错误次数超限。
    """
    serializer = SmsVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data["phone"]
    services.check_code(phone, serializer.validated_data["code"])

    try:
        user, created = User.objects.get_or_create(phone=phone)
    except IntegrityError:
        # 全新号码并发登录时,后到者会撞 phone 的唯一约束:回查一次即可(L-1)
        user = User.objects.get(phone=phone)
        created = False
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
    payload = {
        "access": str(refresh.access_token),
        "is_new_user": created,
        "user_id": user.id,
    }
    if wants_cookie(request):
        # Web:refresh 只进 HttpOnly Cookie,JS 读不到,30 天的长期凭证不再暴露给页面脚本。
        response = Response(payload)
        set_refresh_cookie(response, str(refresh))
        return response
    payload["refresh"] = str(refresh)
    return Response(payload)


def _grace_key(jti: str) -> str:
    """拼出「旧 refresh 的 jti → 轮换后的新 refresh」缓存键。"""
    return f"auth:refresh_grace:{jti}"


def _body_refresh(request) -> str:
    """读取请求体里的 refresh token。

    Web 走 Cookie 时请求体是空的,而 DRF 解析空 JSON 体会抛 ``ParseError``;
    这里把它当作「没带」处理,交给 Cookie 分支。

    Args:
        request: DRF 请求对象。

    Returns:
        请求体里的 refresh 原文;没有或解析失败时返回空串。
    """
    try:
        data = request.data
    except ParseError:
        return ""
    return data.get("refresh", "") if hasattr(data, "get") else ""


def _reuse_within_grace(raw_token: str) -> str | None:
    """宽限期内复用旧 refresh 时,取回轮换时缓存的新 refresh。

    多标签页同时刷新会先后打到同一个旧 refresh:先到者轮换并把它拉黑,
    后到者落在宽限期内,应当拿到同一对新令牌而不是被判会话失效。

    Args:
        raw_token: 客户端提交的旧 refresh token。

    Returns:
        缓存的新 refresh 原文;不在宽限期内(或签名/会话已失效)返回 ``None``。

    Raises:
        SingleDeviceSessionConflict: 令牌本身有效,但账号已被其它设备顶下线。
    """
    try:
        claims = token_backend.decode(raw_token, verify=True)
    except TokenBackendError:
        return None
    cached = cache.get(_grace_key(claims.get("jti", "")))
    if not cached:
        return None
    user = User.objects.filter(id=claims.get("user_id")).first()
    if user is None or claims.get("session_version") != user.session_version:
        raise SingleDeviceSessionConflict()
    return cached


class SessionTokenRefreshView(TokenRefreshView):
    """刷新 access token:Web 走 Cookie,App 走请求体。

    轮换后的 refresh 会写进 ``REFRESH_REUSE_GRACE`` 秒的宽限缓存,
    让并发刷新的多个标签页都能拿到可用的令牌。
    """

    def post(self, request, *args, **kwargs):
        """校验会话版本后换发新令牌。

        Args:
            request: DRF 请求对象;``refresh`` 可放在请求体(App)或 Cookie(Web)。
            *args: 透传给父类的位置参数。
            **kwargs: 透传给父类的关键字参数。

        Returns:
            Web:``{access}`` + 轮换后的 Cookie;App:``{access, refresh}``。

        Raises:
            AuthenticationFailed: 没有令牌、令牌无效或超出宽限期的重复使用。
            SingleDeviceSessionConflict: 该 refresh token 来自已被顶下线的设备。
        """
        cookie_value = request.COOKIES.get(settings.REFRESH_COOKIE_NAME, "")
        raw = _body_refresh(request) or cookie_value
        web = wants_cookie(request) or bool(cookie_value)
        if not same_origin(request):
            # Cookie 会自动随请求带上,必须确认请求来自本站页面(M-3/L-4)
            raise PermissionDenied("跨站请求被拒绝")
        if not raw:
            raise AuthenticationFailed("登录状态已失效,请重新登录")

        try:
            token = SessionRefreshToken(raw)
        except TokenError as exc:
            if "blacklist" in str(exc).lower():
                cached = _reuse_within_grace(raw)
                if cached is not None:
                    return self._respond(str(SessionRefreshToken(cached).access_token), cached, web)
            raise AuthenticationFailed("登录状态已失效,请重新登录")

        user = User.objects.filter(id=token.get("user_id")).first()
        if user is None or token.get("session_version") != user.session_version:
            raise SingleDeviceSessionConflict()

        serializer = TokenRefreshSerializer(data={"refresh": raw})
        serializer.is_valid(raise_exception=True)
        new_refresh = serializer.validated_data.get("refresh", "")
        if new_refresh:
            cache.set(_grace_key(token.get("jti", "")), new_refresh,
                      settings.REFRESH_REUSE_GRACE)
        return self._respond(serializer.validated_data["access"], new_refresh, web)

    @staticmethod
    def _respond(access: str, refresh: str, web: bool) -> Response:
        """按客户端类型拼响应体与 Cookie。

        Args:
            access: 新签发的 access token。
            refresh: 当前有效的 refresh token(Web 会写进 Cookie)。
            web: 是否 Web 客户端。

        Returns:
            响应对象:Web 只返回 ``access`` 并下发 Cookie;App 返回两者。
        """
        if web:
            response = Response({"access": access})
            if refresh:
                set_refresh_cookie(response, refresh)
            return response
        payload = {"access": access}
        if refresh:
            payload["refresh"] = refresh
        return Response(payload)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LogoutThrottle])
def logout(request):
    """注销:拉黑 refresh token 并清除 Cookie(POST /api/v1/auth/logout)。

    幂等 —— 令牌缺失、已过期或已拉黑都返回 204,前端只关心「本地会话已结束」。
    按 IP 限流,避免匿名调用把黑名单表刷大(L-5)。

    Args:
        request: DRF 请求对象;``refresh`` 可放在请求体或 Cookie。

    Returns:
        204 空响应,附带清除 Cookie 的 ``Set-Cookie``。

    Raises:
        PermissionDenied: ``Origin`` 与本站不同源(仅 Cookie 场景需要,见 ``same_origin``)。
    """
    if not same_origin(request):
        raise PermissionDenied("跨站请求被拒绝")
    raw = _body_refresh(request) or request.COOKIES.get(settings.REFRESH_COOKIE_NAME, "")
    if raw:
        try:
            SessionRefreshToken(raw).blacklist()
        except Exception:
            # 已过期/已拉黑/缺 OutstandingToken 都无需处理:注销的目标是「以后不能用」。
            logger.info("注销时 refresh 已失效,忽略")
    response = Response(status=204)
    clear_refresh_cookie(response)
    return response
