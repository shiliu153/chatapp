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

文件信息:
    文件名称          users/views.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import logging
import tempfile
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config import error_codes, images, storage
from discovery.cache_keys import invalidate_candidates, invalidate_pool_globally
from feed.services import follow_state_for_profiles
from im import voice
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

    DELETE 是账号注销,由序列化器校验手机号二次确认后硬删除全部数据;
    PATCH 在昵称变化时顺带把新昵称同步到 IM 资料。

    参数说明:
        request: DRF 请求对象。``DELETE`` 时 body 需带 ``phone``。

    返回参数:
        GET/PATCH 返回完整资料;DELETE 返回 204 空响应。

    使用示例:
        ``PATCH /api/v1/users/me {"nickname": "小林"}``

    备注信息:
        PATCH 只处理提交上来的字段,结束后必然重算完善状态并让候选池缓存失效;
        重封禁用户的 ``DELETE`` 由全局权限类拦成 403(白名单只放行 GET),
        防「注销洗白」。
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
        ``GET /api/v1/users/tags``

    备注信息:
        结果不分页、不缓存:标签池只有 12 行,直接全表取。
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
        ``GET /api/v1/users/42``

    备注信息:
        双向拉黑、资料不存在、重封禁三种情况统一抛 ``NotFound``(按「用户不存在」
        处理,不泄漏账号是否存在);访问会被 ``record_profile_view`` 计数,用于抓取广度监控。
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

    上传后按 ``settings.AUTO_APPROVE`` 决定是否直接过审(开发期上传即过审);
    过审时会顺带把头像同步到 IM。

    参数说明:
        request: DRF 请求对象,multipart 字段为 ``file``。

    返回参数:
        201 + 照片对象;超出张数上限时返回 400。

    使用示例:
        ``POST /api/v1/users/me/photos (multipart: file=@a.jpg)``

    备注信息:
        图片缺失或超过大小上限抛 ``serializers.ValidationError``;
        账号媒体存储配额已满时抛 ``config.storage.StorageQuotaExceeded``(413/``41301``),
        配额检查在落盘之前;落库后必定让全站候选池失效。
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

    只允许删除本人照片(查询集限定在 ``request.user.photos`` 上);
    删除后重算资料完善状态,照片不足会掉回「未完善」并失去候选资格。

    参数说明:
        request: DRF 请求对象。
        photo_id: 照片主键。

    返回参数:
        204 空响应。

    使用示例:
        ``DELETE /api/v1/users/me/photos/7``

    备注信息:
        别人的照片查不到 → 404(查询集已限定在本人名下,不泄漏照片归属);
        磁盘文件与数据库行一起删,删除后全站候选池失效。
    """
    photo = get_object_or_404(request.user.photos, id=photo_id)
    photo.file.delete(save=False)   # 连磁盘文件一起删
    photo.delete()
    get_profile(request.user).refresh_status()
    invalidate_pool_globally()
    invalidate_candidates(request.user.id)
    return Response(status=204)


def normalize_profile_voice(raw: bytes, content_type: str) -> tuple[bytes, int]:
    """校验并转码一段资料语音自我介绍(≤30 秒)。

    转码本身**完全复用** ``im.voice.normalize``(ffprobe 校验 → ffmpeg 转 m4a/AAC,
    含协议白名单、资源上限与最小环境),这里不重写任何 ffmpeg 调用。与聊天语音的差别只有两点:

    1. 资料语音的契约只有一个 ``file`` 字段,**没有客户端声明的时长**;
       ``im.voice.normalize`` 却要求 ``declared_ms`` 并与实测值比对。所以先用
       ``ffprobe`` 探一次真实时长,再把它作为 ``declared_ms`` 传进去 —— 等价于
       「不信任客户端声明」的原始意图,同时不用改 ``im/`` 一行代码;
    2. 上限是 **30 秒**(聊天语音是 60 秒),超限抛 :class:`im.voice.VoiceError`,
       由视图回 400(不新增业务码)。

    参数说明:
        raw: 上传文件的原始字节。
        content_type: 上传声明的 MIME(可带 ``;codecs=...`` 参数)。

    返回参数:
        ``(m4a 字节, 实测毫秒)``。

    使用示例:
        ``data, duration_ms = normalize_profile_voice(upload.read(), upload.content_type)``

    备注信息:
        服务器缺 ffmpeg/ffprobe 时抛 ``voice.VoiceUnavailable``(视图回 503 + ``50302``);
        格式/大小/解码不合法或时长超过 30 秒时抛 ``voice.VoiceError``(视图回 400)。
        探测用的临时目录用完即删,不碰媒体目录。
    """
    suffix = voice.ALLOWED_CONTENT_TYPES.get(voice.base_content_type(content_type))
    if suffix is None:
        raise voice.VoiceError("只支持 M4A/AAC/WebM/OGG 音频")
    if not voice.ffmpeg_available():
        raise voice.VoiceUnavailable()
    with tempfile.TemporaryDirectory() as workdir:
        probe_path = Path(workdir) / f"probe{suffix}"
        probe_path.write_bytes(raw)
        declared_ms = voice._probe_ms(probe_path)
    data, duration_ms = voice.normalize(raw, content_type, declared_ms)
    if duration_ms > settings.PROFILE_VOICE_MAX_MS:
        raise voice.VoiceError(
            f"语音自我介绍不能超过 {settings.PROFILE_VOICE_MAX_MS // 1000} 秒")
    return data, duration_ms


@extend_schema(methods=["POST"], request=ProfileVoiceUploadSerializer,
               responses={201: ProfileVoiceSerializer})
@extend_schema(methods=["DELETE"], request=None, responses={204: None})
@api_view(["POST", "DELETE"])
@throttle_classes([ProfileVoiceThrottle])
def my_voice(request):
    """资料语音自我介绍:上传/覆盖与删除(POST/DELETE /api/v1/users/me/voice)。

    POST 是**覆盖式**的:一个账号只有一条语音,重复上传替换内容并删掉旧文件。
    处理顺序刻意写成「转码 → 时长 → 配额 → 落盘」:

    1. 转码与时长校验都在临时目录里完成,不碰媒体目录;
    2. **配额检查必须在 ``file.save()`` 之前** —— ``FileField.save`` 会立即把文件写进
       存储,先写后查会在超限时留下没有数据库行的孤儿文件,配额对磁盘占用就失效了;
    3. 落盘成功后才删旧文件与旧行,中途失败时旧语音仍然可播放。

    参数说明:
        request: DRF 请求对象。``POST`` 的 multipart 字段为 ``file``。

    返回参数:
        POST 201 + ``{url, duration_ms}``(``url`` 为公开绝对地址,与照片同口径);
        DELETE 幂等 204(没有语音时也返回 204)。

    使用示例:
        ``POST /api/v1/users/me/voice (multipart: file=@intro.m4a)``

    备注信息:
        缺文件、超过 5MB 或格式不在白名单时抛 ``serializers.ValidationError``(400);
        账号媒体存储配额已满时抛 ``config.storage.StorageQuotaExceeded``(413/``41301``);
        服务器缺 ffmpeg/ffprobe 时为 503 + ``error_codes.CHAT_VOICE_UNAVAILABLE``。
        语音不参与「资料完善」判定,所以本接口不调 ``refresh_status()``。
    """
    profile = get_profile(request.user)
    if request.method == "DELETE":
        existing = getattr(profile, "voice", None)
        if existing is not None:
            existing.file.delete(save=False)   # 连磁盘文件一起删
            existing.delete()
        return Response(status=204)

    serializer = ProfileVoiceUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    upload = serializer.validated_data["file"]
    try:
        data, duration_ms = normalize_profile_voice(upload.read(), upload.content_type)
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
    """批量查在线状态;被拉黑/不存在/自己/重封禁的人从结果里省略(GET /api/v1/presence)。

    参数说明:
        request: DRF 请求对象,``user_ids`` 为逗号分隔的账号 id,单次上限 100。

    返回参数:
        ``{"results": [{"user_id", "online", "last_active_at"}]}``。

    使用示例:
        ``GET /api/v1/presence?user_ids=8,21``

    备注信息:
        结果只包含既存在又可见的人(自己、双向拉黑、重封禁、已删号都不出现);
        ``user_ids`` 为空或非数字时回 400,去重保序后超过 100 个也回 400。
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
        ``PATCH /api/v1/users/me/preference {"age_max": 35}``

    备注信息:
        偏好只影响自己的候选池,所以 ``PATCH`` 后只失效本人的候选缓存(不动全站池);
        偏好由 ``services.get_profile`` 懒创建,读取时不会 404。
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
