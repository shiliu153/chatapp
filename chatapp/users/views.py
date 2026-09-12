from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from moderation.services import blocked_user_ids

from .models import Photo, PhotoStatus, Profile, ProfileStatus, Tag
from .serializers import (PhotoSerializer, PhotoUploadSerializer, PreferenceSerializer,
                          ProfileSerializer, ProfileUpdateSerializer, PublicProfileSerializer,
                          TagSerializer)
from .services import get_profile, sync_im_nickname

User = get_user_model()


@api_view(["GET", "PATCH"])
def me(request):
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
    return Response(TagSerializer(Tag.objects.all(), many=True).data)


@api_view(["GET"])
def public_profile(request, user_id):
    # 双向拉黑 = 互相不存在;heavy 封禁的人对外不可见(轻封禁仍可见,还能聊天)
    if user_id in blocked_user_ids(request.user):
        raise NotFound("用户不存在")
    target = get_object_or_404(User, id=user_id)
    profile = getattr(target, "profile", None)
    if profile is None or profile.status == ProfileStatus.BANNED_HEAVY:
        raise NotFound("用户不存在")
    return Response(PublicProfileSerializer(profile, context={"request": request}).data)


@api_view(["POST"])
def upload_photo(request):
    serializer = PhotoUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    count = request.user.photos.count()
    if count >= settings.PHOTO_MAX_COUNT:
        return Response({"code": 400, "message": f"最多上传 {settings.PHOTO_MAX_COUNT} 张照片"}, status=400)
    status = PhotoStatus.APPROVED if settings.AUTO_APPROVE else PhotoStatus.PENDING
    photo = Photo.objects.create(user=request.user, file=serializer.validated_data["file"],
                                 order=count, status=status)
    get_profile(request.user).refresh_status()
    return Response(PhotoSerializer(photo, context={"request": request}).data, status=201)


@api_view(["DELETE"])
def delete_photo(request, photo_id):
    photo = get_object_or_404(request.user.photos, id=photo_id)
    photo.file.delete(save=False)   # 连磁盘文件一起删
    photo.delete()
    get_profile(request.user).refresh_status()
    return Response(status=204)


@api_view(["GET", "PATCH"])
def my_preference(request):
    profile = get_profile(request.user)
    preference = profile.preference
    if request.method == "PATCH":
        serializer = PreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(PreferenceSerializer(preference).data)
