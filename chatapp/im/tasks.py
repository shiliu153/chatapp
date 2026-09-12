"""IM 副作用任务:所有腾讯 REST 调用统一走这里,响应路径禁止直接调用。

im/client.py 的函数对外永不抛异常(失败返回 False 只记日志);
这里把 False 转成异常,让 Celery 的重试策略真正生效。
"""

import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from users.models import PhotoStatus

from . import client as im_client

logger = logging.getLogger(__name__)

RETRY_POLICY = dict(autoretry_for=(Exception,), retry_backoff=True,
                    retry_jitter=True, max_retries=5)

KICK_PENDING_TTL = 300        # 「待踢旧会话」标记有效期(秒)
KICK_BACKSTOP_DELAY = 20      # 兜底任务延迟(秒):App 一直不拉签名时才补踢


def kick_pending_key(user_id: int) -> str:
    return f"im:kick_pending:{user_id}"


def _require(ok: bool, what: str) -> None:
    if not ok:
        raise RuntimeError(f"IM {what} 失败")


def _user(user_id: int):
    return get_user_model().objects.filter(id=user_id).first()


@shared_task(**RETRY_POLICY)
def send_match_notice(user_a_id: int, user_b_id: int) -> None:
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    _require(im_client.send_match_notice(a.im_user_id, b.im_user_id), "send_match_notice")


@shared_task(**RETRY_POLICY)
def blacklist_add(owner_id: int, other_id: int) -> None:
    owner, other = _user(owner_id), _user(other_id)
    if owner is None or other is None:
        return
    _require(im_client.black_list_add(owner.im_user_id, other.im_user_id), "black_list_add")


@shared_task(**RETRY_POLICY)
def blacklist_remove(owner_id: int, other_id: int) -> None:
    owner, other = _user(owner_id), _user(other_id)
    if owner is None or other is None:
        return
    _require(im_client.black_list_delete(owner.im_user_id, other.im_user_id), "black_list_delete")


@shared_task(**RETRY_POLICY)
def ban_notice(user_id: int, level: str, reason: str = "") -> None:
    """封禁说明;heavy 先发消息再踢下线(同一任务内串行,顺序不被多 worker 打乱)。"""
    user = _user(user_id)
    if user is None:
        return
    sent = im_client.send_ban_notice(user.im_user_id, level, reason)
    kicked = True
    if level == "heavy":
        kicked = im_client.kick_user(user.im_user_id)
    _require(sent and kicked, "ban_notice")


@shared_task(**RETRY_POLICY)
def ban_lifted(user_id: int) -> None:
    user = _user(user_id)
    if user is None:
        return
    _require(im_client.send_ban_lifted(user.im_user_id), "ban_lifted")


@shared_task(**RETRY_POLICY)
def report_handled(reporter_id: int) -> None:
    """举报处理完成:告知举报者(收件人是举报者,不是被举报人)。"""
    user = _user(reporter_id)
    if user is None:
        return
    _require(im_client.send_report_handled(user.im_user_id), "report_handled")


@shared_task(**RETRY_POLICY)
def sync_profile(user_id: int, kind: str) -> None:
    """把资料同步到 IM(kind: nick|avatar);没有可同步的值时静默跳过。"""
    user = _user(user_id)
    if user is None:
        return
    profile = getattr(user, "profile", None)
    if profile is None:
        return
    if kind == "nick":
        if not profile.nickname:
            return
        _require(im_client.set_profile_nick(user.im_user_id, profile.nickname), "sync_profile:nick")
    elif kind == "avatar":
        photo = user.photos.filter(status=PhotoStatus.APPROVED).first()
        if photo is None:
            return
        url = f"{settings.MEDIA_BASE_URL.rstrip('/')}{photo.file.url}"
        _require(im_client.set_profile_avatar(user.im_user_id, url), "sync_profile:avatar")
    else:
        raise ValueError(f"未知的资料同步类型 kind={kind}")


@shared_task(**RETRY_POLICY)
def import_account(user_id: int) -> None:
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return
    _require(im_client.import_account(user.im_user_id), "account_import")


@shared_task(**RETRY_POLICY)
def kick_pending(user_id: int) -> None:
    """兜底:登录后 App 没来拉签名(标记仍在)时,补踢一次旧 IM 会话。

    正常路径由 im/views.user_sig 在签发签名前同步踢掉并清标记(顺序保证
    踢的永远是新会话建立之前的旧会话);本任务只覆盖「App 压根没登 IM」的情况。
    """
    key = kick_pending_key(user_id)
    if not cache.get(key):
        return
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        cache.delete(key)
        return
    if im_client.kick_user(user.im_user_id):
        cache.delete(key)
    else:
        raise RuntimeError("IM kick 失败")
