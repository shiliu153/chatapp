from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from .models import Photo, PhotoStatus, Preference, Profile, Tag
from .serializers import (PhotoSerializer, PhotoUploadSerializer, ProfileSerializer,
                          ProfileUpdateSerializer, TagSerializer)


def _get_profile(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    Preference.objects.get_or_create(profile=profile)
    return profile


@api_view(["GET", "PATCH"])
def me(request):
    profile = _get_profile(request.user)
    if request.method == "PATCH":
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tag_ids = data.pop("tag_ids", None)
        for field, value in data.items():
            setattr(profile, field, value)
        profile.save()
        if tag_ids is not None:
            profile.tags.set(Tag.objects.filter(id__in=tag_ids))
        profile.refresh_status()
    return Response(ProfileSerializer(profile, context={"request": request}).data)


@api_view(["GET"])
def tag_list(request):
    return Response(TagSerializer(Tag.objects.all(), many=True).data)


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
    _get_profile(request.user).refresh_status()
    return Response(PhotoSerializer(photo, context={"request": request}).data, status=201)


@api_view(["DELETE"])
def delete_photo(request, photo_id):
    photo = get_object_or_404(request.user.photos, id=photo_id)
    photo.file.delete(save=False)   # 连磁盘文件一起删
    photo.delete()
    _get_profile(request.user).refresh_status()
    return Response(status=204)
