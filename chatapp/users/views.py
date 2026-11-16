"""资料、照片、标签、择偶偏好与在线状态的接口。

设计要点:
    1. **可见性规则集中在两处**:双向拉黑的人互相「不存在」(``blocked_user_ids``);
       重封禁(``banned_heavy``)的人对外不可见,轻封禁仍可见、仍能聊天;
    2. ``DELETE /users/me`` 是账号注销,要求 body 带手机号二次确认,成功后**立即硬删除**
       全部数据并释放手机号(同号可重新注册为全新账号);
    3. 照片数量变化会影响「资料完善」判定,因此上传与删除后都要 ``refresh_status()``;
       资料语音(批次 R)刻意**不**参与该判定,所以语音上传/删除都不调 ``refresh_status()``。

关联文档:
    - 接口契约:docs/api/users.md
    - 踩坑记录:docs/pitfalls/backend.md「账号注销」
"""

import logging
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config import error_codes, images, storage, transcode_gate
from discovery.cache_keys import invalidate_candidates, invalidate_pool_globally
from feed.services import follow_state_for_profiles
from im import media_sign, transcode_queue, voice
from im.models import TranscodeStatus
from im.serializers import VOICE_QUEUED_RESPONSE, VoiceStatusSerializer
from im.tasks import transcode_profile_voice
from im.throttles import VoiceStatusThrottle
from moderation.services import blocked_user_ids

from .models import Photo, PhotoStatus, Profile, ProfileStatus, ProfileVoice, Tag
from .presence import PRESENCE_MAX_IDS, get_presence
from .serializers import (DeleteAccountSerializer, PhotoSerializer, PhotoUploadSerializer,
                          PreferenceSerializer, ProfileSerializer, ProfileVoiceSerializer,
                          ProfileVoiceUploadSerializer, ProfileUpdateSerializer,
                          PublicProfileSerializer, TagSerializer)
from .services import (delete_account, get_profile, record_profile_view, sync_im_avatar,
                       sync_im_nickname)
from .throttles import (PhotoUploadThrottle, PresenceThrottle, ProfileVoiceThrottle,
                        PublicProfileThrottle)

User = get_user_model()
logger = logging.getLogger(__name__)


@extend_schema(methods=["GET"], responses={200: ProfileSerializer})
@extend_schema(methods=["PATCH"], request=ProfileUpdateSerializer,
               responses={200: ProfileSerializer})
@extend_schema(methods=["DELETE"], request=DeleteAccountSerializer, responses={204: None})
@api_view(["GET", "PATCH", "DELETE"])
def me(request):
    """我的资料:读取、局部更新与账号注销(GET/PATCH/DELETE /api/v1/users/me)。

    参数说明:
        request: DRF 请求对象。``DELETE`` 时 body 需带 ``phone``。

    返回参数:
        GET/PATCH 返回完整资料;DELETE 返回 204 空响应。

    使用示例:
        ``self.client.get("/api/v1/users/me")``(见 ``users/tests.py`` 的 ``MeTests``)
        注销:``self.client.delete("/api/v1/users/me", {"phone": "13800138000"}, format="json")``(见 ``users/tests.py`` 的 ``_delete``)

    备注信息:
        DELETE 是账号注销,由序列化器校验手机号二次确认后硬删除全部数据;
        PATCH 在昵称变化时顺带把新昵称同步到 IM 资料。
        重封禁用户由全局权限类拦成 403(白名单只放行 GET),防「注销洗白」。
    """
    if request.method == "DELETE":
        # 手机号二次确认:不可恢复操作,body 必须带上当前账号的手机号。
        # 重封禁用户由全局 IsNotHeavyBanned 拦成 403(白名单只放行 GET),防「注销洗白」。
        serializer = DeleteAccountSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        delete_account(request.user)
        return Response(status=204)
    profile = get_profile(request.user)
    if request.method == "PATCH":
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tag_ids = data.pop("tag_ids", None)
        old_nickname = profile.nickname
        for field, value in data.items():
            setattr(profile, field, value)
        profile.save()
        if tag_ids is not None:
            profile.tags.set(Tag.objects.filter(id__in=tag_ids))
        profile.refresh_status()
        if profile.nickname != old_nickname:
            sync_im_nickname(profile.user)
        # 资料字段(性别/城市/生日)参与别人的候选过滤,必须让全局候选池失效。
        invalidate_pool_globally()
        invalidate_candidates(request.user.id)
    return Response(ProfileSerializer(profile, context={"request": request}).data)


