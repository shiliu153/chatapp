"""IM 接口:签发 userSig、上传聊天图片与语音、查语音转码状态、nginx 验签子请求。

设计要点:
    IM 账号的供给由本模块自己保证:首次调用同步建号,成功后在 Redis 置 30 天标记,
    之后不再重复建号。建号失败不置标记,下次调用自动重试。

注意事项:
    踢旧会话必须发生在**签发新签名之前**,顺序不能反 —— 反了会把本机刚建立的会话
    一起踢掉,客户端收到 KickOffline 会误报「账号已在其他设备登录」(2026-09-12 手测回归)。
    多端在线后「踢旧会话」只踢**本端**(``X-Client`` 决定的端类型),另一端的在线
    会话必须留着 —— 否则一个网页登录就把手机踢下线了。

    聊天图片上传是**同步落盘 + 同步生成缩略图**:这条路径没有任何第三方调用,
    符合「响应路径禁止外部调用」纪律;文件名带随机 uuid,不可枚举。
    聊天语音有两条路(第五轮审计 M-3):抢到转码槽时请求线程内同步转码,行为与响应字段
    与旧版完全一致(只多一个 ``status``);抢不到时落临时区并入队,回 **202 + pending**,
    客户端按 ``retry_after`` 轮询 ``GET /im/voices/{id}``。

    两个上传入口都接受可选请求头 ``Idempotency-Key``(逻辑在 ``config/idempotency.py``):
    同 key 的重试不重复落盘、不重复建行,并发同 key 后到的那个回 ``409`` + ``40901``;
    **不带时行为与加这一层之前逐字一致**(老客户端不受影响)。

关联文档:
    - 接口契约:docs/api/im.md
"""

import io
import logging
import uuid
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from PIL import Image
from rest_framework import serializers
from rest_framework.decorators import (api_view, authentication_classes,
                                      permission_classes, throttle_classes)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts import device_session
from config import error_codes, idempotency, images, storage, transcode_gate

from . import media_sign, transcode_queue, voice
from .client import ensure_account, kick_user, set_session_version
from .models import ChatImage, ChatVoice, TranscodeStatus
from .serializers import (VOICE_QUEUED_RESPONSE, ChatImageUploadSerializer,
                          ChatVoiceUploadSerializer, VoiceStatusSerializer)
from .tasks import kick_pending_key, transcode_chat_voice
from .throttles import (ChatImageThrottle, ChatVoiceThrottle, UserSigThrottle,
                        VoiceStatusThrottle)
from .token import mint_im_token

logger = logging.getLogger(__name__)

IMPORTED_FLAG_TTL = 30 * 24 * 3600   # 30 天;Redis 清空后下次调用会幂等重建


