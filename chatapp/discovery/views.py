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

import random

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config import metrics
from config.cursor import paginated_response
from config.params import int_param
from config.schema_helpers import cursor_page, cursor_params
from im import tasks as im_tasks
from moderation.services import blocked_user_ids, exclude_blocked
from users.models import Photo, PhotoStatus, Profile, ProfileStatus, birthday_bounds
from users.serializers import TagSerializer, shared_tags_for_profiles
from users.services import get_profile

from .cache_keys import invalidate_candidates
from .models import Match, Swipe, SwipeAction
from .serializers import (CandidateSerializer, LikeReceivedSerializer, SwipeSerializer,
                          VisitSerializer)
from .services import (candidate_pool_ids, likes_received_queryset, notify_match,
                       visits_received_queryset)
from .throttles import (CandidateThrottle, SwipeThrottle, VisitsCountThrottle,
                        VisitsThrottle)

User = get_user_model()

DEFAULT_LIMIT = 10
MAX_LIMIT = 20

# 配对列表条目:由 ``_match_entry`` 直接拼字典,没有对应序列化器,这里给 schema 用
MATCH_ENTRY_SCHEMA = inline_serializer("MatchEntry", fields={
    "user_id": serializers.IntegerField(),
    "im_user_id": serializers.CharField(),
    "nickname": serializers.CharField(),
    "avatar_url": serializers.CharField(allow_null=True),
    "matched_at": serializers.DateTimeField(),
    "shared_tags": TagSerializer(many=True),
})


@extend_schema(parameters=[OpenApiParameter(
    "limit", int, OpenApiParameter.QUERY, required=False,
    description="拉取条数,默认 10,上限 20")],
    responses={200: CandidateSerializer(many=True)})
@api_view(["GET"])
@throttle_classes([CandidateThrottle])
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

    # 非法值统一 400,越界收敛到 [1, MAX_LIMIT];不再把负数透传给切片导致 500。
    limit = int_param(request, "limit", default=DEFAULT_LIMIT,
                      minimum=1, maximum=MAX_LIMIT)

    # 候选池走缓存(键带用户版本 + 全局版本,写路径升版本即失效):
    # 池子查询是这条接口最贵的一段,缓存后每次只做内存抽样 + 取 10 张资料卡。
    pool_size = max(limit, getattr(settings, "CANDIDATE_POOL_SIZE", 200))
    pool_ids = candidate_pool_ids(me, preference, pool_size)
    picked = random.sample(pool_ids, min(limit, len(pool_ids)))
    # 抽样后按 picked 的顺序回排;``user_id__in`` 查出来的顺序不保证
    profiles = {
        profile.user_id: profile
        for profile in Profile.objects.filter(user_id__in=picked)
        .prefetch_related("tags", "user__photos")
    }
    ordered = [profiles[user_id] for user_id in picked if user_id in profiles]
    return Response(CandidateSerializer(ordered, many=True,
                                        context={"request": request}).data)


@extend_schema(request=SwipeSerializer, responses={200: inline_serializer(
    "SwipeResult", fields={"matched": serializers.BooleanField(),
                           "shared_tags": TagSerializer(many=True)})})
