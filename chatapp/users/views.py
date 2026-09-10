from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Preference, Profile, Tag
from .serializers import ProfileSerializer, ProfileUpdateSerializer, TagSerializer


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
