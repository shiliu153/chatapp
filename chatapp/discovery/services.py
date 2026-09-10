import logging
import threading

from django.db import transaction

from im import client as im_client

logger = logging.getLogger(__name__)


def notify_match(match):
    """配对成功后给双方各发一条 IM 灰条消息。

    用 on_commit:消息只在配对真正落库后才发;发送失败只记日志,不影响配对结果。
    """
    a_id, b_id = match.user_a.im_user_id, match.user_b.im_user_id
    transaction.on_commit(lambda: _notify_async(a_id, b_id))


def _notify_async(a_id: str, b_id: str) -> None:
    """灰条丢到后台线程发:配对响应不能等腾讯 REST 往返。

    2026-09-10 手测实测:同步发两条各 ~0.45s,「配对成功」弹窗被拖慢近 1 秒;
    发送失败仍由 im_client 内部吞掉只记日志。
    """
    threading.Thread(
        target=im_client.send_match_notice, args=(a_id, b_id), daemon=True
    ).start()
