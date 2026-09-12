"""IM 副作用任务:所有腾讯 REST 调用统一走这里,响应路径禁止直接调用。

im/client.py 的函数对外永不抛异常(失败返回 False 只记日志);
这里把 False 转成异常,让 Celery 的重试策略真正生效。
"""

import logging

from celery import shared_task
from django.contrib.auth import get_user_model

from . import client as im_client

logger = logging.getLogger(__name__)

RETRY_POLICY = dict(autoretry_for=(Exception,), retry_backoff=True,
                    retry_jitter=True, max_retries=5)


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
def kick_user(user_id: int) -> None:
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return
    _require(im_client.kick_user(user.im_user_id), "kick")


@shared_task(**RETRY_POLICY)
def sync_login(user_id: int, created: bool) -> None:
    """登录后的 IM 侧整理:新号建号;老号踢掉旧 IM 会话(单设备登录)。"""
    if created:
        import_account(user_id)
    else:
        kick_user(user_id)
