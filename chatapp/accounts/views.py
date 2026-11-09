"""账号与鉴权接口:健康检查、发码、校验登录、刷新令牌、注销、退出所有设备、登录设备。

设计要点:
    1. **响应路径不做任何第三方网络调用**:短信发送与 IM 建号/踢会话一律入队
       Celery 任务,避免第三方抖动拖垮接口响应;
    2. 登录成功即把**本端**的会话版本 +1(``accounts.device_session.bump``),
       同类端的旧设备令牌随即失效;另一端不受影响(多端在线,批次 K);
    3. 短信任务入队失败时回滚限流占位并返回 503(fail-closed)—— 否则用户会被
       60 秒重发间隔卡死,既拿不到码也不能重试;
    4. 登录设备(批次 M)的「看」与「踢单端」都只经 ``accounts.device_session``
       与 ``im.tasks`` 两个入口,视图里不直接读写 ``DeviceSession``。

关联文档:
    - 接口契约:docs/api/auth.md、docs/api/health.md
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import (APIException, AuthenticationFailed, ParseError,
                                       PermissionDenied)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenBackendError, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.state import token_backend
from rest_framework_simplejwt.views import TokenRefreshView
from django_redis import get_redis_connection

from config import metrics
from im import tasks as im_tasks
from notifications.tasks import send_sms_code

from . import device_session, services
from .cookies import (clear_refresh_cookie, same_origin, set_refresh_cookie,
                      wants_cookie)
from .exceptions import InvalidClientType, SingleDeviceSessionConflict, SmsServiceUnavailable
from .serializers import PhoneSerializer, SmsVerifySerializer
from .throttles import (LogoutThrottle, ProbeThrottle, SmsSendThrottle,
                        SmsVerifyThrottle)
from .tokens import SessionRefreshToken

User = get_user_model()

logger = logging.getLogger(__name__)


@extend_schema(responses={200: inline_serializer("HealthStatus", fields={
    "status": serializers.CharField(),
})})
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


@extend_schema(responses={200: inline_serializer("ReadyStatus", fields={
    "status": serializers.CharField(),
    "checks": serializers.DictField(),
})})
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


@extend_schema(request=PhoneSerializer, responses={200: inline_serializer(
    "SmsSendStatus", fields={"status": serializers.CharField()})})
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
        PhoneNotAllowed: 号码不在封闭测试白名单内(B-1 / K-1)。
        SmsSendTooFrequent: 距上次发送不足重发间隔。
        SmsServiceUnavailable: 短信任务入队失败(fail-closed)。
    """
    serializer = PhoneSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data["phone"]
    # B-1:白名单闸门放在发码之前 —— 非受邀号码不占限流键、不落码、不入队
    services.ensure_phone_allowed(phone)
    code = services.issue_code(phone)
    try:
        send_sms_code.delay(phone, code)
    except Exception:
        # 入队失败用户拿不到码:回滚占位与码并 fail-closed,否则用户被 60 秒间隔卡死
        services.rollback_send(phone)
        logger.exception("短信任务入队失败 phone=%s", phone)
        raise SmsServiceUnavailable()
    return Response({"status": "ok"})


@extend_schema(request=SmsVerifySerializer, responses={200: inline_serializer(
    "SmsVerifyResult", fields={
        "access": serializers.CharField(),
        "refresh": serializers.CharField(required=False),
        "is_new_user": serializers.BooleanField(),
        "user_id": serializers.IntegerField(),
    })})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SmsVerifyThrottle])