@extend_schema(request=None, responses={200: inline_serializer("ImUserSig", fields={
    "backend": serializers.CharField(),
    "token": serializers.CharField(),
    "im_user_id": serializers.CharField(),
    "ws_url": serializers.CharField(),
    "http_url": serializers.CharField(),
    "expire": serializers.IntegerField(),
})})
@api_view(["POST"])
@throttle_classes([UserSigThrottle])
def user_sig(request):
    """签发当前用户的 IM 登录凭证(POST /api/v1/im/user_sig)。

    重封禁用户由全局权限类 ``IsNotHeavyBanned`` 直接拦成 403,本函数不再重复检查。

    端类型取请求头 ``X-Client``(缺省 ``app``):只踢**本端**旧会话、按**本端**版本
    签发 token(``sv`` 是该端版本,``ct`` 是端类型),另一端的在线会话不受影响。

    参数说明:
        request: DRF 请求对象。

    返回参数:
        ``{backend, token, im_user_id, ws_url, http_url, expire}``;
        ``backend`` 恒为 ``self``(腾讯分支已于 2026-11-08 删除)。

    使用示例:
        ``resp = self.client.post("/api/v1/im/user_sig")``(见 ``im/tests.py`` 的 ``UserSigApiTests``)

    备注信息:
        首次调用同步建号并在缓存置 30 天标记,建号失败不置标记,下次调用自动重试。
        踢旧会话必须发生在签发新凭证之前,顺序反了会把本机刚建立的会话一起踢掉。
        会话版本同步失败时不签发 token,直接返回 503。
    """
    # 重封禁由全局权限类 IsNotHeavyBanned 拦下,这里不再重复检查
    user = request.user
    # IM 账号供给归 IM 域自己保证:首次调用同步建号(ensure_account 先查后建,
    # 不会覆盖已同步的昵称/头像),失败不置标记,下次调用再试
    imported_flag = f"im:imported:{user.id}"
    if not cache.get(imported_flag) and ensure_account(user.im_user_id):
        cache.set(imported_flag, 1, IMPORTED_FLAG_TTL)

    # 多端:本次登录只作废**本端**旧会话(verify 时打了按端的标记)→ 先踢本端旧 IM
    # 会话再发凭证,另一端的在线会话必须留着。
    # 顺序不能反:踢必须发生在新会话建立之前,否则会把本机刚建的会话一起踢掉,
    # 客户端收到 KickOffline 会误报「账号已在其他设备登录」(2026-09-12 手测回归)
    client_type = device_session.client_type_of(request)
    kick_flag = kick_pending_key(user.id, client_type)
    if cache.get(kick_flag) and kick_user(user.im_user_id, client_type=client_type):
        cache.delete(kick_flag)

    nickname = getattr(getattr(user, "profile", None), "nickname", "") or ""
    ensure_account(user.im_user_id, nickname)   # 失败不阻断签发
    # 版本必须先落到 imserver 再签发 token:否则新 token 带的是 imserver 还没见过的
    # 版本,连接会被自己拒绝;同步失败则 fail-closed(H3)。
    # 取不到端会话行时按历史列补建一行(不递增),绝不签一个「谁都没见过」的版本。
    version = device_session.ensure_version(user, client_type)
    if not set_session_version(user.im_user_id, version, client_type=client_type):
        return Response({"code": 503, "message": "IM 暂不可用,请稍后重试"}, status=503)
    return Response({
        "backend": "self",
        "token": mint_im_token(user.id, settings.IM_SELF_TOKEN_TTL,
                               version, client_type),
        "im_user_id": user.im_user_id,
        "ws_url": settings.IM_SELF_WS_URL,
        "http_url": settings.IM_SELF_HTTP_URL,
        "expire": settings.IM_SELF_TOKEN_TTL,
    })


@extend_schema(request=ChatImageUploadSerializer,
               parameters=[idempotency.schema_parameter()],
               responses={201: inline_serializer("ChatImageUploaded", fields={
                   "id": serializers.IntegerField(),
                   "url": serializers.CharField(),
                   "thumb_url": serializers.CharField(),
                   "width": serializers.IntegerField(),
                   "height": serializers.IntegerField(),
                   "size": serializers.IntegerField(),
               })})
