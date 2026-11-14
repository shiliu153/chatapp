"""发现页的候选卡片、滑卡与配对列表接口。

设计要点:
    1. **候选池的排除规则**:排除自己、划过的人、已配对的人、双向拉黑的人,
       并且只收 ``status=COMPLETE``(资料完善)且**至少有一张已过审照片**的人;
    2. **滑卡幂等**:同一对 ``(我, 他)`` 只有一条记录,重复提交保留第一次的动作,
       因此重试不会把「喜欢」翻成「跳过」;
    3. **配对是互喜的结果**:只有双方都是 ``like`` 才建 ``Match``,并在事务提交后
       给双方各发一条 IM 灰条;
    4. **解除配对是软删除 + 双向拉黑**:``DELETE /matches/{user_id}`` 只打时间戳,
       读侧统一过滤 ``unmatched_at__isnull=True``;已解除的配对不会被再次滑卡复活;
    5. **撤销滑卡是硬删除**(批次 O):只撤销「最近一次、30 秒内、未产生配对」的记录,
       删行后该目标重新回到候选池(候选池的 ``NOT EXISTS`` 排除条件一个字没改);
    6. **每日喜欢额度**(批次 O):``SWIPE_DAILY_LIKE_LIMIT`` 默认 0 = 不限,超限
       ``429`` + ``42904``;``action=pass`` 与幂等重放不占额度,详见 ``quota.py``;
    7. **临时筛选**(批次 S):``candidates`` 的 ``age_min`` / ``age_max`` / ``city`` /
       ``tag_ids`` 是查询参数,**不落库、不写回 Preference**;空值时行为与加筛选前
       完全一致(连缓存键都不变);
    8. **今日精选**(批次 S):``daily`` 复用同一套候选池,按「共同标签数 → 同城 → 种子
       随机」排序,种子 = ``(日期, 用户 id)``,当天稳定、跨天自动换。

关联文档:
    - 接口契约:docs/api/discovery.md

文件信息:
    文件名称          discovery/views.py
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
import random
from datetime import timedelta

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

from . import quota
from .cache_keys import invalidate_candidates
from .exceptions import SwipeUndoUnavailable
from .models import Match, Swipe, SwipeAction
from .serializers import (CandidateSerializer, DailyCandidatesSerializer,
                          LikeReceivedSerializer, SwipeQuotaSerializer, SwipeSerializer,
                          SwipeUndoSerializer, VisitSerializer)
from .services import (CandidateFilters, candidate_pool_ids, daily_candidate_ids,
                       likes_received_queryset, notify_match, visits_received_queryset)
from .throttles import (CandidateThrottle, SwipeThrottle, SwipeUndoThrottle,
                        VisitsCountThrottle, VisitsThrottle)

User = get_user_model()

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 10
MAX_LIMIT = 20

# 今日精选(批次 S):默认 6 张、上限 12,客户端按 ``date`` 判断「今天已看过」。
DEFAULT_DAILY_LIMIT = 6
MAX_DAILY_LIMIT = 12

# 筛选参数的合法区间:18 岁是合规下限(与 PreferenceSerializer 同口径),
# 城市长度对齐 Profile.city 的 max_length,标签数与标签池(12 个)同量级留点余量。
FILTER_AGE_MIN = 18
FILTER_AGE_MAX = 99
FILTER_CITY_MAX_LENGTH = 50
FILTER_TAG_IDS_MAX = 20

# 撤销窗口(秒):前端按钮的倒计时环按同一个数字渲染,docs/api/discovery.md §3.9 有写。
UNDO_WINDOW_SECONDS = 30

# 配对列表条目:由 ``_match_entry`` 直接拼字典,没有对应序列化器,这里给 schema 用
MATCH_ENTRY_SCHEMA = inline_serializer("MatchEntry", fields={
    "user_id": serializers.IntegerField(),
    "im_user_id": serializers.CharField(),
    "nickname": serializers.CharField(),
    "avatar_url": serializers.CharField(allow_null=True),
    "matched_at": serializers.DateTimeField(),
    "shared_tags": TagSerializer(many=True),
})


def _param_given(request, name: str) -> bool:
    """查询参数是否「给了且非空串」(用于区分「没传」与「传了空值」)。

    参数说明:
        request: DRF 请求对象。
        name: 参数名。

    返回参数:
        参数存在且去掉首尾空白后非空时为 ``True``。

    使用示例:
        ``_param_given(request, "age_min")``

    备注信息:
        只看 ``query_params``,不看请求体;``age_min=`` 这类空值按「没传」处理,
        保证筛选项留空时回落偏好。
    """
    value = request.query_params.get(name)
    return value is not None and value.strip() != ""


def _parse_tag_ids(request) -> tuple[int, ...]:
    """解析逗号分隔的 ``tag_ids``。

    参数说明:
        request: DRF 请求对象。

    返回参数:
        去重后升序的标签 id 元组;没传或空串返回空元组。

    使用示例:
        ``_parse_tag_ids(request)``

    备注信息:
        含非整数、非正整数,或个数超过 ``FILTER_TAG_IDS_MAX`` 时抛
        ``ValidationError``(统一 400),不静默丢弃非法项。
    """
    raw = (request.query_params.get("tag_ids") or "").strip()
    if not raw:
        return ()
    tag_ids: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            tag_id = int(chunk)
        except (TypeError, ValueError) as error:
            raise ValidationError({"tag_ids": "必须是逗号分隔的整数"}) from error
        if tag_id <= 0:
            raise ValidationError({"tag_ids": "必须是正整数"})
        if tag_id not in tag_ids:
            tag_ids.append(tag_id)
    if len(tag_ids) > FILTER_TAG_IDS_MAX:
        raise ValidationError({"tag_ids": f"最多 {FILTER_TAG_IDS_MAX} 个"})
    return tuple(sorted(tag_ids))


def _parse_filters(request) -> CandidateFilters:
    """解析候选池的临时筛选参数(缺省 = 不筛,非法值一律 400)。

    参数缺省时 ``CandidateFilters`` 的字段留 ``None``,由服务层回落到「想找的人」
    偏好 —— 这也是「不带任何筛选时缓存键一字不改」的前提。

    参数说明:
        request: DRF 请求对象。

    返回参数:
        解析好的筛选条件(可能全空)。

    使用示例:
        ``filters = _parse_filters(request)``

    备注信息:
        年龄不是整数或超出 18–99、城市超过 ``FILTER_CITY_MAX_LENGTH`` 个字符、
        ``tag_ids`` 非法,一律抛 ``ValidationError``(400);参数缺省时不落库也不写回
        ``Preference``,由服务层回落偏好。
    """
    age_min = age_max = None
    if _param_given(request, "age_min"):
        age_min = int_param(request, "age_min", default=FILTER_AGE_MIN,
                            minimum=FILTER_AGE_MIN, maximum=FILTER_AGE_MAX)
    if _param_given(request, "age_max"):
        age_max = int_param(request, "age_max", default=FILTER_AGE_MAX,
                            minimum=FILTER_AGE_MIN, maximum=FILTER_AGE_MAX)
    city = (request.query_params.get("city") or "").strip()
    if len(city) > FILTER_CITY_MAX_LENGTH:
        raise ValidationError({"city": f"城市名最长 {FILTER_CITY_MAX_LENGTH} 个字符"})
    return CandidateFilters(age_min=age_min, age_max=age_max, city=city or None,
                            tag_ids=_parse_tag_ids(request))


def _candidate_cards(user_ids, request) -> list[dict]:
    """按给定顺序取候选卡片(批量取资料 + 预取标签照片,不随张数增长)。

    参数说明:
        user_ids: 候选人账号 id 序列,顺序即响应顺序。
        request: 当前请求,用于构造照片的绝对 URL。

    返回参数:
        序列化后的候选卡片数组,字段见 ``CandidateSerializer``。

    使用示例:
        ``_candidate_cards(picked, request)``

    备注信息:
        一条 ``user_id__in`` 查询 + 预取标签与照片;池子里已删号或资料不全的人
        会被跳过,因此返回张数可能少于入参个数。
    """
    # ``user_id__in`` 查出来的顺序不保证,所以按入参顺序回排
    profiles = {
        profile.user_id: profile
        for profile in Profile.objects.filter(user_id__in=user_ids)
        .prefetch_related("tags", "user__photos")
    }
    ordered = [profiles[user_id] for user_id in user_ids if user_id in profiles]
    return CandidateSerializer(ordered, many=True, context={"request": request}).data


@extend_schema(parameters=[
    OpenApiParameter("limit", int, OpenApiParameter.QUERY, required=False,
                     description="拉取条数,默认 10,上限 20"),
    OpenApiParameter("age_min", int, OpenApiParameter.QUERY, required=False,
                     description="年龄下限(含),18–99;缺省沿用「想找的人」偏好"),
    OpenApiParameter("age_max", int, OpenApiParameter.QUERY, required=False,
                     description="年龄上限(含),18–99;缺省沿用「想找的人」偏好"),
    OpenApiParameter("city", str, OpenApiParameter.QUERY, required=False,
                     description="只看这个城市;缺省沿用偏好"),
    OpenApiParameter("tag_ids", str, OpenApiParameter.QUERY, required=False,
                     description="标签 id,逗号分隔(命中其一即可);缺省不筛标签")],
    responses={200: CandidateSerializer(many=True)})
@api_view(["GET"])
@throttle_classes([CandidateThrottle])
def candidates(request):
    """候选卡片列表(GET /api/v1/discovery/candidates)。

    按「想找的人」偏好过滤(性别、城市、年龄区间),再套用候选池的排除规则;
    可选的 ``age_min`` / ``age_max`` / ``city`` / ``tag_ids`` 在**本次请求内**覆盖
    对应的偏好字段(不写回偏好),缺省时行为与加筛选前完全一致。

    参数说明:
        request: DRF 请求对象,支持 ``limit``(默认 10,上限 20)与四个筛选参数。

    返回参数:
        候选卡片数组,字段见 ``CandidateSerializer``;池子不足时返回的张数少于 ``limit``。

    使用示例:
        ``GET /api/v1/discovery/candidates?limit=10&age_min=25&city=杭州``

    备注信息:
        候选池走缓存(键带用户版本 + 全局版本),每次只做内存随机抽样;
        只有真的带了筛选才走带指纹的分桶键,默认路径命中原来那份缓存。
        ``limit`` 越界收敛到 ``[1, MAX_LIMIT]``,非法筛选参数 400。
    """
    me = request.user
    preference = get_profile(me).preference

    # 非法值统一 400,越界收敛到 [1, MAX_LIMIT];不再把负数透传给切片导致 500。
    limit = int_param(request, "limit", default=DEFAULT_LIMIT,
                      minimum=1, maximum=MAX_LIMIT)
    filters = _parse_filters(request)

    # 候选池走缓存(键带用户版本 + 全局版本,写路径升版本即失效):
    # 池子查询是这条接口最贵的一段,缓存后每次只做内存抽样 + 取 10 张资料卡。
    # 注意:只有真的带了筛选才会走带指纹的分桶键,默认路径命中原来那份缓存。
    pool_size = max(limit, getattr(settings, "CANDIDATE_POOL_SIZE", 200))
    pool_ids = candidate_pool_ids(me, preference, pool_size, filters)
    picked = random.sample(pool_ids, min(limit, len(pool_ids)))
    return Response(_candidate_cards(picked, request))


@extend_schema(parameters=[OpenApiParameter(
    "limit", int, OpenApiParameter.QUERY, required=False,
    description="精选张数,默认 6,上限 12")],
    responses={200: DailyCandidatesSerializer})
@api_view(["GET"])
@throttle_classes([CandidateThrottle])
def daily(request):
    """今日精选(GET /api/v1/discovery/daily)。

    从同一套候选池里取 N 张(排除规则与 ``candidates`` 完全一致),按
    「共同标签数 desc → 同城优先 → 种子随机」排序;种子 = ``(日期, 用户 id)``,
    因此**同一天反复刷新结果与顺序都不变**,第二天自动换一批。

    参数说明:
        request: DRF 请求对象,支持 ``limit``(默认 6,上限 12)。

    返回参数:
        ``{"date": <日期>, "candidates": [候选卡...]}``,卡片字段与
        ``GET /discovery/candidates`` 一致。

    使用示例:
        ``GET /api/v1/discovery/daily?limit=6``

    备注信息:
        与 ``candidates`` 同款限流:精选每刷新一次都要过一遍池子,不能变成免限流的旁路;
        ``date`` 是服务端本地日期,客户端据此判断「今天已看过」。
    """
    me = request.user
    preference = get_profile(me).preference
    # 与 candidates 同款限流:精选每刷新一次都要过一遍池子,不能变成免限流的旁路。
    limit = int_param(request, "limit", default=DEFAULT_DAILY_LIMIT,
                      minimum=1, maximum=MAX_DAILY_LIMIT)
    day, user_ids = daily_candidate_ids(me, preference, limit)
    return Response({"date": day.isoformat(),
                     "candidates": _candidate_cards(user_ids, request)})


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

    参数说明:
        request: DRF 请求对象,body 需带 ``target_user_id`` 与 ``action``。

    返回参数:
        ``{"matched": bool, "shared_tags": [...]}``;未配对时 ``shared_tags`` 为空数组。

    使用示例:
        ``POST /api/v1/discovery/swipe`` body ``{"target_user_id": 9, "action": "like"}``

    备注信息:
        当前账号被封禁(轻封禁也禁止滑卡)抛 ``PermissionDenied``;划自己或对方资料
        不完整抛 ``ValidationError``;只有「注定会新写一条 like」的请求才扣当日额度
        (幂等重放与 ``action=pass`` 不扣),超限抛 ``SwipeLikeQuotaExceeded``
        (429 + 42904)。写库后立刻升候选池版本,划过的人随即消失。
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

    # 每日额度(批次 O):只有「注定会新写一条 like」的请求才占用额度 ——
    # 幂等重放(这一对我已经划过)与 action=pass 都不计,否则重试与跳过会白吃额度。
    # 必须在写库之前判断:超限的请求不该留下任何 Swipe 行。
    if action == SwipeAction.LIKE and not Swipe.objects.filter(swiper=me, target=target).exists():
        quota.consume_like(me.id)

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


@extend_schema(request=None, responses={200: SwipeUndoSerializer})
@api_view(["POST"])
@throttle_classes([SwipeUndoThrottle])
def swipe_undo(request):
    """撤销最近一次滑卡(POST /api/v1/discovery/swipe/undo)。

    只撤销「**我最近一次**、``UNDO_WINDOW_SECONDS`` 秒内、且**未产生配对**」的滑卡:

    - 实现是**硬删除**那一条 ``Swipe`` 行 —— 软删除要连带改候选池的 ``NOT EXISTS``
      排除条件(索引与 ``test_query_budget`` 的预算都会被牵动),收益为零;
    - 删完之后该目标会重新出现在 ``GET /discovery/candidates`` 里,所以顺带让本人的
      候选池缓存失效;
    - **已产生配对的滑卡一律不撤销**:回滚 ``Match`` + 解除 IM 拉黑 + 回收两条灰条,
      风险远大于「误划」的收益,因此只给 ``400``;
    - 额度也跟着退回(``quota.refund_like``):撤销意味着「那次操作没有发生」。

    参数说明:
        request: DRF 请求对象;无请求体。

    返回参数:
        ``{"undone": true, "target_user_id": <int>}``,被撤销的那次滑卡的目标账号 id。

    使用示例:
        ``POST /api/v1/discovery/swipe/undo``

    备注信息:
        当前账号被轻封禁抛 ``PermissionDenied``(与 ``POST /discovery/swipe`` 同口径);
        没有可撤销的滑卡(无记录 / 超过 30 秒 / 已配对)抛 ``SwipeUndoUnavailable``
        (400 + 40003)。删除是条件删除并检查影响行数,并发两次撤销只有一次成功;
        撤销的是 like 时同步退回额度,并升本人的候选池版本让目标重新入池。
    """
    me = request.user
    # 与滑卡同口径:轻封禁只禁滑卡,撤销也算滑卡的一部分。
    if get_profile(me).is_banned:
        raise PermissionDenied("账号已被限制,暂时无法滑卡")

    # ``Swipe.Meta.ordering`` 是 ``-created_at``,这里补 ``-id`` 兜底:同一微秒内的两条
    # 记录在 MySQL 里顺序不保证,撤销必须落在「最新那条」上。
    latest = Swipe.objects.filter(swiper=me).order_by("-created_at", "-id").first()
    if latest is None:
        raise SwipeUndoUnavailable("没有可撤销的滑卡")
    if latest.created_at < timezone.now() - timedelta(seconds=UNDO_WINDOW_SECONDS):
        raise SwipeUndoUnavailable(f"滑卡已超过 {UNDO_WINDOW_SECONDS} 秒,不能再撤销")

    target_id = latest.target_id
    if Match.objects.filter(Q(user_a=me, user_b_id=target_id)
                            | Q(user_b=me, user_a_id=target_id)).exists():
        # 含已解除的配对:那一对已经建立过关系(灰条、IM 拉黑都发生过),撤销它是另一码事。
        raise SwipeUndoUnavailable("这条滑卡已经配对成功,不能撤销")

    # 条件删除 + 检查影响行数:并发两次撤销只有一次能删到行,另一次拿到 0 行。
    deleted, _ = Swipe.objects.filter(pk=latest.pk).delete()
    if not deleted:
        raise SwipeUndoUnavailable("没有可撤销的滑卡")

    if latest.action == SwipeAction.LIKE:
        quota.refund_like(me.id)
    # 目标重新回到我的候选池:升版本让旧缓存(里面还排除了他)立刻不可达。
    invalidate_candidates(me.id)
    logger.info(
        "swipe_undo uid=%s target=%s action=%s swipe_id=%s",
        me.id, target_id, latest.action, latest.pk,
        extra={"user_id": me.id},
    )
    return Response({"undone": True, "target_user_id": target_id})


@extend_schema(responses={200: SwipeQuotaSerializer})
@api_view(["GET"])
def quota_view(request):
    """查询每日喜欢额度(GET /api/v1/discovery/quota)。

    只读一个 Redis 计数,不查库;``like_limit = 0``(不限)时 ``likes_used`` 恒为 0、
    ``likes_remaining`` 为 ``null``,客户端据此决定要不要显示额度文案。

    参数说明:
        request: DRF 请求对象。

    返回参数:
        ``{"like_limit": int, "likes_used": int, "likes_remaining": int|null}``。

    使用示例:
        ``GET /api/v1/discovery/quota``

    备注信息:
        只读一个 Redis 计数,不查库;``like_limit = 0``(不限)时 ``likes_used`` 恒为 0、
        ``likes_remaining`` 为 ``null``,客户端据此决定要不要显示额度文案。
    """
    return Response(quota.quota_snapshot(request.user.id))


@extend_schema(parameters=cursor_params(),
               responses={200: cursor_page("MatchPage", MATCH_ENTRY_SCHEMA)})
@api_view(["GET"])
def match_list(request):
    """我的配对列表(GET /api/v1/matches)。

    与我有拉黑关系的人(我拉黑的 ∪ 拉黑我的)从列表中剔除;按配对时间倒序分页。

    参数说明:
        request: DRF 请求对象,支持 ``limit`` / ``before``(或兼容的 ``offset``)。

    返回参数:
        分页后的配对条目数组,条目字段见 ``MATCH_ENTRY_SCHEMA``。

    使用示例:
        ``GET /api/v1/matches?limit=20&before=<游标>``

    备注信息:
        只取 ``unmatched_at__isnull=True``(未解除)的配对,按 ``-created_at, -id``
        排序;游标分页要求排序完全确定,补 ``-id`` 兜底才不漏行。拉黑用两个
        ``NOT EXISTS`` 各排一次,不把 id 拉进 Python 再 ``__in``。
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

    参数说明:
        request: DRF 请求对象。
        user_id: 对方的账号 id(路径参数)。

    返回参数:
        204 空响应(没有配对 / 已解除时同样 204)。

    使用示例:
        ``DELETE /api/v1/matches/9``

    备注信息:
        软删除只打 ``unmatched_at`` 与 ``unmatched_by`` 时间戳,读侧统一过滤;
        事务提交后异步做 IM 双向拉黑并移除配对关系(``robust=True``),
        已解除的配对不会被再次滑卡复活。
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

    参数说明:
        matches: 本页配对记录。
        me: 当前用户,用于确定「对方」是谁。
        request: 当前请求,用于构造绝对 URL。

    返回参数:
        列表项数组,字段见 ``MATCH_ENTRY_SCHEMA``。

    使用示例:
        ``_match_entries(rows, me, request)``

    备注信息:
        整页只多一条 M2M 查询算共同标签,不随配对条数增长(``test_query_budget`` 会拦 N+1)。
    """
    profiles = [getattr(match.other_user(me), "profile", None) for match in matches]
    shared_map = shared_tags_for_profiles(profiles, me)
    return [_match_entry(match, me, request,
                         shared_map.get(match.other_user(me).id, []))
            for match in matches]


def _match_entry(match, me, request, shared_tags):
    """把一条配对记录整理成列表项。

    头像取对方第一张已过审照片,并转成绝对 URL(IM 与会话列表需要可直接访问的地址)。

    参数说明:
        match: 配对记录。
        me: 当前用户,用于确定「对方」是谁。
        request: 当前请求,用于构造绝对 URL。
        shared_tags: 已算好的共同标签数组(``{id, name, icon}``),无交集为空数组。

    返回参数:
        列表项字典(``user_id`` / ``im_user_id`` / ``nickname`` / ``avatar_url`` /
        ``matched_at`` / ``shared_tags``)。

    使用示例:
        ``_match_entry(match, me, request, shared_tags)``

    备注信息:
        照片从 ``prefetch_related`` 缓存里挑第一张已过审的,不再单独查库;对方资料缺失
        时昵称回落空串,无已过审照片时 ``avatar_url`` 为 ``None``。
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

    参数说明:
        request: DRF 请求对象,支持 ``limit`` / ``before``(或兼容的 ``offset``)。

    返回参数:
        分页后的「喜欢我的人」列表,字段见 ``LikeReceivedSerializer``。

    使用示例:
        ``GET /api/v1/discovery/likes?limit=20``

    备注信息:
        口径来自 ``likes_received_queryset``(排除我已划过 / 双向拉黑 / 资料不全),
        按喜欢时间倒序分页;``count`` 接口与它共用同一份查询集。
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

    参数说明:
        request: DRF 请求对象。

    返回参数:
        ``{"count": N}``,与列表同口径,供入口角标使用。

    使用示例:
        ``GET /api/v1/discovery/likes/count``

    备注信息:
        与 ``GET /discovery/likes`` 共用 ``likes_received_queryset``,不另写一份口径;
        只取计数,不拉行内容。
    """
    return Response({"count": likes_received_queryset(request.user).count()})

@extend_schema(parameters=cursor_params(),
               responses={200: cursor_page("VisitPage", VisitSerializer)})
@api_view(["GET"])
@throttle_classes([VisitsThrottle])
def visits(request):
    """谁看过我(GET /api/v1/discovery/visits)。

    参数说明:
        request: DRF 请求对象,支持 ``limit`` / ``before``(或兼容的 ``offset``)。

    返回参数:
        分页后的访客列表,字段见 ``VisitSerializer``。

    使用示例:
        ``GET /api/v1/discovery/visits?limit=20``

    备注信息:
        口径来自 ``visits_received_queryset``(排除我已划过 / 双向拉黑 / 资料不全);
        游标字段传 ``field="last_at"``,按最近访问时间倒序而不是记录创建时间。
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

    参数说明:
        request: DRF 请求对象。

    返回参数:
        ``{"count": N}``,与列表同口径,供入口角标使用。

    使用示例:
        ``GET /api/v1/discovery/visits/count``

    备注信息:
        与 ``GET /discovery/visits`` 共用 ``visits_received_queryset``;该接口单独挂了
        ``VisitsCountThrottle``,限流口径与列表接口不同。
    """
    return Response({"count": visits_received_queryset(request.user).count()})