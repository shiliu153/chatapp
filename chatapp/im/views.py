"""IM 接口:签发 userSig、上传聊天图片与语音、nginx 验签子请求。

设计要点:
    IM 账号的供给由本模块自己保证:首次调用同步建号,成功后在 Redis 置 30 天标记,
    之后不再重复查腾讯。建号失败不置标记,下次调用自动重试。

注意事项:
    踢旧会话必须发生在**签发新签名之前**,顺序不能反 —— 反了会把本机刚建立的会话
    一起踢掉,客户端收到 KickOffline 会误报「账号已在其他设备登录」(2026-09-12 手测回归)。

    聊天图片上传是**同步落盘 + 同步生成缩略图**:这条路径没有任何第三方调用,
    符合「响应路径禁止外部调用」纪律;文件名带随机 uuid,不可枚举。

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
from PIL import Image
from rest_framework.decorators import (api_view, authentication_classes,
                                      permission_classes, throttle_classes)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from config import error_codes, images, storage

from . import media_sign, voice
from .backend import use_self_im
from .client import ensure_account, kick_user, set_session_version
from .models import ChatImage, ChatVoice
from .serializers import ChatImageUploadSerializer, ChatVoiceUploadSerializer
from .signature import gen_user_sig
from .tasks import kick_pending_key
from .throttles import ChatImageThrottle, ChatVoiceThrottle, UserSigThrottle
from .token import mint_im_token

logger = logging.getLogger(__name__)

IMPORTED_FLAG_TTL = 30 * 24 * 3600   # 30 天;Redis 清空后下次调用会幂等重建


@api_view(["POST"])
@throttle_classes([UserSigThrottle])
def user_sig(request):
    """签发当前用户的 IM userSig(POST /api/v1/im/user_sig)。

    重封禁用户由全局权限类 ``IsNotHeavyBanned`` 直接拦成 403,本函数不再重复检查。

    Args:
        request: DRF 请求对象。

    Returns:
        ``{backend, ...}``;腾讯分支含 ``user_sig/sdkappid``,自建分支含
        ``token/ws_url/http_url``。
    """
    # 重封禁由全局权限类 IsNotHeavyBanned 拦下,这里不再重复检查
    user = request.user
    # IM 账号供给归 IM 域自己保证:首次调用同步建号(ensure_account 先查后建,
    # 不会覆盖已同步的昵称/头像),失败不置标记,下次调用再试;
    # 这样鉴权路径永远不碰腾讯 REST
    imported_flag = f"im:imported:{user.id}"
    if not cache.get(imported_flag) and ensure_account(user.im_user_id):
        cache.set(imported_flag, 1, IMPORTED_FLAG_TTL)

    # 单设备:本次登录作废了旧会话(verify 时打了标记)→ 先踢旧 IM 会话再发签名。
    # 顺序不能反:踢必须发生在新会话建立之前,否则会把本机刚建的会话一起踢掉,
    # 客户端收到 KickOffline 会误报「账号已在其他设备登录」(2026-09-12 手测回归)
    kick_flag = kick_pending_key(user.id)
    if cache.get(kick_flag) and kick_user(user.im_user_id):
        cache.delete(kick_flag)

    if use_self_im(user):
        nickname = getattr(getattr(user, "profile", None), "nickname", "") or ""
        ensure_account(user.im_user_id, nickname)   # 失败不阻断签发
        # 会话版本必须先落到 imserver 再签发 token:否则新 token 带的是
        # imserver 还没见过的版本,连接会被自己拒绝;同步失败则 fail-closed(H3)。
        if not set_session_version(user.im_user_id, user.session_version):
            return Response({"code": 503, "message": "IM 暂不可用,请稍后重试"}, status=503)
        return Response({
            "backend": "self",
            "token": mint_im_token(user.id, settings.IM_SELF_TOKEN_TTL,
                                   user.session_version),
            "im_user_id": user.im_user_id,
            "ws_url": settings.IM_SELF_WS_URL,
            "http_url": settings.IM_SELF_HTTP_URL,
            "expire": settings.IM_SELF_TOKEN_TTL,
        })

    return Response({
        "backend": "tencent",
        "user_sig": gen_user_sig(user.im_user_id),
        "sdkappid": settings.IM_SDKAPPID,
        "im_user_id": user.im_user_id,
        "expire": settings.IM_SIG_EXPIRE,
    })


@api_view(["POST"])
@throttle_classes([ChatImageThrottle])
def upload_image(request):
    """上传一张聊天图片(POST /api/v1/im/images)。

    同步落盘 + 生成缩略图,不进 Celery:这条路径没有第三方调用,
    符合「响应路径禁止外部调用」纪律。文件名带随机 uuid,不可枚举。

    Args:
        request: DRF 请求对象,multipart 字段为 ``file``。

    Returns:
        201 + ``{id, url, thumb_url, width, height, size}``;URL 用
        ``settings.MEDIA_BASE_URL`` 拼绝对地址(与 IM 头像同步同一套)。

    Raises:
        config.storage.StorageQuotaExceeded: 账号媒体存储配额已满(413/``41301``)。
    """
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

    base = settings.MEDIA_BASE_URL.rstrip("/")
    return Response({
        "id": chat_image.id,
        "url": media_sign.sign_url(f"{base}{chat_image.file.url}"),
        "thumb_url": media_sign.sign_url(f"{base}{chat_image.thumb.url}"),
        "width": chat_image.width,
        "height": chat_image.height,
        "size": chat_image.bytes,
    }, status=201)


@api_view(["POST"])
@throttle_classes([ChatVoiceThrottle])
def upload_voice(request):
    """上传一段聊天语音(POST /api/v1/im/voices)。

    同步执行:写临时文件 → ffprobe 校验时长 → ffmpeg 转 m4a → 落盘。全程本地进程,
    没有第三方网络调用,符合「响应路径禁止外部调用」纪律。

    Args:
        request: DRF 请求对象,multipart 字段为 ``file`` 与 ``duration_ms``。

    Returns:
        201 + ``{id, url, duration_ms, size}``;URL 为限时签名地址。
        400 参数不合法;503 服务器缺 ffmpeg(``code=50302``)。

    Raises:
        config.storage.StorageQuotaExceeded: 账号媒体存储配额已满(413/``41301``)。
    """
    serializer = ChatVoiceUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    upload = serializer.validated_data["file"]
    try:
        data, duration_ms = voice.normalize(
            upload.read(), upload.content_type, serializer.validated_data["duration_ms"])
    except voice.VoiceUnavailable:
        logger.error("聊天语音上传失败:服务器缺少 ffmpeg/ffprobe")
        return Response({"code": error_codes.CHAT_VOICE_UNAVAILABLE,
                         "message": "语音消息暂不可用"}, status=503)
    except voice.VoiceError as error:
        return Response({"code": 400, "message": str(error)}, status=400)

    stem = f"{request.user.id}-{uuid.uuid4().hex}"
    storage.ensure_quota(request.user, len(data))   # 配额检查在落盘前(M7)
    chat_voice = ChatVoice(owner=request.user, duration_ms=duration_ms, bytes=len(data))
    chat_voice.file.save(f"{stem}.m4a", ContentFile(data), save=False)
    chat_voice.save()

    base = settings.MEDIA_BASE_URL.rstrip("/")
    return Response({
        "id": chat_voice.id,
        "url": media_sign.sign_url(f"{base}{chat_voice.file.url}"),
        "duration_ms": chat_voice.duration_ms,
        "size": chat_voice.bytes,
    }, status=201)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def image_auth(request):
    """nginx ``auth_request`` 子请求:校验聊天图片签名(GET /api/v1/im/images/auth)。

    这条路径**不校验登录态**:nginx 的内部子请求不会带 Authorization,而图片本身
    已经是「谁拿到链接谁能看」的语义,靠签名与有效期兜底。

    Args:
        request: DRF 请求对象,nginx 通过 ``X-Original-URI`` 传入原始 URI
            (含 ``?e=&s=``)。

    Returns:
        通过返回 204;缺头、路径不在 ``/media/chat/`` 下、过期或签名不符返回 403。
    """
    original = request.headers.get("X-Original-URI", "")
    parts = urlsplit(original)
    query = parse_qs(parts.query)
    expires = (query.get("e") or [""])[0]
    signature_value = (query.get("s") or [""])[0]
    if not original or not media_sign.verify(parts.path, expires, signature_value):
        return Response({"code": 403, "message": "图片链接已失效"}, status=403)
    return Response(status=204)