@api_view(["POST"])
@throttle_classes([ChatImageThrottle])
def upload_image(request):
    """上传一张聊天图片(POST /api/v1/im/images)。

    同步落盘 + 生成缩略图,不进 Celery:这条路径没有第三方调用,
    符合「响应路径禁止外部调用」纪律。文件名带随机 uuid,不可枚举。

    参数说明:
        request: DRF 请求对象,multipart 字段为 ``file``;请求头可带
            ``Idempotency-Key``(可选,不带时行为与加幂等之前逐字一致)。

    返回参数:
        201 + ``{id, url, thumb_url, width, height, size}``;URL 用
        ``settings.MEDIA_BASE_URL`` 拼绝对地址(与 IM 头像同步同一套)。
        同一个 ``Idempotency-Key`` 的重试返回同一行、同一个 201 响应体(不落盘、不建行);
        并发同 key 时后到的那个 409 + ``40901``。

    使用示例:
        ``self.client.post(self.url, {"file": SimpleUploadedFile("a.png", PNG_1PX, content_type="image/png")}, format="multipart")``
        (见 ``im/tests.py`` 的 ``ChatImageUploadTests.upload``,其中 ``self.url = "/api/v1/im/images"``)

    备注信息:
        配额检查在任何一次落盘之前完成,超限时抛 ``config.storage.StorageQuotaExceeded``
        (413/``41301``),库内与磁盘上都不留痕迹。
        非图片、尺寸超限返回 400;格式与大小的校验在 ``ChatImageUploadSerializer`` 里。
        幂等映射只存「id + 状态」(Redis,24 小时):重放时按 id 回查那一行重新签名,
        而不是回放存下来的签名地址 —— 签名是会过期的,存下来的地址重放时可能已经失效。
        本次请求没写成结果就退出 ``with``(400/413/503/异常)会释放 key,用户改好文件
        用同一个 key 重传不会被自己挡住。
    """
    with idempotency.guard(request, idempotency.IMAGE) as session:
        if session.saved is not None:
            replayed = ChatImage.objects.filter(owner=request.user,
                                                id=session.saved["id"]).first()
            if replayed is not None:
                return Response(_image_payload(replayed), status=201)
            # 行已被运营删除或 30 天回收:映射指向空处,丢掉它按首次请求重来
            session.discard()

        serializer = ChatImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        try:
            image = images.open_checked(upload.read())
        except images.ImageError as error:
            return Response({"code": 400, "message": str(error)}, status=400)

        if max(image.size) > settings.CHAT_IMAGE_MAX_SIDE:
            return Response({"code": 400, "message": "图片尺寸过大,请先压缩"}, status=400)

        normalized = images.normalize(image)
        stem = f"{request.user.id}-{uuid.uuid4().hex}"

        thumb = normalized.image.copy()
        thumb.thumbnail((settings.CHAT_IMAGE_THUMB_SIDE, settings.CHAT_IMAGE_THUMB_SIDE),
                        Image.Resampling.LANCZOS)
        thumb_buffer = io.BytesIO()
        thumb.convert("RGB").save(thumb_buffer, "JPEG", quality=80)
        thumb_data = thumb_buffer.getvalue()

        # 配额必须查在**任何一次落盘之前**:``FileField.save(save=False)`` 会立即把文件写进
        # 存储,先写后查会在超限时留下没有数据库行的孤儿文件,配额对磁盘占用就失效了(M-1)。
        storage.ensure_quota(request.user, len(normalized.data) + len(thumb_data))

        # upload_to 已经是 ``chat/%Y/%m/``,这里只给文件名 —— 再拼一遍 "chat/年/月"
        # 会落成 media/chat/2026/10/chat/2026/10/xxx.jpg(2026-10-26 部署时实测踩到)
        chat_image = ChatImage(owner=request.user, width=normalized.width,
                               height=normalized.height, bytes=len(normalized.data))
        chat_image.file.save(f"{stem}{normalized.extension}",
                             ContentFile(normalized.data), save=False)
        chat_image.thumb.save(f"{stem}_thumb.jpg",
                              ContentFile(thumb_data), save=False)
        chat_image.save()

        # 行已提交才写映射:重放路径会按这个 id 回查那一行
        session.remember(chat_image.id, idempotency.READY)
        return Response(_image_payload(chat_image), status=201)


def _image_payload(chat_image) -> dict:
    """把一条 ``ChatImage`` 渲染成上传响应体(首次上传与幂等重放共用一份)。

    参数说明:
        chat_image: 聊天图片行(``file`` / ``thumb`` 必须非空)。

    返回参数:
        ``{id, url, thumb_url, width, height, size}``;两个 URL 都是**这次**重新签名的
        限时绝对地址。

    使用示例:
        ``return Response(_image_payload(chat_image), status=201)``
        (见本模块 ``upload_image``)

    备注信息:
        抽出来是为了「重放」与「首次」不会各写一份而慢慢分叉 —— 幂等的承诺就是
        「两次响应体相同」,两份拼装代码是漂移的入口。
    """
    base = settings.MEDIA_BASE_URL.rstrip("/")
    return {
        "id": chat_image.id,
        "url": media_sign.sign_url(f"{base}{chat_image.file.url}"),
        "thumb_url": media_sign.sign_url(f"{base}{chat_image.thumb.url}"),
        "width": chat_image.width,
        "height": chat_image.height,
        "size": chat_image.bytes,
    }