@extend_schema(responses={200: TagSerializer(many=True)})
@api_view(["GET"])
def tag_list(request):
    """标签池全量列表(GET /api/v1/users/tags)。

    参数说明:
        request: DRF 请求对象。

    返回参数:
        全部标签(12 个,由数据迁移写入);重封禁用户由全局权限类放行本接口。

    使用示例:
        ``self.client.get("/api/v1/users/tags")``(见 ``users/tests.py`` 的 ``MeTests``)

    备注信息:
        标签池不接受写接口,只能由数据迁移维护;``feed`` 与资料卡展示都取这一份。
    """
    return Response(TagSerializer(Tag.objects.all(), many=True).data)


@extend_schema(responses={200: PublicProfileSerializer})
@api_view(["GET"])
@throttle_classes([PublicProfileThrottle])
def public_profile(request, user_id):
    """他人资料卡(GET /api/v1/users/{user_id})。

    参数说明:
        request: DRF 请求对象。
        user_id: 目标账号 id。

    返回参数:
        公开资料(不含手机号、生日、偏好与缺失项),含共同标签与关注态
        (``is_followed`` / ``follower_count`` / ``following_count``)。

    使用示例:
        ``self.client.get(f"/api/v1/users/{self.other.id}")``(见 ``users/tests.py`` 的 ``PublicProfileTests._get``)

    备注信息:
        对方与当前用户互相拉黑、资料不存在,或对方处于重封禁状态时统一抛 ``NotFound``,
        按「用户不存在」处理,不泄漏账号是否存在。
        关注态一次算好注入 context,单条资料卡只多一条聚合 SQL。
    """
    # 双向拉黑 = 互相不存在;heavy 封禁的人对外不可见(轻封禁仍可见,还能聊天)
    if user_id in blocked_user_ids(request.user):
        raise NotFound("用户不存在")
    target = get_object_or_404(User, id=user_id)
    profile = getattr(target, "profile", None)
    if profile is None or profile.status == ProfileStatus.BANNED_HEAVY:
        raise NotFound("用户不存在")
    record_profile_view(request.user.id, target.id)   # 抓取广度监控,失败不影响响应
    # 关注态一次算好注入(单条资料卡只多一条聚合 SQL),序列化器不再逐字段查库
    follow_state = follow_state_for_profiles([profile], request.user)
    return Response(PublicProfileSerializer(
        profile,
        context={"request": request, "follow_state_map": follow_state}).data)


@extend_schema(request=PhotoUploadSerializer, responses={201: PhotoSerializer})
@api_view(["POST"])
@throttle_classes([PhotoUploadThrottle])
def upload_photo(request):
    """上传照片(POST /api/v1/users/me/photos)。

    参数说明:
        request: DRF 请求对象,multipart 字段为 ``file``。

    返回参数:
        201 + 照片对象;超出张数上限时返回 400。

    使用示例:
        ``self.client.post("/api/v1/users/me/photos", {"file": SimpleUploadedFile(...)}, format="multipart")``(见 ``users/tests.py`` 的 ``PhotoTests.upload``)

    备注信息:
        上传后按 ``settings.AUTO_APPROVE`` 决定是否直接过审(开发期上传即过审);
        过审时会顺带把头像同步到 IM。图片缺失或超过大小上限抛
        ``serializers.ValidationError``;配额已满抛 ``config.storage.StorageQuotaExceeded``
        (413/``41301``)。
    """
    serializer = PhotoUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    count = request.user.photos.count()
    if count >= settings.PHOTO_MAX_COUNT:
        return Response({"code": 400, "message": f"最多上传 {settings.PHOTO_MAX_COUNT} 张照片"}, status=400)
    try:
        normalized = images.normalize(images.open_checked(
            serializer.validated_data["file"].read()))
    except images.ImageError as error:
        return Response({"code": 400, "message": str(error)}, status=400)
    status = PhotoStatus.APPROVED if settings.AUTO_APPROVE else PhotoStatus.PENDING
    filename = f"{request.user.id}-{uuid.uuid4().hex}{normalized.extension}"
    storage.ensure_quota(request.user, len(normalized.data))
    photo = Photo.objects.create(user=request.user,
                                 file=ContentFile(normalized.data, name=filename),
                                 bytes=len(normalized.data),
                                 order=count, status=status)
    get_profile(request.user).refresh_status()
    if status == PhotoStatus.APPROVED:
        sync_im_avatar(request.user.id)
    # 照片决定「谁有资格进候选池」,上传/过审后全站候选池都要重算。
    invalidate_pool_globally()
    invalidate_candidates(request.user.id)
    return Response(PhotoSerializer(photo, context={"request": request}).data, status=201)


