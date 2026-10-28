"""资料、照片、标签、择偶偏好与在线状态的接口。

设计要点:
    1. **可见性规则集中在两处**:双向拉黑的人互相「不存在」(``blocked_user_ids``);
       重封禁(``banned_heavy``)的人对外不可见,轻封禁仍可见、仍能聊天;
    2. ``DELETE /users/me`` 是账号注销,要求 body 带手机号二次确认,成功后**立即硬删除**
       全部数据并释放手机号(同号可重新注册为全新账号);
    3. 照片数量变化会影响「资料完善」判定,因此上传与删除后都要 ``refresh_status()``。

关联文档:
    - 接口契约:docs/api/users.md
    - 踩坑记录:docs/pitfalls/backend.md「账号注销」
"""

import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config import images, storage
from moderation.services import blocked_user_ids

from .models import Photo, PhotoStatus, Profile, ProfileStatus, Tag
from .presence import PRESENCE_MAX_IDS, get_presence
from .serializers import (DeleteAccountSerializer, PhotoSerializer, PhotoUploadSerializer,
                          PreferenceSerializer, ProfileSerializer, ProfileUpdateSerializer,
                          PublicProfileSerializer, TagSerializer)
from .services import (delete_account, get_profile, record_profile_view, sync_im_avatar,
                       sync_im_nickname)
from .throttles import PhotoUploadThrottle, PresenceThrottle, PublicProfileThrottle

User = get_user_model()


@api_view(["GET", "PATCH", "DELETE"])
def me(request):
    """我的资料:读取、局部更新与账号注销(GET/PATCH/DELETE /api/v1/users/me)。

    DELETE 是账号注销,由序列化器校验手机号二次确认后硬删除全部数据;
    PATCH 在昵称变化时顺带把新昵称同步到 IM 资料。

    Args:
        request: DRF 请求对象。``DELETE`` 时 body 需带 ``phone``。

    Returns:
        GET/PATCH 返回完整资料;DELETE 返回 204 空响应。
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
    return Response(ProfileSerializer(profile, context={"request": request}).data)


@api_view(["GET"])
def tag_list(request):
    """标签池全量列表(GET /api/v1/users/tags)。

    Args:
        request: DRF 请求对象。

    Returns:
        全部标签(12 个,由数据迁移写入);重封禁用户由全局权限类放行本接口。
    """
    return Response(TagSerializer(Tag.objects.all(), many=True).data)


@api_view(["GET"])
@throttle_classes([PublicProfileThrottle])
def public_profile(request, user_id):
    """他人资料卡(GET /api/v1/users/{user_id})。

    Args:
        request: DRF 请求对象。
        user_id: 目标账号 id。

    Returns:
        公开资料(不含手机号、生日、偏好与缺失项)。

    Raises:
        NotFound: 对方与当前用户互相拉黑、资料不存在,或对方处于重封禁状态 ——
            三种情况统一按「用户不存在」处理,不泄漏账号是否存在。
    """
    # 双向拉黑 = 互相不存在;heavy 封禁的人对外不可见(轻封禁仍可见,还能聊天)
    if user_id in blocked_user_ids(request.user):
        raise NotFound("用户不存在")
    target = get_object_or_404(User, id=user_id)
    profile = getattr(target, "profile", None)
    if profile is None or profile.status == ProfileStatus.BANNED_HEAVY:
        raise NotFound("用户不存在")
    record_profile_view(request.user.id, target.id)   # 抓取广度监控,失败不影响响应
    return Response(PublicProfileSerializer(profile, context={"request": request}).data)


@api_view(["POST"])
@throttle_classes([PhotoUploadThrottle])
def upload_photo(request):
    """上传照片(POST /api/v1/users/me/photos)。

    上传后按 ``settings.AUTO_APPROVE`` 决定是否直接过审(开发期上传即过审);
    过审时会顺带把头像同步到 IM。

    Args:
        request: DRF 请求对象,multipart 字段为 ``file``。

    Returns:
        201 + 照片对象;超出张数上限时返回 400。

    Raises:
        serializers.ValidationError: 图片缺失或超过大小上限。
        config.storage.StorageQuotaExceeded: 账号媒体存储配额已满(413/``41301``)。
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
    return Response(PhotoSerializer(photo, context={"request": request}).data, status=201)


@api_view(["DELETE"])
def delete_photo(request, photo_id):
    """删除自己的照片(DELETE /api/v1/users/me/photos/{photo_id})。

    只允许删除本人照片(查询集限定在 ``request.user.photos`` 上);
    删除后重算资料完善状态,照片不足会掉回「未完善」并失去候选资格。

    Args:
        request: DRF 请求对象。
        photo_id: 照片主键。

    Returns:
        204 空响应。
    """
    photo = get_object_or_404(request.user.photos, id=photo_id)
    photo.file.delete(save=False)   # 连磁盘文件一起删
    photo.delete()
    get_profile(request.user).refresh_status()
    return Response(status=204)


@api_view(["GET"])
@throttle_classes([PresenceThrottle])
def presence_status(request):
    """批量查在线状态;被拉黑/不存在/自己/重封禁的人从结果里省略。

    Args:
        request: DRF 请求对象,``user_ids`` 为逗号分隔的账号 id,单次上限 100。

    Returns:
        ``{"results": [{"user_id", "online", "last_active_at"}]}``。
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


@api_view(["GET", "PATCH"])
def my_preference(request):
    """我的择偶偏好:读取与局部更新(GET/PATCH /api/v1/users/me/preference)。

    Args:
        request: DRF 请求对象;``PATCH`` 支持部分字段。

    Returns:
        更新后的完整偏好对象。
    """
    profile = get_profile(request.user)
    preference = profile.preference
    if request.method == "PATCH":
        serializer = PreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(PreferenceSerializer(preference).data)