def sms_verify(request):
    """校验验证码并登录(POST /api/v1/auth/sms/verify)。

    号码未注册过则自动建号;登录成功即把**本端**的会话版本 +1,使同类端的旧设备
    令牌失效(另一端不受影响),并在事务提交后入队 IM 建号或标记待踢旧会话。

    端类型由请求头 ``X-Client`` 决定(``web`` / 其余与缺省一律 ``app``);
    之后一律按令牌里的 ``ct`` 回查,不再看请求头。

    Args:
        request: DRF 请求对象,body 需带 ``phone`` 与 ``code``。

    Returns:
        ``{access, is_new_user, user_id}``;带 ``X-Client: web`` 的请求不返回
        ``refresh``,改为下发 HttpOnly Cookie(App 分支保持原样)。

    Raises:
        PhoneNotAllowed: 号码不在封闭测试白名单内(B-1 / K-1)。
        SmsCodeExpired: 验证码已过期或不存在。
        SmsCodeWrong: 验证码错误。
        SmsLocked: 连续错误次数超限。
    """
    serializer = SmsVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data["phone"]
    # 业务指标(E-4 ③):只分「成功 / 被拒」两档。标签里不放手机号,也不细分被拒原因
    # —— 那会把时间序列基数撑开,而「被拒有多少次」已经够判断「是不是有人在试探」。
    try:
        # B-1:校验入口再拦一次(纵深防御)—— 白名单可能在码已下发之后才收紧
        services.ensure_phone_allowed(phone)
        services.check_code(phone, serializer.validated_data["code"])
    except APIException:
        metrics.LOGINS.labels(result="rejected").inc()
        raise

    try:
        user, created = User.objects.get_or_create(phone=phone)
    except IntegrityError:
        # 全新号码并发登录时,后到者会撞 phone 的唯一约束:回查一次即可(L-1)
        user = User.objects.get(phone=phone)
        created = False
    # C-1:运营账号(staff/superuser)不走短信登录。固定验证码 + 可猜的管理员手机号
    # 会让「最高权限的 API 身份」被直接接管;运营后台用账号口令 + TOTP。
    # 封闭测试环境确需用运营账号登 App 时,显式设 SMS_ALLOW_STAFF_LOGIN=1。
    if (user.is_staff or user.is_superuser) and not settings.SMS_ALLOW_STAFF_LOGIN:
        metrics.LOGINS.labels(result="rejected").inc()
        raise PermissionDenied("运营账号请使用运营后台登录")
    # 多端:只递增**本端**版本(同类互顶),另一端不受影响。用 F() 在数据库内自增,
    # 避免「读—加一—写」在并发登录时两个请求都拿到同一个旧版本,结果两台设备都以为
    # 自己是有效会话(M12)。IM 建号/踢旧会话交给队列(响应路径不做外部调用)。
    # 同一个入口顺带清掉该端的「已下线」标记与刷新活跃时间:被下线过的端重新登录后
    # 必须重新出现在登录设备列表里,而版本号继续单调递增,下线前的旧令牌仍然无效。
    client_type = device_session.client_type_of(request)
    device_session.login(user, client_type)

    def _after_commit():
        # robust=True:broker 抖动不会把已提交的登录拖成 500
        if created:
            im_tasks.import_account.delay(user.id)
        else:
            # 标记「本端待踢旧 IM 会话」,由新设备在 /im/user_sig 拉签名前同步踢
            # (踢必须早于新会话建立;延迟任务只兜底 App 不来拉签名的情况)。
            # 标记必须带端维度:否则 Web 登录会把 App 的在线 IM 会话也踢掉。
            cache.set(im_tasks.kick_pending_key(user.id, client_type), 1,
                      im_tasks.KICK_PENDING_TTL)
            im_tasks.kick_pending.apply_async(
                args=[user.id, client_type], countdown=im_tasks.KICK_BACKSTOP_DELAY)
        # 会话版本同步给 imserver:新设备即使不拉签名,旧 token 也会在任务完成后失效
        im_tasks.sync_session_version.delay(user.id)

    transaction.on_commit(_after_commit, robust=True)

    refresh = SessionRefreshToken.for_user(user, client_type)
    payload = {
        "access": str(refresh.access_token),
        "is_new_user": created,
        "user_id": user.id,
    }
    metrics.LOGINS.labels(result="success").inc()
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
    client_type = device_session.client_type_of_token(claims)
    if user is None or device_session.legacy_token_version(claims) != \
            device_session.current_version(user, client_type):
        raise SingleDeviceSessionConflict()
    return cached


@extend_schema(request=inline_serializer("TokenRefreshBody", fields={
    "refresh": serializers.CharField(required=False)}),
    responses={200: inline_serializer("TokenRefreshResult", fields={
        "access": serializers.CharField(),
        "refresh": serializers.CharField(required=False)})})
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
        # 按令牌里的 ct 校验**该端**版本:Web 的 refresh 换出来的 access 仍是 web 端,
        # 不会把 App 顶掉;轮换后的 refresh 由 simplejwt 从旧 refresh 复制全部 claim,
        # 因此 ct / session_version 自动带过去(有专门的用例钉住)。
        client_type = device_session.client_type_of_token(token)
        if user is None or device_session.legacy_token_version(token) != \
                device_session.current_version(user, client_type):
            raise SingleDeviceSessionConflict()

        serializer = TokenRefreshSerializer(data={"refresh": raw})
        serializer.is_valid(raise_exception=True)
        # 刷新成功 = 这一端确实还在用,顺带刷新登录设备列表的「最近活跃时间」
        device_session.touch(user, client_type)
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


@extend_schema(request=inline_serializer("LogoutBody", fields={
    "refresh": serializers.CharField(required=False)}),
    responses={204: None})
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