def _queue_chat_voice(user, upload, duration_ms: int, session) -> Response:
    """把一次聊天语音上传改走异步:落临时区 + 建 pending 行 + 入队,回 202。

    参数说明:
        user: 发送者账号。
        upload: 已通过浅校验的上传文件。
        duration_ms: 客户端声明的时长(毫秒),worker 转码时与 ``ffprobe`` 实测值比对。
        session: 本次请求的幂等会话(``config.idempotency.Session``);行提交后把
            ``key → {id, status: pending}`` 写进 Redis,``pending`` 期间同 key 重试
            会拿回同一个 id。

    返回参数:
        202 + ``{id, status, retry_after}``(不带 ``url``);
        服务器缺 ``ffmpeg`` / ``ffprobe`` 时改回 503 + ``50302``。

    使用示例:
        ``return _queue_chat_voice(request.user, upload, declared_ms, session)``
        (见本模块 ``upload_voice``)

    备注信息:
        浅校验(大小 / MIME 白名单 / 声明时长上限)序列化器已经做过,深校验(实测时长)
        只能由 worker 做。入队挂在 ``transaction.on_commit`` 上:行先提交,任务才可能查到它。
        缺 ffmpeg 时**不受理**:否则客户端先拿到 202,再等来一个注定失败的转码,不如当场
        回 503 让客户端提示「语音暂不可用」(此时幂等 key 由 ``with`` 退出时释放)。
    """
    if not voice.ffmpeg_available():
        logger.error("聊天语音上传失败:服务器缺少 ffmpeg/ffprobe")
        return Response({"code": error_codes.CHAT_VOICE_UNAVAILABLE,
                         "message": "语音消息暂不可用"}, status=503)
    staged = transcode_queue.stage(upload.read(),
                                   transcode_queue.staged_name(upload.content_type))
    chat_voice = ChatVoice(owner=user, duration_ms=duration_ms, bytes=0,
                           mime=voice.base_content_type(upload.content_type),
                           transcode_status=TranscodeStatus.PENDING)
    chat_voice.file = staged
    chat_voice.save()
    voice_id = chat_voice.pk
    transaction.on_commit(lambda: transcode_chat_voice.delay(voice_id), robust=True)
    session.remember(voice_id, idempotency.PENDING)
    logger.info("chat_voice_queued", extra={"user_id": user.id, "voice_id": voice_id})
    return Response({"id": voice_id, "status": TranscodeStatus.PENDING,
                     "retry_after": transcode_gate.retry_after()}, status=202)


def _voice_payload(chat_voice) -> dict:
    """把一条已转码完成的 ``ChatVoice`` 渲染成上传响应体(首次上传与幂等重放共用)。

    参数说明:
        chat_voice: 聊天语音行(``transcode_status=ready`` 且 ``file`` 非空)。

    返回参数:
        ``{id, url, duration_ms, size, status}``;``url`` 是**这次**重新签名的限时地址。

    使用示例:
        ``return Response(_voice_payload(chat_voice), status=201)``
        (见本模块 ``upload_voice``)

    备注信息:
        与 ``_image_payload`` 同一理由:重放与首次共用一份拼装代码,幂等的承诺
        (两次响应体相同)才不会慢慢漂移。
    """
    base = settings.MEDIA_BASE_URL.rstrip("/")
    return {
        "id": chat_voice.id,
        "url": media_sign.sign_url(f"{base}{chat_voice.file.url}"),
        "duration_ms": chat_voice.duration_ms,
        "size": chat_voice.bytes,
        "status": TranscodeStatus.READY,
    }


def _replay_voice(user, saved: dict):
    """按 Redis 里存的结果重放一次聊天语音上传响应。

    参数说明:
        user: 当前账号(查询集限定在本人语音上,别人的 id 一律当不存在)。
        saved: 幂等会话里读到的映射 ``{"id": 行主键, "status": ready|pending}``。

    返回参数:
        可重放的 ``Response``;行已不可用(被删 / 转码失败 / ready 却没有文件)时返回 ``None``,
        由调用方丢掉映射后按首次请求重新处理。

    使用示例:
        ``replay = _replay_voice(request.user, session.saved)``(见本模块 ``upload_voice``)

    备注信息:
        状态取**首次响应的那个状态**:首次是 202,重放也是 202(同一个 id),客户端继续按
        ``retry_after`` 轮询 6.5 即可;首次是 201,重放按 id 重新签名算一份 201。
        ``failed`` 的行不重放:那说明上一次尝试已经失败,此时用户重传应当照常处理
        (与「失败释放 key」同一条口径)。
    """
    chat_voice = ChatVoice.objects.filter(owner=user, id=saved["id"]).first()
    if chat_voice is None or chat_voice.transcode_status == TranscodeStatus.FAILED:
        return None
    if saved["status"] == idempotency.PENDING:
        return Response({"id": chat_voice.id, "status": TranscodeStatus.PENDING,
                         "retry_after": transcode_gate.retry_after()}, status=202)
    if not chat_voice.file:
        return None
    return Response(_voice_payload(chat_voice), status=201)


@extend_schema(request=ChatVoiceUploadSerializer,
               parameters=[idempotency.schema_parameter()],
               responses={201: inline_serializer("ChatVoiceUploaded", fields={
                   "id": serializers.IntegerField(),
                   "url": serializers.CharField(),
                   "duration_ms": serializers.IntegerField(),
                   "size": serializers.IntegerField(),
                   "status": serializers.CharField(),
               }), 202: VOICE_QUEUED_RESPONSE})
