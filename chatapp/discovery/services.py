"""配对相关的领域服务。

四件事:
    1. ``likes_received_queryset`` 是「喜欢我的人」的**唯一口径**,列表与计数共用;
    2. 候选池的查询与缓存(``candidate_pool_ids``):按用户版本 + 全局版本做键,
       写路径升版本即可让旧缓存不可达(详见 ``config/cache_utils.py``);带筛选
       (``CandidateFilters``)时键尾追加筛选指纹分桶,**无筛选时键一字不改**;
    3. 「今日精选」(``daily_candidate_ids``):复用同一套候选池与排除规则,
       按「共同标签数 → 同城 → 种子随机」排序,当天稳定、跨天变化;
    4. 配对成功后给双方发 IM 灰条。之所以独立成模块而不是写在视图里,
       是为了让「配对成功」这件事的副作用只有一个入口,便于后续追加(如推送、埋点)。
"""

import hashlib
import random
from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from config import cache_utils
from im import tasks as im_tasks
from moderation.services import exclude_blocked
from notifications.models import NotificationKind, NotificationTarget
from notifications.services import notify_on_commit
from users.models import (Photo, PhotoStatus, Profile, ProfileStatus, ProfileVisit,
                          birthday_bounds)

from .cache_keys import POOL_VERSION_KEY, user_version_key
from .models import Match, Swipe, SwipeAction


@dataclass(frozen=True)
class CandidateFilters:
    """候选池的**临时**筛选条件(来自查询参数)。

    设计要点:
        1. **不落库**:筛选既不下发也不写回 ``Preference``(设置页仍是唯一持久化入口);
        2. **非空字段覆盖偏好**:只传 ``city`` 时年龄区间继续沿用用户设置,
           「临时筛一下」不会悄悄改掉用户的长期偏好;
        3. ``tag_ids`` 是纯增量条件(偏好里没有同名字段),空元组表示不筛标签。

    Attributes:
        age_min: 年龄下限(含);``None`` 表示沿用偏好。
        age_max: 年龄上限(含);``None`` 表示沿用偏好。
        city: 城市;``None`` / 空串表示沿用偏好。
        tag_ids: 至少命中一个的标签 id(已去重、升序);空元组表示不筛标签。
    """

    age_min: int | None = None
    age_max: int | None = None
    city: str | None = None
    tag_ids: tuple[int, ...] = ()

    def is_empty(self) -> bool:
        """是否完全没有筛选条件(缓存键要不要追加指纹的唯一判据)。

        Returns:
            四个字段都为空时为 ``True``。
        """
        return (self.age_min is None and self.age_max is None
                and not (self.city or "").strip() and not self.tag_ids)

    def fingerprint(self) -> str:
        """筛选指纹:缓存键尾部 ``:f{指纹}`` 的那一段。

        只对**筛选参数本身**求指纹,不掺用户偏好 —— 偏好变化有自己的版本键
        (``disc:ver:{uid}``),掺进来只会给同一份筛选多切出无意义的分桶,
        让默认路径的命中率继续退化。

        Returns:
            四个参数按固定顺序拼接后 sha1 的前 8 位十六进制。
        """
        parts = [
            "" if self.age_min is None else str(self.age_min),
            "" if self.age_max is None else str(self.age_max),
            (self.city or "").strip(),
            ",".join(str(tag_id) for tag_id in sorted(self.tag_ids)),
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:8]


def today_date() -> date:
    """「今天」的唯一来源(本地时区)。

    抽成函数是为了让「同一天稳定 / 跨天变化」可测:测试 monkeypatch 它即可,
    不要去 patch ``datetime.date.today`` —— 那会连带影响别处的日期逻辑。

    Returns:
        本地时区的今天。
    """
    return timezone.localdate()


def _resolve_age_bounds(preference, filters: CandidateFilters | None):
    """把「筛选覆盖偏好」之后的年龄区间换算成生日区间。

    Args:
        preference: 当前用户的「想找的人」偏好。
        filters: 临时筛选条件;``None`` 表示不筛选。

    Returns:
        ``(upper, lower)``,语义见 ``users.models.birthday_bounds``。

    Raises:
        ValidationError: 合并后的最小年龄大于最大年龄(如 ``age_min=40&age_max=20``)。
    """
    age_min = (filters.age_min if filters is not None and filters.age_min is not None
               else preference.age_min)
    age_max = (filters.age_max if filters is not None and filters.age_max is not None
               else preference.age_max)
    if age_min > age_max:
        raise ValidationError("最小年龄不能大于最大年龄")
    return birthday_bounds(age_min, age_max)


