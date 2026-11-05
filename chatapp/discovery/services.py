"""配对相关的领域服务。

三件事:
    1. ``likes_received_queryset`` 是「喜欢我的人」的**唯一口径**,列表与计数共用;
    2. 候选池的查询与缓存(``candidate_pool_ids``):按用户版本 + 全局版本做键,
       写路径升版本即可让旧缓存不可达(详见 ``config/cache_utils.py``);
    3. 配对成功后给双方发 IM 灰条。之所以独立成模块而不是写在视图里,
       是为了让「配对成功」这件事的副作用只有一个入口,便于后续追加(如推送、埋点)。
"""

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q

from config import cache_utils
from im import tasks as im_tasks
from moderation.services import exclude_blocked
from users.models import (Photo, PhotoStatus, Profile, ProfileStatus, ProfileVisit,
                          birthday_bounds)

from .cache_keys import POOL_VERSION_KEY, user_version_key
from .models import Match, Swipe, SwipeAction


def candidate_pool_queryset(me, preference, pool_size: int):
    """候选池查询集(不含缓存),供缓存回填与执行计划分析共用。

    三处排除都写成 ``NOT EXISTS`` 子查询而不是「先把 id 拉进 Python 再 ``__in``」:
    后者生成的 SQL 会随用户活跃度线性变长(划过几百人就有几百个占位符),
    而且命中不了索引(审查 N-4/N-5)。

    Args:
        me: 当前用户。
        preference: 当前用户的「想找的人」偏好。
        pool_size: 池子大小(取前 N 个)。

    Returns:
        按 ``shuffle_key`` 排序的 ``Profile`` 查询集。
    """
    swiped_exists = Exists(Swipe.objects.filter(swiper=me, target_id=OuterRef("user_id")))
    matched_exists = Exists(Match.objects.filter(
        Q(user_a=me, user_b_id=OuterRef("user_id")) | Q(user_b=me, user_a_id=OuterRef("user_id"))))

    # 只让有已过审照片的人进候选。用子查询而非 JOIN,避免产生重复行,
    # 也避免 distinct 与随机排序互相冲突(``(status, user_id)`` 索引专为它而建)。
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    qs = (Profile.objects.filter(status=ProfileStatus.COMPLETE, user_id__in=with_photos)
          .exclude(user_id=me.id)
          .exclude(swiped_exists)
          .exclude(matched_exists))
    qs = exclude_blocked(qs, me, "user_id")

    if preference.target_gender:
        qs = qs.filter(gender=preference.target_gender)
    if preference.city:
        qs = qs.filter(city=preference.city)
    upper, lower = birthday_bounds(preference.age_min, preference.age_max)
    qs = qs.filter(birthday__lte=upper, birthday__gt=lower)
    return qs.order_by("shuffle_key", "id")[:pool_size]


def _query_pool_ids(me, preference, pool_size: int) -> list[int]:
    """查候选池 id(未命中缓存时的真实查询)。

    Args:
        me: 当前用户。
        preference: 「想找的人」偏好。
        pool_size: 池子大小。

    Returns:
        候选用户 id 列表。
    """
    return list(candidate_pool_queryset(me, preference, pool_size)
                .values_list("user_id", flat=True))


def candidate_pool_ids(me, preference, pool_size: int) -> list[int]:
    """候选池(带缓存):同一用户在同一版本内复用同一份 id 列表。

    ``CANDIDATE_CACHE_TTL <= 0`` 表示**显式关闭缓存**(直接查库、不读也不写缓存)。
    为什么需要这个开关:``ttl_with_jitter`` 会把 0 兜成 1 秒,只把 TTL 设 0 并不能
    真正关掉缓存,于是「开/关缓存」的对比实验没法做(E-7);顺带它也是线上可用的
    缓存熔断手段(缓存怀疑有问题时设 0 重启即可退回纯查库)。

    Args:
        me: 当前用户。
        preference: 「想找的人」偏好。
        pool_size: 池子大小。

    Returns:
        候选用户 id 列表;缓存关闭或不可用时退化为直接查库。
    """
    ttl = int(getattr(settings, "CANDIDATE_CACHE_TTL", 30))
    if ttl <= 0:
        return _query_pool_ids(me, preference, pool_size)
    key = "disc:cand:{}:u{}:g{}:p{}".format(
        me.id,
        cache_utils.version(user_version_key(me.id)),
        cache_utils.version(POOL_VERSION_KEY),
        pool_size,
    )
    ids = cache_utils.get_or_load(
        key, ttl, lambda: _query_pool_ids(me, preference, pool_size), name="candidates")
    return ids or []


def notify_match(match):
    """配对成功后给双方各发一条 IM 灰条消息(经任务队列,失败可重试)。

    on_commit:配对真正落库后才入队;robust=True:broker 抖动不影响配对结果。

    Args:
        match: 刚创建的配对记录,双方 id 从它上面取。
    """
    a_id, b_id = match.user_a_id, match.user_b_id
    transaction.on_commit(lambda: im_tasks.pair_add.delay(a_id, b_id), robust=True)
    transaction.on_commit(lambda: im_tasks.send_match_notice.delay(a_id, b_id), robust=True)


def likes_received_queryset(me):
    """收到的喜欢:与候选池同口径,排除我已划过 / 双向拉黑 / 资料不全的人。

    Args:
        me: 当前用户。

    Returns:
        以 ``Swipe`` 为行的查询集,按喜欢时间倒序;列表与计数必须共用它。
    """
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    qs = (Swipe.objects
          .filter(target=me, action=SwipeAction.LIKE)
          .exclude(swiper_id=me.id)
          .exclude(Exists(Swipe.objects.filter(swiper=me, target_id=OuterRef("swiper_id"))))
          .filter(swiper__profile__status=ProfileStatus.COMPLETE)
          .filter(swiper_id__in=with_photos)
          .select_related("swiper__profile")
          .prefetch_related("swiper__photos", "swiper__profile__tags")
          .order_by("-created_at", "-id"))
    return exclude_blocked(qs, me, "swiper_id")


def visits_received_queryset(me):
    """谁看过我:与「喜欢我的人」同口径,排除我已划过 / 双向拉黑 / 资料不全。

    已配对的人不需要单独过滤:配对的前提是双方都划过对方,「排除我已划过」已天然覆盖。

    Args:
        me: 当前用户。

    Returns:
        以 ``ProfileVisit`` 为行的查询集,按最近访问时间倒序;列表与计数必须共用它。
    """
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    qs = (ProfileVisit.objects
          .filter(owner=me)
          .exclude(viewer_id=me.id)
          .exclude(Exists(Swipe.objects.filter(swiper=me, target_id=OuterRef("viewer_id"))))
          .filter(viewer__profile__status=ProfileStatus.COMPLETE)
          .filter(viewer_id__in=with_photos)
          .select_related("viewer__profile")
          .prefetch_related("viewer__photos", "viewer__profile__tags")
          .order_by("-last_at", "-id"))
    return exclude_blocked(qs, me, "viewer_id")