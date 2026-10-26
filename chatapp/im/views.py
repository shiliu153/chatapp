"""IM 接口:签发 userSig 与上传聊天图片。

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
import uuid

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from . import media_sign
from .backend import use_self_im
from .client import ensure_account, kick_user
from .models import ChatImage
from .serializers import ChatImageUploadSerializer
from .signature import gen_user_sig
from .tasks import kick_pending_key
from .throttles import ChatImageThrottle
from .token import mint_im_token

IMPORTED_FLAG_TTL = 30 * 24 * 3600   # 30 天;Redis 清空后下次调用会幂等重建

# 上传时的 MIME → 落盘后缀;EXIF 方向不为 1 时统一重编码成 JPEG
SUFFIX_BY_CONTENT_TYPE = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@api_view(["POST"])
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
        return Response({
            "backend": "self",
            "token": mint_im_token(user.id, settings.IM_SELF_TOKEN_TTL),
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
    """
    serializer = ChatImageUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    upload = serializer.validated_data["file"]
    raw = upload.read()
    try:
        image = Image.open(io.BytesIO(raw))
        orientation = image.getexif().get(0x0112, 1)
        display = ImageOps.exif_transpose(image)
        width, height = display.size
    except Exception:
        return Response({"code": 400, "message": "请上传图片文件"}, status=400)

    if max(width, height) > settings.CHAT_IMAGE_MAX_SIDE:
        return Response({"code": 400, "message": "图片尺寸过大,请先压缩"}, status=400)

    stem = f"{request.user.id}-{uuid.uuid4().hex}"
    month = timezone.localtime().strftime("%Y/%m")
    if orientation == 1:
        data, suffix = raw, SUFFIX_BY_CONTENT_TYPE[upload.content_type]
    else:
        buffer = io.BytesIO()
        display.convert("RGB").save(buffer, "JPEG", quality=85)
        data, suffix = buffer.getvalue(), ".jpg"

    chat_image = ChatImage(owner=request.user, width=width, height=height, bytes=len(data))
    chat_image.file.save(f"chat/{month}/{stem}{suffix}", ContentFile(data), save=False)

    thumb = display.copy()
    thumb.thumbnail((settings.CHAT_IMAGE_THUMB_SIDE, settings.CHAT_IMAGE_THUMB_SIDE),
                    Image.Resampling.LANCZOS)
    thumb_buffer = io.BytesIO()
    thumb.convert("RGB").save(thumb_buffer, "JPEG", quality=80)
    chat_image.thumb.save(f"chat/{month}/{stem}_thumb.jpg",
                          ContentFile(thumb_buffer.getvalue()), save=False)
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
