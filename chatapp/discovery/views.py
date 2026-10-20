"""发现页的候选卡片、滑卡与配对列表接口。

设计要点:
    1. **候选池的排除规则**:排除自己、划过的人、已配对的人、双向拉黑的人,
       并且只收 ``status=COMPLETE``(资料完善)且**至少有一张已过审照片**的人;
    2. **滑卡幂等**:同一对 ``(我, 他)`` 只有一条记录,重复提交保留第一次的动作,
       因此重试不会把「喜欢」翻成「跳过」;
    3. **配对是互喜的结果**:只有双方都是 ``like`` 才建 ``Match``,并在事务提交后
       给双方各发一条 IM 灰条;
    4. **解除配对是软删除 + 双向拉黑**:``DELETE /matches/{user_id}`` 只打时间戳,
       读侧统一过滤 ``unmatched_at__isnull=True``;已解除的配对不会被再次滑卡复活。

关联文档:
    - 接口契约:docs/api/discovery.md
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config.pagination import DefaultLimitOffsetPagination
from im import tasks as im_tasks
from moderation.services import blocked_user_ids
from users.models import Photo, PhotoStatus, Profile, ProfileStatus, birthday_bounds
from users.services import get_profile

from .models import Match, Swipe, SwipeAction
from .serializers import CandidateSerializer, LikeReceivedSerializer, SwipeSerializer
from .services import likes_received_queryset, notify_match
from .throttles import SwipeThrottle

User = get_user_model()

DEFAULT_LIMIT = 10
MAX_LIMIT = 20


@api_view(["GET"])
def candidates(request):
    """候选卡片列表(GET /api/v1/discovery/candidates)。

    按「想找的人」偏好过滤(性别、城市、年龄区间),再套用候选池的排除规则。

    Args:
        request: DRF 请求对象,支持 ``limit`` 查询参数(默认 10,上限 20)。

    Returns:
        候选卡片数组,字段见 ``CandidateSerializer``。
    """
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

    # 只让有已过审照片的人进候选。用子查询而非 JOIN,避免产生重复行,
    # 也避免 distinct 与随机排序互相冲突。
    blocked_ids = blocked_user_ids(me)
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    qs = (Profile.objects.filter(status=ProfileStatus.COMPLETE, user_id__in=with_photos)
          .exclude(user_id=me.id)
          .exclude(user_id__in=list(swiped_ids))
          .exclude(user_id__in=matched_ids)
          .exclude(user_id__in=list(blocked_ids)))

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

    # order_by("?") 在数据量大时性能下降。当前用户规模(数百人)可接受,
    # 后续改为预计算随机列。
    qs = qs.prefetch_related("tags", "user__photos").order_by("?")[:limit]
    return Response(CandidateSerializer(qs, many=True, context={"request": request}).data)


@api_view(["POST"])
@throttle_classes([SwipeThrottle])
def swipe(request):
    """提交一次滑卡(POST /api/v1/discovery/swipe)。

    幂等:同一对用户重复提交保留第一次的动作;若本次形成互喜则创建配对,
    并在事务提交后给双方发 IM 灰条。

    Args:
        request: DRF 请求对象,body 需带 ``target_user_id`` 与 ``action``。

    Returns:
        ``{"matched": bool}``,表示本次是否配对成功。

    Raises:
        PermissionDenied: 当前账号被封禁(轻封禁也禁止滑卡)。
        ValidationError: 划自己,或对方资料不完整。
    """
    me = request.user
    serializer = SwipeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    target_id = serializer.validated_data["target_user_id"]
    action = serializer.validated_data["action"]

    if get_profile(me).is_banned:
        raise PermissionDenied("账号已被限制,暂时无法滑卡")
    if target_id == me.id:
        raise ValidationError("不能划自己")

    target = get_object_or_404(User, id=target_id)
    if not Profile.objects.filter(user=target, status=ProfileStatus.COMPLETE).exists():
        raise ValidationError("对方资料不完整,无法操作")

    # 幂等:重复提交保留第一次的动作与结果
    swipe_obj, _ = Swipe.objects.get_or_create(swiper=me, target=target, defaults={"action": action})

    matched = False
    if swipe_obj.action == SwipeAction.LIKE and Swipe.objects.filter(
            swiper=target, target=me, action=SwipeAction.LIKE).exists():
        with transaction.atomic():
            match, created = Match.objects.get_or_create(**Match.pair_kwargs(me, target))
            # 已解除的配对不复活:get_or_create 会捞到软删除的旧行
            if match.unmatched_at is not None:
                matched = False
            else:
                if created:
                    notify_match(match)
                matched = True

    return Response({"matched": matched})


@api_view(["GET"])
def match_list(request):
    """我的配对列表(GET /api/v1/matches)。

    与我有拉黑关系的人(我拉黑的 ∪ 拉黑我的)从列表中剔除;按配对时间倒序分页。

    Args:
        request: DRF 请求对象,支持 ``limit`` / ``offset``。

    Returns:
        分页后的配对条目数组。
    """
    me = request.user
    blocked_ids = blocked_user_ids(me)
    matches = (Match.objects.filter(Q(user_a=me) | Q(user_b=me), unmatched_at__isnull=True)
               .exclude(Q(user_a_id__in=blocked_ids) | Q(user_b_id__in=blocked_ids))
               .select_related("user_a__profile", "user_b__profile")
               .prefetch_related("user_a__photos", "user_b__photos"))
    entries = [_match_entry(match, me, request) for match in matches]
    paginator = DefaultLimitOffsetPagination()   # Match Meta ordering=-created_at,翻页顺序稳定
    page = paginator.paginate_queryset(entries, request)
    return paginator.get_paginated_response(page)


@api_view(["DELETE"])
def unmatch(request, user_id):
    """解除配对(DELETE /api/v1/matches/{user_id})。

    幂等:没有配对 / 已解除 / 解除自己都返回 204,与 ``DELETE /blocks/{user_id}``
    保持一致。解除是软删除(``unmatched_at`` 落时间戳),并双向拉黑 IM,
    之后双方既收不到、也发不出消息。

    Args:
        request: DRF 请求对象。
        user_id: 对方的账号 id。

    Returns:
        204 空响应。
    """
    me = request.user
    match = (Match.objects
             .filter(Q(user_a=me, user_b_id=user_id) | Q(user_b=me, user_a_id=user_id))
             .first())
    if match is None or match.unmatched_at is not None:
        return Response(status=204)
    other = match.other_user(me)
    with transaction.atomic():
        match.unmatched_at = timezone.now()
        match.unmatched_by = me
        match.save(update_fields=["unmatched_at", "unmatched_by"])
        transaction.on_commit(
            lambda: im_tasks.unmatch_blacklist.delay(me.id, other.id), robust=True)
    return Response(status=204)


def _match_entry(match, me, request):
    """把一条配对记录整理成列表项。

    头像取对方第一张已过审照片,并转成绝对 URL(IM 与会话列表需要可直接访问的地址)。

    Args:
        match: 配对记录。
        me: 当前用户,用于确定「对方」是谁。
        request: 当前请求,用于构造绝对 URL。

    Returns:
        列表项字典(``user_id`` / ``im_user_id`` / ``nickname`` / ``avatar_url`` /
        ``matched_at``)。
    """
    other = match.other_user(me)
    profile = getattr(other, "profile", None)
    approved = [p for p in other.photos.all() if p.status == PhotoStatus.APPROVED]
    return {
        "user_id": other.id,
        "im_user_id": other.im_user_id,
        "nickname": profile.nickname if profile else "",
        "avatar_url": request.build_absolute_uri(approved[0].file.url) if approved else None,
        "matched_at": match.created_at,
    }


@api_view(["GET"])
def likes_received(request):
    """喜欢我的人列表(GET /api/v1/discovery/likes)。

    Args:
        request: DRF 请求对象,支持 ``limit`` / ``offset``。

    Returns:
        分页后的「喜欢我的人」列表,字段见 ``LikeReceivedSerializer``。
    """
    qs = likes_received_queryset(request.user)
    paginator = DefaultLimitOffsetPagination()
    page = paginator.paginate_queryset(qs, request)
    return paginator.get_paginated_response(
        LikeReceivedSerializer(page, many=True, context={"request": request}).data)


@api_view(["GET"])
def likes_received_count(request):
    """喜欢我的人数(GET /api/v1/discovery/likes/count)。

    Args:
        request: DRF 请求对象。

    Returns:
        ``{"count": N}``,与列表同口径,供入口角标使用。
    """
    return Response({"count": likes_received_queryset(request.user).count()})
