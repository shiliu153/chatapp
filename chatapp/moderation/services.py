import logging
import threading

from im import client as im_client
from users.models import Profile, ProfileStatus

from .models import BanAction, BanLog, Block

logger = logging.getLogger(__name__)


def blocked_user_ids(user) -> set[int]:
    """与我有拉黑关系的人(我拉黑的 ∪ 拉黑我的);候选/配对/资料卡统一用它。"""
    made = Block.objects.filter(blocker=user).values_list("blocked_id", flat=True)
    received = Block.objects.filter(blocked=user).values_list("blocker_id", flat=True)
    return set(made) | set(received)


def log_ban_change(user, old_status, new_status, reason, operator) -> None:
    """admin 保存 Profile 时调用:状态跨封禁边界就写审计 + 发系统通知;重封禁顺带踢下线。"""
    if new_status == old_status:
        return
    identifier = user.im_user_id
    if new_status == ProfileStatus.BANNED_LIGHT:
        _write_log(user, BanAction.BAN_LIGHT, reason, operator)
        _dispatch_async(im_client.send_ban_notice, identifier, "light", reason or "")
    elif new_status == ProfileStatus.BANNED_HEAVY:
        _write_log(user, BanAction.BAN_HEAVY, reason, operator)
        _dispatch_async(_send_notice_then_kick, identifier, reason or "")
    elif old_status in Profile.BANNED_STATUSES:
        _write_log(user, BanAction.UNBAN, reason, operator)
        _dispatch_async(im_client.send_ban_lifted, identifier)


def _send_notice_then_kick(identifier, reason) -> None:
    """重封禁:先把封禁说明送达,再踢下线(同一线程保证顺序)。"""
    im_client.send_ban_notice(identifier, "heavy", reason)
    im_client.kick_user(identifier)


def sync_im_blacklist(blocker, blocked, *, add: bool) -> None:
    """拉黑/解除后同步 IM 黑名单(后台线程,失败只记日志;UI 侧还有双向不可见兜底)。"""
    fn = im_client.black_list_add if add else im_client.black_list_delete
    _dispatch_async(fn, blocker.im_user_id, blocked.im_user_id)


def _write_log(user, action, reason, operator) -> None:
    try:
        BanLog.objects.create(user=user, action=action, reason=reason or "", operator=operator)
    except Exception:
        # 审计写失败不该炸掉运营的保存动作(Profile 已经保存过了)
        logger.exception("写 BanLog 失败 user=%s action=%s", user.pk, action)


def _dispatch_async(fn, *args) -> None:
    """IM 调用一律丢后台线程:接口响应不等腾讯 REST(同配对灰条 _notify_async 模式)。"""
    threading.Thread(target=fn, args=args, daemon=True).start()