@api_view(["POST"])
@throttle_classes([ChatVoiceThrottle])
def upload_voice(request):
    """上传一段聊天语音(POST /api/v1/im/voices)。

    抢到转码槽时同步执行:写临时文件 → ffprobe 校验时长 → ffmpeg 转 m4a → 落盘;
    抢不到时落临时区并入队,由 worker 异步转码。全程本地进程,没有第三方网络调用,
    符合「响应路径禁止外部调用」纪律。

    参数说明:
        request: DRF 请求对象,multipart 字段为 ``file`` 与 ``duration_ms``;请求头可带
            ``Idempotency-Key``(可选,不带时行为与加幂等之前逐字一致)。

    返回参数:
        201 + ``{id, url, duration_ms, size, status}``(同步路径,``status`` 恒为 ``ready``);
        202 + ``{id, status: "pending", retry_after}``(槽被占用,转码已入队,不带 ``url``);
        400 参数不合法;503 服务器缺 ffmpeg(``code=50302``);
        409 + ``40901``(同一个 ``Idempotency-Key`` 的上一次还没处理完)。
        同 key 重试不会新建第二条:已完成的重放 201 / 202,``pending`` 期间重放的 202
        带的是**同一个 id**。

    使用示例:
        ``self.client.post(self.url, {"file": SimpleUploadedFile("a.m4a", content, content_type="audio/mp4"), "duration_ms": duration_ms}, format="multipart")``
        (见 ``im/tests.py`` 的 ``ChatVoiceUploadTests.upload``,其中 ``self.url = "/api/v1/im/voices"``)

    备注信息:
        配额检查在落盘之前完成,超限时抛 ``config.storage.StorageQuotaExceeded``(413/``41301``)。
        缺 ffmpeg/ffprobe 时按 ``voice.VoiceUnavailable`` 回 503,不静默降级;
        时长与格式不合法按 ``voice.VoiceError`` 回 400。
        转码前先抢 ``config.transcode_gate`` 的全局槽(与资料语音共用一个槽):抢不到时
        **不再回 503**,而是改走异步并回 202 —— 异步路径里配额只能在 worker 落盘前检查,
        超限时该行转 ``failed`` + ``transcode_error=41301``(异步没法同步回 413)。
        槽在 ``with`` 退出时释放,异常路径同样释放。
        幂等映射只存 id 与状态(Redis,24 小时),异步路径记 ``pending``:``pending`` 期间
        同 key 重试拿回同一个 id 继续轮询,而不是又落一份临时文件。
    """
    with idempotency.guard(request, idempotency.CHAT_VOICE) as session:
        if session.saved is not None:
            replayed = _replay_voice(request.user, session.saved)
            if replayed is not None:
                return replayed
            session.discard()

        serializer = ChatVoiceUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        declared_ms = serializer.validated_data["duration_ms"]

        # 抢槽在真正转码之前:抢不到就改走异步,把请求线程让给别的接口(M-3)。
        with transcode_gate.slot() as acquired:
            if not acquired:
                logger.warning("chat_voice_transcode_busy", extra={"user_id": request.user.id})
                return _queue_chat_voice(request.user, upload, declared_ms, session)
            try:
                data, duration_ms = voice.normalize(upload.read(), upload.content_type,
                                                    declared_ms)
            except voice.VoiceUnavailable:
                logger.error("聊天语音上传失败:服务器缺少 ffmpeg/ffprobe")
                return Response({"code": error_codes.CHAT_VOICE_UNAVAILABLE,
                                 "message": "语音消息暂不可用"}, status=503)
            except voice.VoiceError as error:
                return Response({"code": 400, "message": str(error)}, status=400)

        stem = f"{request.user.id}-{uuid.uuid4().hex}"
        storage.ensure_quota(request.user, len(data))   # 配额检查在落盘前(M7)
        chat_voice = ChatVoice(owner=request.user, duration_ms=duration_ms, bytes=len(data),
                               transcode_status=TranscodeStatus.READY)
        chat_voice.file.save(f"{stem}.m4a", ContentFile(data), save=False)
        chat_voice.save()

        session.remember(chat_voice.id, idempotency.READY)
        return Response(_voice_payload(chat_voice), status=201)


