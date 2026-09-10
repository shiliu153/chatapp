import logging

from django.db import transaction

from im import client as im_client

logger = logging.getLogger(__name__)


def notify_match(match):
    """配对成功后给双方各发一条 IM 灰条消息。

    用 on_commit:消息只在配对真正落库后才发;发送失败只记日志,不影响配对结果。
    """
    a_id, b_id = match.user_a.im_user_id, match.user_b.im_user_id
    transaction.on_commit(lambda: im_client.send_match_notice(a_id, b_id))
