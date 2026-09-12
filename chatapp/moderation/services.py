import logging

from django.db import transaction

from im import tasks as im_tasks
from users.models import Profile, ProfileStatus

from .models import BanAction, BanLog, Block

logger = logging.getLogger(__name__)


def blocked_user_ids(user) -> set[int]:
    """与我有拉黑关系的人(我拉黑的 ∪ 拉黑我的);候选/配对/资料卡统一用它。"""
    made = Block.objects.filter(blocker=user).values_list("blocked_id", flat=True)
    received = Block.objects.filter(blocked=user).values_list("blocker_id", flat=True)
    return set(made) | set(received)


def log_ban_change(user, old_status, new_status, reason, operator) -> None:
    """admin 保存 Profile / ops 封禁时调用:状态跨封禁边界就写审计 + 发系统通知。

    通知与踢下线经任务队列(ban_notice 任务内保证 heavy 先发后踢);响应路径不等腾讯。
    """
    if new_status == old_status:
        return
    if new_status == ProfileStatus.BANNED_LIGHT:
        _write_log(user, BanAction.BAN_LIGHT, reason, operator)
        _enqueue(im_tasks.ban_notice, user.id, "light", reason or "")
    elif new_status == ProfileStatus.BANNED_HEAVY:
        _write_log(user, BanAction.BAN_HEAVY, reason, operator)
        _enqueue(im_tasks.ban_notice, user.id, "heavy", reason or "")
    elif old_status in Profile.BANNED_STATUSES:
        _write_log(user, BanAction.UNBAN, reason, operator)
        _enqueue(im_tasks.ban_lifted, user.id)


def sync_im_blacklist(blocker, blocked, *, add: bool) -> None:
    """拉黑/解除后同步 IM 黑名单(经任务队列;UI 侧还有双向不可见兜底)。"""
    task = im_tasks.blacklist_add if add else im_tasks.blacklist_remove
    _enqueue(task, blocker.id, blocked.id)


def _write_log(user, action, reason, operator) -> None:
    try:
        BanLog.objects.create(user=user, action=action, reason=reason or "", operator=operator)
    except Exception:
        # 审计写失败不该炸掉运营的保存动作(Profile 已经保存过了)
        logger.exception("写 BanLog 失败 user=%s action=%s", user.pk, action)


def _enqueue(task, *args) -> None:
    """入队统一走 on_commit(robust=True):在事务里等提交,不在事务里立即入队(很快)。"""
    transaction.on_commit(lambda: task.delay(*args), robust=True)
