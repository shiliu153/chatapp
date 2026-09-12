"""IM 副作用任务:所有腾讯 REST 调用统一走这里,响应路径禁止直接调用。

im/client.py 的函数对外永不抛异常(失败返回 False 只记日志);
这里把 False 转成异常,让 Celery 的重试策略真正生效。
"""

import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.cache import cache

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