@extend_schema(responses={200: VoiceStatusSerializer})
@api_view(["GET"])
@throttle_classes([VoiceStatusThrottle])
def voice_status(request, voice_id):
    """查询一条聊天语音的转码状态(GET /api/v1/im/voices/{voice_id})。

    只给创建者本人用:异步上传拿到 202 后,客户端按 ``retry_after`` 轮询本接口,
    等 ``status`` 变成 ``ready`` 再拿 ``url`` 去发消息。

    参数说明:
        request: DRF 请求对象。
        voice_id: 聊天语音主键。

    返回参数:
        200 + ``{id, status, url, duration_ms, size, code, message}``;``pending`` 时
        ``url`` / ``duration_ms`` / ``size`` 为 ``null``,``failed`` 时失败原因落在
        ``code``(业务码)或 ``message``(短文案)上。别人的语音或不存在都是 404。

    使用示例:
        ``self.client.get(f"/api/v1/im/voices/{voice.id}")``(见 ``im/tests.py`` 的
        ``ChatVoiceStatusTests``)

    备注信息:
        查询集限定在 ``request.user`` 的语音上,他人 id 一律 404 —— 与「不确认资源是否存在」
        的既有口径一致。URL 与上传接口同一套签名口径(``media_sign``)。
    """
    chat_voice = get_object_or_404(ChatVoice.objects.filter(owner=request.user), id=voice_id)
    url = None
    if chat_voice.transcode_status == TranscodeStatus.READY and chat_voice.file:
        base = settings.MEDIA_BASE_URL.rstrip("/")
        url = media_sign.sign_url(f"{base}{chat_voice.file.url}")
    return Response(VoiceStatusSerializer(
        transcode_queue.status_payload(chat_voice, url)).data)


@extend_schema(parameters=[OpenApiParameter(
    "X-Original-URI", str, OpenApiParameter.HEADER, required=True,
    description="原始 URI(含签名与过期时间),由 nginx 的 auth_request 注入")],
    responses={204: None, 403: None})
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def image_auth(request):
    """nginx ``auth_request`` 子请求:校验媒体签名(GET /api/v1/im/images/auth)。

    这条路径**不校验登录态**:nginx 的内部子请求不会带 Authorization,而媒体本身
    已经是「谁拿到链接谁能看」的语义,靠签名与有效期兜底。

    参数说明:
        request: DRF 请求对象,nginx 通过 ``X-Original-URI`` 传入原始 URI
            (含 ``?e=&s=``)。

    返回参数:
        通过返回 204;缺头、路径不在可签名白名单(``/media/chat/`` 与 ``/media/voices/``)
        下、过期或签名不符返回 403。

    使用示例:
        ``self.client.get(self.url, HTTP_X_ORIGINAL_URI=original)``(见 ``im/tests.py`` 的 ``ChatImageAuthTests.auth``)

    备注信息:
        不校验登录态:nginx 的内部子请求不带 Authorization,靠签名与有效期兜底。
        路径前缀在这里显式校验一次(判据是 ``media_sign.is_signable_path``,
        ``media_sign.verify`` 内部还会再查),因此以后改签名逻辑也不会把资料图、
        广场图放进来。
        白名单自 2026-11-16 起含 ``/media/voices/``(资料语音自我介绍,第五轮审计 L-7):
        Django 这一侧只负责「发签名 + 放行验签」,**不负责强制** —— 要等
        ``deploy/nginx`` 给 ``/media/voices/`` 也加上 ``auth_request`` 之后,「无签名即 403」
        才真正成立(nginx 属 ``deploy/**``,不在后端栈的范围)。
    """
    original = request.headers.get("X-Original-URI", "")
    parts = urlsplit(original)
    query = parse_qs(parts.query)
    expires = (query.get("e") or [""])[0]
    signature_value = (query.get("s") or [""])[0]
    # L-6:显式校验路径前缀,与 docstring 一致。``media_sign.verify`` 内部也查一次,
    # 但那是「签名覆盖路径」的兜底;这里先挡掉不在白名单里的请求,避免以后改签名逻辑时
    # 把资料图/广场图也放进来。白名单与签名侧共用 ``is_signable_path``,不留两套判定。
    if not media_sign.is_signable_path(parts.path):
        return Response({"code": 403, "message": "图片链接已失效"}, status=403)
    if not original or not media_sign.verify(parts.path, expires, signature_value):
        return Response({"code": 403, "message": "图片链接已失效"}, status=403)
    return Response(status=204)

