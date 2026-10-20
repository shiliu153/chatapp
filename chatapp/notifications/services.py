"""推送的业务入口:把「发一条推送」收敛成一个函数。

设计要点:
    所有业务事件都调 ``enqueue_push``,由它统一 ``on_commit`` 入队;
    业务代码不需要知道 Celery、偏好与设备的存在。
"""

from django.db import transaction

from .tasks import send_push


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
