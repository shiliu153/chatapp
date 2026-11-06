"""合规领域服务:拉黑关系查询、封禁审计与 IM 副作用入队。

设计要点:
    1. ``blocked_user_ids`` 返回**双向并集**(我拉黑的 ∪ 拉黑我的),是候选池、
       配对列表、他人资料卡、在线状态查询共用的唯一可见性口径;
    2. 封禁状态跨越边界时才写审计并发通知(``new_status != old_status``),
       重复保存同一个状态不会产生重复通知;
    3. 所有 IM 副作用统一经 ``_enqueue`` 走 ``transaction.on_commit`` ——
       响应路径不等 IM,且入队必须晚于事务提交。
"""

import logging

from django.db import transaction
from django.db.models import Exists, OuterRef

from discovery.cache_keys import invalidate_pool_globally
from im import tasks as im_tasks
from notifications.models import NotificationKind, NotificationTarget
from notifications.services import notify_on_commit
from users.models import Profile, ProfileStatus

from .models import BanAction, BanLog, Block

logger = logging.getLogger(__name__)


def exclude_blocked(queryset, user, outer_field: str):
    """在查询集上排除「与我双向拉黑」的人,返回新的查询集。

    与 :func:`blocked_user_ids` 同一口径(我拉黑的 ∪ 拉黑我的),区别只在**执行方式**:
    ``blocked_user_ids`` 把 id 全拉进 Python 再用 ``__in``,活跃用户一多,
    SQL 里就会出现几千个占位符的 ``NOT IN (...)``,还多打两条查询(审查 N-4/N-5)。
    列表类查询请用本函数,让数据库做反连接。

    两个实现细节,改之前先看:

    1. **必须拆成两次 ``exclude``**:``exclude(a, b)`` 在 Django 里是
       ``NOT (a AND b)``,只有「双向都拉黑」的行才会被剔除 —— 单方向拉黑会漏掉;
    2. **不能合并成一条带 ``OR`` 的 ``EXISTS``**:MySQL 对 OR 形式的 EXISTS 用不了
       半连接,会退化成「把外层行全部物化进临时表」——2026-11-03 在 2 万访客上实测
       565ms,拆成两条只要 103ms(与完全不加拉黑过滤同价)。

    Args:
        queryset: 外层查询集(``Profile`` / ``Swipe`` / ``ProfileVisit`` / ``Match``)。
        user: 当前用户。
        outer_field: 外层查询集里指向「对方用户 id」的字段名
            (``user_id`` / ``swiper_id`` / ``viewer_id`` / ``user_a_id`` / ``user_b_id``)。

    Returns:
        追加了两次 ``NOT EXISTS`` 的查询集。
    """
    for condition in (
            Exists(Block.objects.filter(blocker=user, blocked_id=OuterRef(outer_field))),
            Exists(Block.objects.filter(blocked=user, blocker_id=OuterRef(outer_field))),
    ):
        queryset = queryset.exclude(condition)
    return queryset


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

    通知与踢下线经任务队列(ban_notice 任务内保证 heavy 先发后踢);响应路径不等 IM。

    Args:
        user: 状态被修改的用户。
        old_status: 修改前的资料状态。
        new_status: 修改后的资料状态。
        reason: 封禁/解封原因,可为空。
        operator: 执行操作的运营账号,可为 ``None``。
    """
    if new_status == old_status:
        return
    # 封禁/解封改变「谁有资格出现在候选池」,全站候选缓存必须失效。
    invalidate_pool_globally()
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


def sync_im_pair(user_a_id: int, user_b_id: int, *, add: bool) -> None:
    """同步聊天权限:配对创建时 add,解除配对/拉黑时 remove(H4)。

    Args:
        user_a_id: 一方账号 id。
        user_b_id: 另一方账号 id。
        add: ``True`` 建立权限,``False`` 移除权限。
    """
    task = im_tasks.pair_add if add else im_tasks.pair_remove
    _enqueue(task, user_a_id, user_b_id)


def notify_report_handled(report) -> None:
    """举报首次标记「已处理」时调用:给举报者发系统通知(灰条 + 站内通知)。

    只在处理状态从 pending 变为 handled 的那一刻调用;重复处理不要再调,
    否则举报者会收到多条同样的通知。站内通知(批次 H)与灰条并存,用
    ``dedupe_key`` 兜住「重复处理」这类误调。

    Args:
        report: 刚被标记为已处理的举报记录。
    """
    _enqueue(im_tasks.report_handled, report.reporter_id)
    notify_on_commit(
        report.reporter_id, NotificationKind.REPORT_HANDLED,
        target_kind=NotificationTarget.NONE,
        text="你的举报已处理,感谢你的反馈",
        dedupe_key=f"report:{report.pk}")


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
