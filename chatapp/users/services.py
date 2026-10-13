import logging

from django.db import transaction
from django.utils import timezone

from im import tasks as im_tasks

from .models import PhotoStatus, Preference, Profile

logger = logging.getLogger(__name__)


def get_profile(user):
    """取当前用户资料;没有就建空 Profile + 空 Preference(资料是懒创建的)。"""
    profile, _ = Profile.objects.get_or_create(user=user)
    Preference.objects.get_or_create(profile=profile)
    return profile


def review_photos(queryset, status, operator=None) -> int:
    """通过/驳回照片:落审核审计 + 重算资料完善状态;过审时把头像同步到 IM。admin 与 ops 共用。"""
    user_ids = set(queryset.values_list("user_id", flat=True))
    count = queryset.update(status=status, reviewed_by=operator, reviewed_at=timezone.now())
    # 照片数量变化会影响「资料完善」判定(掉回未完善 = 失去候选资格),必须重算
    for profile in Profile.objects.filter(user_id__in=user_ids):
        profile.refresh_status()
    if status == PhotoStatus.APPROVED:
        for user_id in user_ids:
            sync_im_avatar(user_id)
    return count


def sync_im_nickname(user) -> None:
    """昵称变更后同步到 IM 资料(经任务队列;失败可重试,不影响业务)。"""
    nickname = getattr(getattr(user, "profile", None), "nickname", "")
    if not nickname:
        return
    transaction.on_commit(lambda: im_tasks.sync_profile.delay(user.id, "nick"), robust=True)


def sync_im_avatar(user_id: int) -> None:
    """照片过审后把头像同步到 IM(任务内部取第一张过审照片的绝对 URL)。"""
    transaction.on_commit(lambda: im_tasks.sync_profile.delay(user_id, "avatar"), robust=True)


def delete_account(user) -> None:
    """注销账号:删除该用户的全部数据。

    本函数只负责数据层(事务内);磁盘文件 / Redis / IM 删号等副作用
    由后续任务补在 `transaction.on_commit` 里。

    ⚠️ 调用前必须取好 `user.id` / `user.im_user_id` —— `user.delete()` 之后
    Django 会把实例的主键置为 None(见 users/tests.py 的回归用例)。
    """
    user.delete()
