"""合规领域服务:拉黑关系查询、封禁审计与 IM 副作用入队。

设计要点:
    1. ``blocked_user_ids`` 返回**双向并集**(我拉黑的 ∪ 拉黑我的),是候选池、
       配对列表、他人资料卡、在线状态查询共用的唯一可见性口径;
    2. 封禁状态跨越边界时才写审计并发通知(``new_status != old_status``),
       重复保存同一个状态不会产生重复通知;
    3. 所有 IM 副作用统一经 ``_enqueue`` 走 ``transaction.on_commit`` ——
       响应路径不等腾讯,且入队必须晚于事务提交。
"""

import logging

from django.db import transaction

from im import tasks as im_tasks
from users.models import Profile, ProfileStatus

from .models import BanAction, BanLog, Block

logger = logging.getLogger(__name__)


def blocked_user_ids(user) -> set[int]:
    """与我有拉黑关系的人(我拉黑的 ∪ 拉黑我的);候选/配对/资料卡统一用它。

    Args:
        user: 当前用户。

    Returns:
        对方用户 id 的集合(双向并集)。
    """
    made = Block.objects.filter(blocker=user).values_list("blocked_id", flat=True)
    received = Block.objects.filter(blocked=user).values_list("blocker_id", flat=True)
    return set(made) | set(received)


def log_ban_change(user, old_status, new_status, reason, operator) -> None:
    """admin 保存 Profile / ops 封禁时调用:状态跨封禁边界就写审计 + 发系统通知。

    通知与踢下线经任务队列(ban_notice 任务内保证 heavy 先发后踢);响应路径不等腾讯。

    Args:
        user: 状态被修改的用户。
        old_status: 修改前的资料状态。
        new_status: 修改后的资料状态。
        reason: 封禁/解封原因,可为空。
        operator: 执行操作的运营账号,可为 ``None``。
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
    """拉黑/解除后同步 IM 黑名单(经任务队列;UI 侧还有双向不可见兜底)。

    Args:
        blocker: 拉黑发起方。
        blocked: 被拉黑方。
        add: ``True`` 表示加入黑名单,``False`` 表示移除。
    """
    task = im_tasks.blacklist_add if add else im_tasks.blacklist_remove
    _enqueue(task, blocker.id, blocked.id)


def notify_report_handled(report) -> None:
    """举报首次标记「已处理」时调用:给举报者发系统通知(经任务队列)。

    只在处理状态从 pending 变为 handled 的那一刻调用;重复处理不要再调,
    否则举报者会收到多条同样的通知。

    Args:
        report: 刚被标记为已处理的举报记录。
    """
    _enqueue(im_tasks.report_handled, report.reporter_id)


def _write_log(user, action, reason, operator) -> None:
    """写一条封禁审计;失败只记日志,不向上抛。

    审计写失败不该炸掉运营的保存动作 —— 此时 ``Profile`` 已经保存成功了。

    Args:
        user: 被封禁/解封的用户。
        action: ``BanAction`` 取值。
        reason: 原因文本,可为空。
        operator: 执行操作的运营账号,可为 ``None``。
    """
    try:
        BanLog.objects.create(user=user, action=action, reason=reason or "", operator=operator)
    except Exception:
        # 审计写失败不该炸掉运营的保存动作(Profile 已经保存过了)
        logger.exception("写 BanLog 失败 user=%s action=%s", user.pk, action)


def _enqueue(task, *args) -> None:
    """入队统一走 on_commit(robust=True):在事务里等提交,不在事务里立即入队(很快)。"""
    transaction.on_commit(lambda: task.delay(*args), robust=True)
