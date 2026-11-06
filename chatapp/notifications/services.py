"""通知的业务入口:推送入队 + 站内通知落库。

设计要点:
    业务事件都调 ``enqueue_push``(喜欢 / 配对 / 系统)或 ``enqueue_message_push``
    (imserver 转发过来的离线新消息),由它们统一入队;业务代码不需要知道
    Celery、偏好与设备的存在。

    ``enqueue_message_push`` 故意**不用** ``transaction.on_commit``:它的调用方是
    imserver 的内部事件,那条消息在 imserver 侧已经提交完才发事件;Django 这一侧
    再挂一层 on_commit 会让「有事务 / 没事务」两种调用走不同时机,反而难查。
    要幂等,靠的是任务里按 msg_id 去重。

    站内通知(批次 H)走 ``notify`` / ``notify_on_commit`` 两个入口:
        - ``notify`` 是同步写库的纯函数(偏好过滤 + 幂等),给测试与管理命令用;
        - ``notify_on_commit`` 是业务事件的**唯一**调用方式:它把写库挂到
          ``transaction.on_commit(..., robust=True)`` 上,DB 没提交就不写,
          写失败只记日志、绝不影响主流程(与 IM 灰条同一口径)。
    通知是**站内**数据,不是跨系统副作用,所以不走 Celery。
"""

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import InAppNotification, NotificationKind, NotificationPreference, NotificationTarget
from .tasks import send_message_push, send_push

# 事件类型 → 通知偏好开关(``NotificationPreference.allows`` 的入参)。
# 动态互动三类共用一个开关:用户关心的是「要不要被动态互动打扰」,不是具体哪一类。
PREFERENCE_BY_KIND = {
    NotificationKind.POST_LIKE: "social",
    NotificationKind.POST_COMMENT: "social",
    NotificationKind.COMMENT_REPLY: "social",
    NotificationKind.MATCH: "match",
    NotificationKind.REPORT_HANDLED: "system",
    NotificationKind.SYSTEM: "system",
}


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


def display_name(user) -> str:
    """取用户对外显示的昵称(文案里用)。

    Args:
        user: 目标用户。

    Returns:
        资料里的昵称;未填资料时回落为 ``u{id}``(与 IM 灰条同一口径)。
    """
    profile = getattr(user, "profile", None)
    return (profile.nickname if profile else "") or f"u{user.id}"


def notify(user, kind: str, *, actor=None, target_kind: str = NotificationTarget.NONE,
           target_id: int | None = None, text: str = "",
           dedupe_key: str | None = None):
    """写一条站内通知(偏好过滤 + 幂等)。

    调用方负责把它放进 ``transaction.on_commit``;业务代码请用
    :func:`notify_on_commit`,不要直接调本函数。

    Args:
        user: 接收者(``User`` 实例)。
        kind: ``NotificationKind`` 取值。
        actor: 触发这条通知的人(``User`` 实例);系统消息可为 ``None``。
        target_kind: 点击跳转的目标类型,``post`` / ``user`` / ``none``。
        target_id: 目标主键;``target_kind=none`` 时为 ``None``。
        text: 服务端生成的通知正文,超过 200 字截断。
        dedupe_key: 去重键;同一个键只会留一条通知(重复点赞、重复处理举报)。

    Returns:
        落库的 ``InAppNotification``;偏好关闭时返回 ``None``(不落库)。
    """
    preference_key = PREFERENCE_BY_KIND.get(kind)
    if preference_key is None:
        return None
    if not NotificationPreference.for_user(user).allows(preference_key):
        return None
    fields = {
        "user": user,
        "kind": kind,
        "actor": actor,
        "target_kind": target_kind,
        "target_id": target_id,
        "text": (text or "")[:200],
    }
    if dedupe_key:
        notification, _ = InAppNotification.objects.get_or_create(
            dedupe_key=dedupe_key, defaults=fields)
        return notification
    return InAppNotification.objects.create(**fields)


def notify_on_commit(user_id: int, kind: str, *, actor_id: int | None = None,
                     target_kind: str = NotificationTarget.NONE,
                     target_id: int | None = None, text: str = "",
                     dedupe_key: str | None = None) -> None:
    """事务提交后写一条站内通知(业务事件统一入口)。

    为什么传 id 而不是实例:回调在事务提交后才执行,期间账号可能已被注销;
    回调里按 id 现查,查不到就安静跳过,不会拿一个悬空实例去写外键。

    Args:
        user_id: 接收者账号 id。
        kind: ``NotificationKind`` 取值。
        actor_id: 触发者账号 id;系统消息可为 ``None``。
        target_kind: 点击跳转的目标类型,``post`` / ``user`` / ``none``。
        target_id: 目标主键。
        text: 服务端生成的通知正文。
        dedupe_key: 去重键。
    """
    transaction.on_commit(
        lambda: _deliver(user_id, kind, actor_id, target_kind, target_id, text, dedupe_key),
        robust=True)


def _deliver(user_id: int, kind: str, actor_id: int | None, target_kind: str,
             target_id: int | None, text: str, dedupe_key: str | None) -> None:
    """``notify_on_commit`` 的回调体:按 id 取实例后调用 :func:`notify`。

    Args:
        user_id: 接收者账号 id。
        kind: ``NotificationKind`` 取值。
        actor_id: 触发者账号 id。
        target_kind: 目标类型。
        target_id: 目标主键。
        text: 通知正文。
        dedupe_key: 去重键。
    """
    user_model = get_user_model()
    user = user_model.objects.filter(pk=user_id).first()
    if user is None:
        return
    actor = user_model.objects.filter(pk=actor_id).first() if actor_id else None
    notify(user, kind, actor=actor, target_kind=target_kind, target_id=target_id,
           text=text, dedupe_key=dedupe_key)