@extend_schema(request=None, responses={204: None})
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([LogoutThrottle])
def logout_all(request):
    """退出所有设备:两端会话版本各 +1,并踢掉全部在线 IM 会话。

    为什么两个端都 +1:这是「手机丢了,一键全端下线」的语义 —— 只递增本端会让
    另一台设备继续在线。踢 IM 会话必须走 Celery:响应路径禁止外部调用。

    两端同样打上 ``logged_out_at`` 标记(下线 = 打标记不是删行),于是退出之后
    ``GET /api/v1/devices`` 是空列表 —— 与 1.7 单端下线的可观察语义保持一致;
    哪一端重新登录,哪一端就重新出现,版本号继续单调递增,旧令牌始终无效。

    Args:
        request: DRF 请求对象(必须已认证)。

    Returns:
        204 空响应,附带清除 Cookie 的 ``Set-Cookie``;之后两端的 access 与
        refresh 全部失效。
    """
    user = request.user
    for client_type in device_session.CLIENT_TYPES:
        device_session.logout(user, client_type)
    im_tasks.kick_all_devices.delay(user.id)   # 响应路径不做外部调用
    response = Response(status=204)
    clear_refresh_cookie(response)
    return response


@extend_schema(parameters=[OpenApiParameter(
    "X-Client", str, OpenApiParameter.HEADER, required=False,
    description="客户端类型。填 web 表示网页端,current 落在 web 那行;"
                "缺省(含不带该头)按 app 处理")],
    responses={200: inline_serializer("DeviceListResult", fields={
        "results": serializers.ListField(child=inline_serializer("DeviceItem", fields={
            "client_type": serializers.CharField(),
            "client_label": serializers.CharField(),
            "current": serializers.BooleanField(),
            "created_at": serializers.DateTimeField(),
            "last_active_at": serializers.DateTimeField(allow_null=True),
        }))})})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def devices(request):
    """登录设备列表(GET /api/v1/devices)。

    只列**当前在用**的端(一类端一行,最多两行),``current`` 由请求头 ``X-Client``
    判定 —— 缺省与未知取值一律按 ``app``,与签发令牌时的口径完全一致。

    **已下线的端不返回**:被 ``DELETE /api/v1/devices/{client_type}``(或
    ``POST /auth/logout/all``)下线过的端,会话行还留着(版本号要单调递增,好让它的
    旧令牌一直失效),但 ``logged_out_at`` 有值,因此从列表里消失;该端**重新登录**
    后标记被清空,就会重新出现。

    为什么不在服务端判「在线」:在线是**账号级**的 ``presence``(120 秒窗口),
    按端拆要动心跳链路;这里只给「最近活跃时间」,让用户自己判断哪台设备还在用。

    Args:
        request: DRF 请求对象(必须已认证)。

    Returns:
        ``{"results": [{client_type, client_label, current, created_at,
        last_active_at}]}``;``last_active_at`` 为 ``null`` 表示该端只有登录记录、
        还没刷新过令牌(批次 M 上线前建的行)。从没登录过、已下线的端不出现。
    """
    current = device_session.client_type_of(request)
    rows = [{
        "client_type": session.client_type,
        "client_label": device_session.label_of(session.client_type),
        "current": session.client_type == current,
        "created_at": session.created_at,
        "last_active_at": session.last_active_at,
    } for session in device_session.sessions_of(request.user)]
    return Response({"results": rows})


@extend_schema(responses={204: None})
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def device_logout(request, client_type):
    """下线指定端的登录会话(DELETE /api/v1/devices/{client_type})。

    三步走:① 该端的会话版本 +1,让这台设备的 access / refresh 立刻失效
    (下一次请求拿到 ``401`` + ``40101``);② 打上 ``logged_out_at`` 标记 ——
    **下线是标记,不是删行**,该端随即从 ``GET /api/v1/devices`` 里消失,但会话行
    留着、版本号继续单调递增,免得上线前的旧令牌因为「行没了、版本回到默认值」
    重新变有效;③ 经 Celery 踢掉该端在线的 IM 连接 —— 响应路径禁止外部调用。
    **另一端不受影响**。

    幂等:该端本来就没有会话行、或重复下线,都返回 204(与 ``POST /auth/logout``
    同口径),``logged_out_at`` 只刷新成最新时间。允许踢当前正在用的这一端:语义等同
    「注销本端」,服务端不做特判,客户端收到 204 后自行回登录页。

    Args:
        request: DRF 请求对象(必须已认证)。
        client_type: 路径参数,``app`` 或 ``web``。

    Returns:
        204 空响应。

    Raises:
        InvalidClientType: ``client_type`` 不是 ``app`` / ``web``(400 + 40004)。
    """
    if client_type not in device_session.CLIENT_TYPES:
        raise InvalidClientType()
    device_session.logout(request.user, client_type)
    im_tasks.kick_device.delay(request.user.id, client_type)   # 响应路径不做外部调用
    return Response(status=204)