@extend_schema(responses={204: None})
@api_view(["DELETE"])
def delete_photo(request, photo_id):
    """删除自己的照片(DELETE /api/v1/users/me/photos/{photo_id})。

    参数说明:
        request: DRF 请求对象。
        photo_id: 照片主键。

    返回参数:
        204 空响应。

    使用示例:
        ``self.client.delete(f"/api/v1/users/me/photos/{photo.id}")``(见 ``users/tests.py`` 的 ``PhotoTests``)

    备注信息:
        只允许删除本人照片(查询集限定在 ``request.user.photos`` 上);
        删除后重算资料完善状态,照片不足会掉回「未完善」并失去候选资格。
        非本人或不存在时 ``get_object_or_404`` 抛 404。
    """
    photo = get_object_or_404(request.user.photos, id=photo_id)
    photo.file.delete(save=False)   # 连磁盘文件一起删
    photo.delete()
    get_profile(request.user).refresh_status()
    invalidate_pool_globally()
    invalidate_candidates(request.user.id)
    return Response(status=204)


def _queue_profile_voice(user, profile, upload) -> Response:
    """把一次资料语音上传改走异步:落临时区 + 标 pending + 入队,回 202。

    参数说明:
        user: 当前登录账号。
        profile: 当前账号的资料(语音是一对一,没有就现建一行 ``pending``)。
        upload: 已通过浅校验的上传文件。

    返回参数:
        202 + ``{id, status, retry_after}``;服务器缺 ``ffmpeg`` / ``ffprobe`` 时回
        503 + ``50302``。

    使用示例:
        ``return _queue_profile_voice(request.user, profile, upload)``(见本模块 ``my_voice``)

    备注信息:
        **覆盖式**在异步路径上的表现:受理的同时就把旧语音下线(删旧文件、``bytes`` 归零),
        旧行因此不会既占配额又停在 ``pending`` 上;转码失败时该行是 ``failed`` 且没有文件,
        用户重录即可(失败重试 UI 另单处理)。
        行先提交、任务后入队(``transaction.on_commit``),worker 才查得到它。
    """
    if not voice.ffmpeg_available():
        logger.error("资料语音上传失败:服务器缺少 ffmpeg/ffprobe")
        return Response({"code": error_codes.CHAT_VOICE_UNAVAILABLE,
                         "message": "语音自我介绍暂不可用"}, status=503)
    staged = transcode_queue.stage(upload.read(),
                                   transcode_queue.staged_name(upload.content_type))
    record = getattr(profile, "voice", None) or ProfileVoice(profile=profile)
    old_name = record.file.name or ""
    record.file = staged
    record.bytes = 0
    record.duration_ms = 0
    record.transcode_status = TranscodeStatus.PENDING
    record.transcode_error = ""
    record.save()
    if old_name and not transcode_queue.is_staged(old_name):
        record.file.storage.delete(old_name)
    voice_id = record.pk
    transaction.on_commit(lambda: transcode_profile_voice.delay(voice_id), robust=True)
    logger.info("profile_voice_queued", extra={"user_id": user.id, "voice_id": voice_id})
    return Response({"id": voice_id, "status": TranscodeStatus.PENDING,
                     "retry_after": transcode_gate.retry_after()}, status=202)


@extend_schema(methods=["GET"], responses={200: VoiceStatusSerializer})
@extend_schema(methods=["POST"], request=ProfileVoiceUploadSerializer,
               responses={201: ProfileVoiceSerializer, 202: VOICE_QUEUED_RESPONSE})