def candidate_pool_queryset(me, preference, pool_size: int,
                            filters: CandidateFilters | None = None):
    """候选池查询集(不含缓存),供缓存回填与执行计划分析共用。

    三处排除都写成 ``NOT EXISTS`` 子查询而不是「先把 id 拉进 Python 再 ``__in``」:
    后者生成的 SQL 会随用户活跃度线性变长(划过几百人就有几百个占位符),
    而且命中不了索引(审查 N-4/N-5)。

    ``filters`` 的非空字段覆盖偏好的同名字段。标签筛选用 ``Exists``
    (M2M 中间表的 ``NOT EXISTS`` 同款子查询)而不是
    ``filter(tags__id__in=...).distinct()``:后者要先 JOIN 再全局去重,
    而 ``[:pool_size]`` 的截断发生在去重之前,join 出来的行数被放大,
    同一个人的多个命中标签会挤掉别人的名额(重复行也会漏进切片)。

    Args:
        me: 当前用户。
        preference: 当前用户的「想找的人」偏好。
        pool_size: 池子大小(取前 N 个)。
        filters: 临时筛选条件;``None`` 或全空表示完全沿用偏好(默认路径)。

    Returns:
        按 ``shuffle_key`` 排序的 ``Profile`` 查询集,不含重复行。

    Raises:
        ValidationError: 合并后的年龄区间上下界倒置。
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
    # 城市:筛选优先,空则回落偏好的城市(空串 = 不限)
    city = (filters.city if filters is not None and (filters.city or "").strip()
            else preference.city)
    if city:
        qs = qs.filter(city=city)
    upper, lower = _resolve_age_bounds(preference, filters)
    qs = qs.filter(birthday__lte=upper, birthday__gt=lower)
    if filters is not None and filters.tag_ids:
        tag_exists = Exists(Profile.tags.through.objects.filter(
            profile_id=OuterRef("id"), tag_id__in=filters.tag_ids))
        qs = qs.filter(tag_exists)
    return qs.order_by("shuffle_key", "id")[:pool_size]


def _query_pool_ids(me, preference, pool_size: int,
                    filters: CandidateFilters | None = None) -> list[int]:
    """查候选池 id(未命中缓存时的真实查询)。

    Args:
        me: 当前用户。
        preference: 「想找的人」偏好。
        pool_size: 池子大小。
        filters: 临时筛选条件;``None`` 表示不筛选。

    Returns:
        候选用户 id 列表。
    """
    return list(candidate_pool_queryset(me, preference, pool_size, filters)
                .values_list("user_id", flat=True))


def candidate_pool_ids(me, preference, pool_size: int,
                       filters: CandidateFilters | None = None) -> list[int]:
    """候选池(带缓存):同一用户在同一版本内复用同一份 id 列表。

    缓存键 ``disc:cand:{uid}:u{ver}:g{ver}:p{size}`` 是候选接口唯一省掉那次重查询的
    机制(实测命中率 97.8%,见 docs/reports/cache-win-2026-11-05.md)。因此:

    - **筛选全空时键一字不改** —— 默认路径仍命中改动前那份缓存,不因本次改动
      多切一个分桶;
    - 有筛选时才在键尾追加 ``:f{指纹}``,让每份筛选各自成桶(筛选是自由组合,
      不按指纹分桶就会互相污染结果)。

    ``CANDIDATE_CACHE_TTL <= 0`` 表示**显式关闭缓存**(直接查库、不读也不写缓存)。
    为什么需要这个开关:``ttl_with_jitter`` 会把 0 兜成 1 秒,只把 TTL 设 0 并不能
    真正关掉缓存,于是「开/关缓存」的对比实验没法做(E-7);顺带它也是线上可用的
    缓存熔断手段(缓存怀疑有问题时设 0 重启即可退回纯查库)。

    Args:
        me: 当前用户。
        preference: 「想找的人」偏好。
        pool_size: 池子大小。
        filters: 临时筛选条件;``None`` 或全空走默认键。

    Returns:
        候选用户 id 列表;缓存关闭或不可用时退化为直接查库。

    Raises:
        ValidationError: 筛选与偏好合并后的年龄区间倒置。
    """
    ttl = int(getattr(settings, "CANDIDATE_CACHE_TTL", 30))
    if ttl <= 0:
        return _query_pool_ids(me, preference, pool_size, filters)
    key = "disc:cand:{}:u{}:g{}:p{}".format(
        me.id,
        cache_utils.version(user_version_key(me.id)),
        cache_utils.version(POOL_VERSION_KEY),
        pool_size,
    )
    if filters is not None and not filters.is_empty():
        key += ":f" + filters.fingerprint()
    ids = cache_utils.get_or_load(
        key, ttl, lambda: _query_pool_ids(me, preference, pool_size, filters),
        name="candidates")
    return ids or []


def shared_tag_counts(me, user_ids) -> dict[int, int]:
    """一条分组查询算出「候选池里每个人与我共有几个标签」。

    池子 ≤200 人、标签池 12 个,所以按 ``Profile.tags.through``(M2M 中间表)
    过滤 ``tag_id__in=我的标签`` 再按**账号 id** 分组就够,绝不按人循环查 ——
    那就是 N+1(``config/test_query_budget.py`` 会拦)。

    分组键取 ``profile__user_id`` 而不是 ``profile_id``:中间表存的是**资料主键**,
    而调用方拿的是账号 id,两者是两个序列;混用不会报错,只会静默查出空集合。

    Args:
        me: 当前用户。
        user_ids: 候选池的用户 id 序列。

    Returns:
        ``{user_id: 共同标签数}``;没有共同标签的人**不出现在字典里**,调用方用
        ``.get(user_id, 0)`` 取;我没有标签或池子为空时返回空字典。
    """
    if not user_ids:
        return {}
    through = Profile.tags.through
    # 注意:中间表的外键是 ``profile_id``(资料主键),不是账号 id ——
    # ``user_id`` 与 ``profile.id`` 是两个序列,混用会静默查出空集合。
    my_tag_ids = list(through.objects.filter(profile__user_id=me.id)
                      .values_list("tag_id", flat=True))
    if not my_tag_ids:
        return {}
    rows = (through.objects
            .filter(tag_id__in=my_tag_ids, profile__user_id__in=list(user_ids))
            .values("profile__user_id")
            .annotate(n=Count("tag_id")))
    return {row["profile__user_id"]: row["n"] for row in rows}


def daily_candidate_ids(me, preference, limit: int, today: date | None = None):
    """「今日精选」选出的用户 id(当天稳定、跨天变化)。

    排序口径:共同标签数 desc → 同城优先 → 种子随机。做法是先按种子取一个**确定的
    随机排列**,再用 ``list.sort`` 做稳定排序叠上前面两条主键 —— 这样同分的候选
    之间的先后完全由种子决定,同一天两次调用必然一模一样,换一天整体换一批。

    候选来源是 ``candidate_pool_ids``(同一套排除规则),不另写一份。

    Args:
        me: 当前用户。
        preference: 「想找的人」偏好(作为候选池的默认过滤条件)。
        limit: 要几张;调用方负责收敛到合法区间。
        today: 参照日期;``None`` 表示取 ``today_date()``(测试可注入)。

    Returns:
        ``(date, [user_id, ...])``,``date`` 是本次精选对应的日期。
    """
    day = today or today_date()
    pool_size = max(limit, int(getattr(settings, "CANDIDATE_POOL_SIZE", 200)))
    pool_ids = candidate_pool_ids(me, preference, pool_size)
    if not pool_ids:
        return day, []

    # 同城信息与共同标签数各一条查询,不随池子大小增长
    cities = dict(Profile.objects.filter(user_id__in=pool_ids).values_list("user_id", "city"))
    shared = shared_tag_counts(me, pool_ids)
    my_city = getattr(getattr(me, "profile", None), "city", "")

    shuffled = random.Random(f"{day.isoformat()}:{me.id}").sample(pool_ids, len(pool_ids))
    shuffled.sort(key=lambda user_id: (-shared.get(user_id, 0),
                                       0 if my_city and cities.get(user_id) == my_city else 1))
    return day, shuffled[:limit]


def notify_match(match):
    """配对成功后给双方各发一条 IM 灰条消息,并各写一条站内通知。

    on_commit:配对真正落库后才入队;robust=True:broker 抖动不影响配对结果。
    站内通知(批次 H)与灰条并存,不互相替代;文案不带昵称 —— 通知项里已经有
    ``actor`` 摘要,再查一次对方昵称只是多打一条 SQL。

    Args:
        match: 刚创建的配对记录,双方 id 从它上面取。
    """
    a_id, b_id = match.user_a_id, match.user_b_id
    transaction.on_commit(lambda: im_tasks.pair_add.delay(a_id, b_id), robust=True)
    transaction.on_commit(lambda: im_tasks.send_match_notice.delay(a_id, b_id), robust=True)
    for receiver_id, peer_id in ((a_id, b_id), (b_id, a_id)):
        notify_on_commit(
            receiver_id, NotificationKind.MATCH, actor_id=peer_id,
            target_kind=NotificationTarget.USER, target_id=peer_id,
            text="你们互相喜欢,配对成功,去打个招呼吧",
            dedupe_key=f"match:{match.pk}:{receiver_id}")


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