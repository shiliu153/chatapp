import logging

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from im import tasks as im_tasks

from . import presence
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
    """注销账号:删除该用户的全部数据,并清理磁盘文件 / 缓存 / IM 账号。

    顺序有讲究:
      1. 事务内先**收集**待删文件路径与 im_user_id(删行之后就取不到了,
         且 `user.delete()` 会把实例主键置为 None);
      2. 事务内删 User 行(CASCADE 清掉全部关联数据);
      3. 事务提交后(on_commit)删磁盘文件、清 Redis、入队 IM 删号 ——
         响应路径禁止外部调用,且入队必须晚于提交(否则事务回滚了 IM 号却没了)。
    """
    from feed.models import PostImage   # 延迟导入,避免 app 加载顺序问题(同 im/tasks.py)

    file_names = list(user.photos.values_list("file", flat=True))
    file_names += list(PostImage.objects.filter(post__author=user).values_list("file", flat=True))
    user_id = user.id
    im_user_id = user.im_user_id

    user.delete()

    def _cleanup():
        for name in file_names:
            try:
                default_storage.delete(name)
            except Exception:
                logger.warning("注销删文件失败 name=%s", name, exc_info=True)
        presence.clear(user_id)
        cache.delete(im_tasks.kick_pending_key(user_id))
        im_tasks.delete_account.delay(im_user_id)

    transaction.on_commit(_cleanup, robust=True)