@extend_schema(methods=["DELETE"], request=None, responses={204: None})
@api_view(["GET", "POST", "DELETE"])
@throttle_classes([ProfileVoiceThrottle, VoiceStatusThrottle])
def my_voice(request):
    """资料语音自我介绍:读取转码状态、上传/覆盖与删除(GET/POST/DELETE /api/v1/users/me/voice)。

    参数说明:
        request: DRF 请求对象。``POST`` 的 multipart 字段为 ``file``。

    返回参数:
        GET 200 + ``{id, status, url, duration_ms, size, code, message}``(``pending`` 时
        ``url`` / ``duration_ms`` / ``size`` 为 ``null``;``failed`` 时原因落在
        ``code`` / ``message``);没有语音时 404。
        POST 201 + ``{url, duration_ms, status}``(``url`` 为**限时签名**的绝对地址,带
        ``e``/``s``,TTL 与聊天媒体同源 ``IM_MEDIA_SIGN_TTL``,过期失效);
        POST 抢不到转码槽时 202 + ``{id, status: "pending", retry_after}``。
        DELETE 幂等 204(没有语音时也返回 204)。

    使用示例:
        ``self.client.post("/api/v1/users/me/voice", {"file": SimpleUploadedFile(...)}, format="multipart")``(见 ``users/tests.py`` 的 ``VoiceTests.upload``)

    备注信息:
        POST 是**覆盖式**的:一个账号只有一条语音,重复上传替换内容并删掉旧文件。
        处理顺序刻意写成「转码 → 时长 → 配额 → 落盘」:**配额检查必须在 ``file.save()`` 之前**,
        否则超限时会留下没有数据库行的孤儿文件。
        缺文件、超过 5MB 或格式不在白名单抛 ``serializers.ValidationError``(400);
        配额已满抛 ``config.storage.StorageQuotaExceeded``(413/``41301``)。
        转码前先抢 ``config.transcode_gate`` 的全局槽(与聊天语音共用一个槽):抢不到时
        **不再回 503**,改走异步并回 202 —— 资料语音要跑两次 ``ffprobe`` 加一次 ``ffmpeg``,
        占满 2 个 worker 期间连登录都会排队(第五轮审计 M-3)。异步路径的配额同样在
        worker 落盘前检查,超限时该行转 ``failed`` + ``transcode_error=41301``。
        GET 与 POST/DELETE 的限流分开:轮询走 ``voice_status``,不占 10 次/小时的改资料额度。
    """
    profile = get_profile(request.user)
    if request.method == "GET":
        record = getattr(profile, "voice", None)
        if record is None:
            raise NotFound("还没有语音自我介绍")
        url = None
        if record.transcode_status == TranscodeStatus.READY and record.file:
            # 与 ProfileVoiceSerializer.get_url / 聊天语音轮询接口同一套签名口径
            base = settings.MEDIA_BASE_URL.rstrip("/")
            url = media_sign.sign_url(f"{base}{record.file.url}")
        return Response(VoiceStatusSerializer(
            transcode_queue.status_payload(record, url)).data)

    if request.method == "DELETE":
        existing = getattr(profile, "voice", None)
        if existing is not None:
            if transcode_queue.is_staged(existing.file.name or ""):
                transcode_queue.discard(existing.file.name)
            existing.file.delete(save=False)   # 连磁盘文件一起删
            existing.delete()
        return Response(status=204)

    serializer = ProfileVoiceUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    upload = serializer.validated_data["file"]

    # 抢槽在真正转码之前:抢不到就改走异步,把请求线程让给别的接口(M-3)。
    with transcode_gate.slot() as acquired:
        if not acquired:
            logger.warning("profile_voice_transcode_busy", extra={"user_id": request.user.id})
            return _queue_profile_voice(request.user, profile, upload)
        try:
            data, duration_ms = voice.normalize_profile(upload.read(), upload.content_type)
        except voice.VoiceUnavailable:
            logger.error("资料语音上传失败:服务器缺少 ffmpeg/ffprobe")
            return Response({"code": error_codes.CHAT_VOICE_UNAVAILABLE,
                             "message": "语音自我介绍暂不可用"}, status=503)
        except voice.VoiceError as error:
            return Response({"code": 400, "message": str(error)}, status=400)

    # 配额检查在落盘之前(M7):超限时一个字节都不写进媒体目录。
    storage.ensure_quota(request.user, len(data))

    record = getattr(profile, "voice", None) or ProfileVoice(profile=profile)
    old_name = record.file.name or ""
    stem = f"{request.user.id}-{uuid.uuid4().hex}"
    record.file.save(f"{stem}.m4a", ContentFile(data), save=False)
    record.duration_ms = duration_ms
    record.bytes = len(data)
    record.transcode_status = TranscodeStatus.READY
    record.transcode_error = ""
    record.save()
    if old_name and old_name != record.file.name:
        record.file.storage.delete(old_name)
    return Response(ProfileVoiceSerializer(record, context={"request": request}).data,
                    status=201)


