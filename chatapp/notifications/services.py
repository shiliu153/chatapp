"""推送的业务入口:把「发一条推送」收敛成两个函数。

设计要点:
    业务事件都调 ``enqueue_push``(喜欢 / 配对 / 系统)或 ``enqueue_message_push``
    (imserver 转发过来的离线新消息),由它们统一入队;业务代码不需要知道
    Celery、偏好与设备的存在。

    ``enqueue_message_push`` 故意**不用** ``transaction.on_commit``:它的调用方是
    imserver 的内部事件,那条消息在 imserver 侧已经提交完才发事件;Django 这一侧
    再挂一层 on_commit 会让「有事务 / 没事务」两种调用走不同时机,反而难查。
    要幂等,靠的是任务里按 msg_id 去重。
"""

from django.db import transaction

from .tasks import send_message_push, send_push


def enqueue_push(user_id: int, kind: str, *, title: str, alert: str, extras: dict) -> None:
    """事务提交后入队一条推送。

    Args:
        user_id: 接收者账号 id。
        kind: 通知类型,``like`` / ``match`` / ``system``。
        title: 通知标题。
        alert: 通知正文。
        extras: 附加数据;``deeplink`` 是点击后要打开的 App 路径。
    """
    transaction.on_commit(
        lambda: send_push.delay(user_id, kind, title, alert, extras), robust=True)


def enqueue_message_push(to_user_id: int, from_user_id: int, from_nickname: str,
                         preview: str, dedupe_key: str) -> None:
    """入队一条「离线新消息」推送。

    Args:
        to_user_id: 接收者账号 id。
        from_user_id: 发送者账号 id。
        from_nickname: 发送者昵称。
        preview: 消息预览文本。
        dedupe_key: 消息标识(``msg_id``),用于幂等。
    """
    send_message_push.delay(to_user_id, from_user_id, from_nickname, preview, dedupe_key)
