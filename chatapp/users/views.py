from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Preference, Profile, Tag
from .serializers import ProfileSerializer, TagSerializer


def _get_profile(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    Preference.objects.get_or_create(profile=profile)
    return profile


@api_view(["GET"])
def me(request):
    profile = _get_profile(request.user)
    return Response(ProfileSerializer(profile, context={"request": request}).data)


@api_view(["GET"])
def tag_list(request):
    return Response(TagSerializer(Tag.objects.all(), many=True).data)
