from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from users.models import Photo, PhotoStatus, Profile, ProfileStatus, birthday_bounds
from users.services import get_profile

from .models import Match, Swipe
from .serializers import CandidateSerializer

DEFAULT_LIMIT = 10
MAX_LIMIT = 20


@api_view(["GET"])
def candidates(request):
    me = request.user
    preference = get_profile(me).preference

    swiped_ids = Swipe.objects.filter(swiper=me).values_list("target_id", flat=True)
    my_matches = Match.objects.filter(Q(user_a=me) | Q(user_b=me))
    matched_ids = [
        other_id
        for other_id in list(my_matches.values_list("user_a_id", flat=True))
        + list(my_matches.values_list("user_b_id", flat=True))
        if other_id != me.id
    ]

    # 有过审照片的人才进候选(用子查询而不是 JOIN,避免出重复行、也避免 distinct + 随机排序的坑)
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    qs = (Profile.objects.filter(status=ProfileStatus.COMPLETE, user_id__in=with_photos)
          .exclude(user_id=me.id)
          .exclude(user_id__in=list(swiped_ids))
          .exclude(user_id__in=matched_ids))

    if preference.target_gender:
        qs = qs.filter(gender=preference.target_gender)
    if preference.city:
        qs = qs.filter(city=preference.city)
    upper, lower = birthday_bounds(preference.age_min, preference.age_max)
    qs = qs.filter(birthday__lte=upper, birthday__gt=lower)

    try:
        limit = min(int(request.query_params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
    except ValueError:
        limit = DEFAULT_LIMIT

    # order_by("?") 在数据量大时会慢,MVP 阶段(几百人)够用,将来换成预计算随机列
    qs = qs.prefetch_related("tags", "user__photos").order_by("?")[:limit]
    return Response(CandidateSerializer(qs, many=True, context={"request": request}).data)