@api_view(["POST"])
@throttle_classes([SwipeThrottle])
def swipe(request):
    """提交一次滑卡(POST /api/v1/discovery/swipe)。

    幂等:同一对用户重复提交保留第一次的动作;若本次形成互喜则创建配对,
    并在事务提交后给双方发 IM 灰条。配对成功时响应带 ``shared_tags``
    (共同标签),供「配对那一刻」的破冰文案直接使用 —— 客户端不必再拉一次
    ``GET /users/{id}``,否则会被记成一次访客访问(语义污染)。

    Args:
        request: DRF 请求对象,body 需带 ``target_user_id`` 与 ``action``。

    Returns:
        ``{"matched": bool, "shared_tags": [...]}``;未配对时 ``shared_tags`` 为空数组。

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
    # 拉黑是双向的:任一方向拉黑后,对方都不应再出现在我的可操作范围里(M11)。
    if target.id in blocked_user_ids(me):
        raise NotFound("用户不存在")
    if not Profile.objects.filter(user=target, status=ProfileStatus.COMPLETE).exists():
        raise ValidationError("对方资料不完整,无法操作")

    # 幂等:重复提交保留第一次的动作与结果
    swipe_obj, _ = Swipe.objects.get_or_create(swiper=me, target=target, defaults={"action": action})
    # 业务指标(E-4 ③):按「实际生效的动作」计数,幂等重放不会把 like 记成 pass。
    metrics.SWIPES.labels(action=swipe_obj.action).inc()
    # 划过的人必须立刻从我的候选池消失:升版本,旧缓存键随即不可达。
    invalidate_candidates(me.id)

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
                    # 只在「新建配对」时计数:软删除的旧行被 get_or_create 捞出来不算新配对。
                    metrics.MATCHES.inc()
                    notify_match(match)
                    # 对方也进入了「已配对」状态,候选池同样要失效。
                    invalidate_candidates(target.id)
                matched = True

    shared_tags = (shared_tags_for_profiles([getattr(target, "profile", None)], me)
                   .get(target.id, []) if matched else [])
    return Response({"matched": matched, "shared_tags": shared_tags})


@extend_schema(parameters=cursor_params(),
               responses={200: cursor_page("MatchPage", MATCH_ENTRY_SCHEMA)})
@api_view(["GET"])
def match_list(request):
    """我的配对列表(GET /api/v1/matches)。

    与我有拉黑关系的人(我拉黑的 ∪ 拉黑我的)从列表中剔除;按配对时间倒序分页。

    Args:
        request: DRF 请求对象,支持 ``limit`` / ``before``(或兼容的 ``offset``)。

    Returns:
        分页后的配对条目数组。
    """
    me = request.user
    # 拉黑用 NOT EXISTS 而不是把 id 拉进 Python 再 __in:配对行的数量会随用户成长,
    # 占位符列表同样会线性变长(审查 N-4)。配对双方各排一次。
    matches = (Match.objects.filter(Q(user_a=me) | Q(user_b=me), unmatched_at__isnull=True)
               .select_related("user_a__profile", "user_b__profile")
               .prefetch_related("user_a__photos", "user_b__photos"))
    matches = exclude_blocked(exclude_blocked(matches, me, "user_a_id"), me, "user_b_id")
    # 显式补 -id 兜底:同一次配对不可能同微秒发生,但游标要求「排序完全确定」,
    # 少了它 MySQL 对同一 created_at 的行顺序不保证,翻页可能漏行。
    matches = matches.order_by("-created_at", "-id")
    return paginated_response(request, matches,
                              lambda rows: _match_entries(rows, me, request))


@extend_schema(responses={204: None})
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
        transaction.on_commit(
            lambda: im_tasks.pair_remove.delay(me.id, other.id), robust=True)
    return Response(status=204)


def _match_entries(matches, me, request):
    """把一页配对记录整理成列表项,共同标签**一次批量求交**。

    ``shared_tags`` 供配对那一刻的破冰文案使用。整页只多一条 M2M 查询,
    不随配对条数增长(``config/test_query_budget.py`` 会拦 N+1)。

    Args:
        matches: 本页配对记录。
        me: 当前用户,用于确定「对方」是谁。
        request: 当前请求,用于构造绝对 URL。

    Returns:
        列表项数组,字段见 ``MATCH_ENTRY_SCHEMA``。
    """
    profiles = [getattr(match.other_user(me), "profile", None) for match in matches]
    shared_map = shared_tags_for_profiles(profiles, me)
    return [_match_entry(match, me, request,
                         shared_map.get(match.other_user(me).id, []))
            for match in matches]


def _match_entry(match, me, request, shared_tags):
    """把一条配对记录整理成列表项。

    头像取对方第一张已过审照片,并转成绝对 URL(IM 与会话列表需要可直接访问的地址)。

    Args:
        match: 配对记录。
        me: 当前用户,用于确定「对方」是谁。
        request: 当前请求,用于构造绝对 URL。
        shared_tags: 已算好的共同标签数组(``{id, name, icon}``),无交集为空数组。

    Returns:
        列表项字典(``user_id`` / ``im_user_id`` / ``nickname`` / ``avatar_url`` /
        ``matched_at`` / ``shared_tags``)。
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
        "shared_tags": shared_tags,
    }


@extend_schema(parameters=cursor_params(),
               responses={200: cursor_page("LikePage", LikeReceivedSerializer)})
@api_view(["GET"])
def likes_received(request):
    """喜欢我的人列表(GET /api/v1/discovery/likes)。

    Args:
        request: DRF 请求对象,支持 ``limit`` / ``before``(或兼容的 ``offset``)。

    Returns:
        分页后的「喜欢我的人」列表,字段见 ``LikeReceivedSerializer``。
    """
    return paginated_response(
        request, likes_received_queryset(request.user),
        lambda rows: LikeReceivedSerializer(rows, many=True,
                                            context={"request": request}).data)


@extend_schema(responses={200: inline_serializer(
    "LikesCount", fields={"count": serializers.IntegerField()})})
@api_view(["GET"])
def likes_received_count(request):
    """喜欢我的人数(GET /api/v1/discovery/likes/count)。

    Args:
        request: DRF 请求对象。

    Returns:
        ``{"count": N}``,与列表同口径,供入口角标使用。
    """
    return Response({"count": likes_received_queryset(request.user).count()})

@extend_schema(parameters=cursor_params(),
               responses={200: cursor_page("VisitPage", VisitSerializer)})
@api_view(["GET"])
@throttle_classes([VisitsThrottle])
def visits(request):
    """谁看过我(GET /api/v1/discovery/visits)。

    Args:
        request: DRF 请求对象,支持 ``limit`` / ``before``(或兼容的 ``offset``)。

    Returns:
        分页后的访客列表,字段见 ``VisitSerializer``。
    """
    return paginated_response(
        request, visits_received_queryset(request.user),
        lambda rows: VisitSerializer(rows, many=True, context={"request": request}).data,
        field="last_at")


@extend_schema(responses={200: inline_serializer(
    "VisitsCount", fields={"count": serializers.IntegerField()})})
@api_view(["GET"])
@throttle_classes([VisitsCountThrottle])
def visits_count(request):
    """访客人数(GET /api/v1/discovery/visits/count)。

    Args:
        request: DRF 请求对象。

    Returns:
        ``{"count": N}``,与列表同口径,供入口角标使用。
    """
    return Response({"count": visits_received_queryset(request.user).count()})