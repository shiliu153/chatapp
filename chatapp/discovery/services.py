"""配对相关的领域服务。

两件事:
    1. ``likes_received_queryset`` 是「喜欢我的人」的**唯一口径**,列表与计数共用;
    2. 配对成功后给双方发 IM 灰条。之所以独立成模块而不是写在视图里,
       是为了让「配对成功」这件事的副作用只有一个入口,便于后续追加(如推送、埋点)。
"""

from django.db import transaction

from im import tasks as im_tasks
from moderation.services import blocked_user_ids
from notifications.services import enqueue_push
from users.models import Photo, PhotoStatus, ProfileStatus

from .models import Swipe, SwipeAction


def notify_match(match, actor_id=None):
    """配对成功后给双方发 IM 灰条,并给「先喜欢的一方」发推送。

    on_commit:配对真正落库后才入队;robust=True:broker 抖动不影响配对结果。

    Args:
        match: 刚创建的配对记录,双方 id 从它上面取。
        actor_id: 本次触发配对的用户 id(正在滑卡的人);``None`` 表示不推配对通知。
    """
    a_id, b_id = match.user_a_id, match.user_b_id
    transaction.on_commit(lambda: im_tasks.send_match_notice.delay(a_id, b_id), robust=True)
    if actor_id is None:
        return
    receiver_id = b_id if actor_id == a_id else a_id
    other = match.user_b if receiver_id == a_id else match.user_a
    nickname = getattr(getattr(other, "profile", None), "nickname", "") or "对方"
    enqueue_push(
        receiver_id, "match",
        title="配对成功", alert=f"你和{nickname}互相喜欢,快去打招呼吧",
        extras={"deeplink": f"/chat/{actor_id}", "type": "match"},
    )


def likes_received_queryset(me):
    """收到的喜欢:与候选池同口径,排除我已划过 / 双向拉黑 / 资料不全的人。

    Args:
        me: 当前用户。

    Returns:
        以 ``Swipe`` 为行的查询集,按喜欢时间倒序;列表与计数必须共用它。
    """
    swiped = Swipe.objects.filter(swiper=me).values("target_id")
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    return (Swipe.objects
            .filter(target=me, action=SwipeAction.LIKE)
            .exclude(swiper_id=me.id)
            .exclude(swiper_id__in=swiped)
            .exclude(swiper_id__in=blocked_user_ids(me))
            .filter(swiper__profile__status=ProfileStatus.COMPLETE)
            .filter(swiper_id__in=with_photos)
            .select_related("swiper__profile")
            .prefetch_related("swiper__photos", "swiper__profile__tags")
            .order_by("-created_at", "-id"))