@extend_schema(parameters=[OpenApiParameter(
    "user_ids", str, OpenApiParameter.QUERY, required=True,
    description="逗号分隔的账号 ID,一次最多 100 个")],
    responses={200: inline_serializer("PresenceResult", fields={
        "results": serializers.ListField(child=inline_serializer("PresenceItem", fields={
            "user_id": serializers.IntegerField(),
            "online": serializers.BooleanField(),
            "last_active_at": serializers.DateTimeField(allow_null=True),
        }))})})
@api_view(["GET"])
@throttle_classes([PresenceThrottle])
def presence_status(request):
    """批量查在线状态;被拉黑/不存在/自己/重封禁的人从结果里省略。

    参数说明:
        request: DRF 请求对象,``user_ids`` 为逗号分隔的账号 id,单次上限 100。

    返回参数:
        ``{"results": [{"user_id", "online", "last_active_at"}]}``。

    使用示例:
        ``self.client.get("/api/v1/presence", {"user_ids": str(self.other.id)})``(见 ``users/tests.py`` 的 ``PresenceApiTests``)

    备注信息:
        ``user_ids`` 缺失、非数字或超过上限时返回 400;结果去重且保持请求顺序。
        在线与否读 ``users.presence`` 的 Redis 键,Redis 不可用时降级成全部离线而不是报错。
    """
    raw = request.query_params.get("user_ids", "")
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return Response({"code": 400, "message": "user_ids 不能为空"}, status=400)
    try:
        ids = [int(part) for part in parts]
    except ValueError:
        return Response({"code": 400, "message": "user_ids 必须是数字"}, status=400)
    seen: set[int] = set()
    ids = [uid for uid in ids if not (uid in seen or seen.add(uid))]   # 去重保序
    if len(ids) > PRESENCE_MAX_IDS:
        return Response({"code": 400, "message": f"一次最多查询 {PRESENCE_MAX_IDS} 个用户"}, status=400)

    hidden = blocked_user_ids(request.user)
    visible = [uid for uid in ids if uid != request.user.id and uid not in hidden]
    if visible:
        existing = set(User.objects.filter(id__in=visible).values_list("id", flat=True))
        banned = set(Profile.objects.filter(user_id__in=visible,
                                            status=ProfileStatus.BANNED_HEAVY)
                     .values_list("user_id", flat=True))
        visible = [uid for uid in visible if uid in existing and uid not in banned]
    data = get_presence(visible)
    return Response({"results": [{"user_id": uid, **data[uid]} for uid in visible]})


@extend_schema(methods=["GET"], responses={200: PreferenceSerializer})
@extend_schema(methods=["PATCH"], request=PreferenceSerializer,
               responses={200: PreferenceSerializer})
@api_view(["GET", "PATCH"])
def my_preference(request):
    """我的择偶偏好:读取与局部更新(GET/PATCH /api/v1/users/me/preference)。

    参数说明:
        request: DRF 请求对象;``PATCH`` 支持部分字段。

    返回参数:
        更新后的完整偏好对象。

    使用示例:
        ``self.client.patch("/api/v1/users/me/preference", {"age_min": 22, "age_max": 30}, format="json")``(见 ``users/tests.py`` 的 ``PreferenceTests.test_update``)

    备注信息:
        偏好只影响自己的候选池,写入后立即让本人候选缓存失效;年龄区间由序列化器校验
        (下限不小于 18、下限不得大于上限)。
    """
    profile = get_profile(request.user)
    preference = profile.preference
    if request.method == "PATCH":
        serializer = PreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # 偏好只影响自己的候选池。
        invalidate_candidates(request.user.id)
    return Response(PreferenceSerializer(preference).data)
