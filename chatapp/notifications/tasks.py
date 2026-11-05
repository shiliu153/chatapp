"""通知类副作用任务:短信发送与推送。

设计要点:
    1. 发短信 / 发推送都是跨系统调用,必须走队列 —— 响应路径不做第三方网络调用
       (见 ``docs/standards/python.md`` 所属的项目契约);
    2. 两类任务都套用与 IM 任务相同的重试策略(指数退避 + 抖动);
    3. 推送任务按「通道 → 账号 → 封禁 → 偏好 → 设备 → 去重」逐层短路,
       任一层不满足就静默返回,并记一条 ``push_skipped_total{reason}`` ——
       「没推送」和「推送失败」必须能从指标上分开(2026-11-05,C-1)。
"""

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from config import metrics

from .backends import get_sms_backend
from .models import NotificationPreference, PushDevice
from .push import PROVIDER_OFF, get_push_client, provider_name

# 「没有推送」的原因;指标标签基数固定,别在这里加用户 id
PUSH_SKIP_NO_USER = "no_user"
PUSH_SKIP_BANNED = "banned"
PUSH_SKIP_PREFERENCE = "preference_off"
PUSH_SKIP_NO_DEVICE = "no_device"
PUSH_SKIP_DUPLICATE = "duplicate"
PUSH_SKIP_PROVIDER_OFF = "provider_off"

PREVIEW_MAX = 40          # 通知正文里展示的预览长度(字符)
RETRY_POLICY = dict(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True,
                    max_retries=3)


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=5)
def send_sms_code(phone: str, code: str) -> None:
    """发送验证码短信。

    Args:
        phone: 接收手机号。
        code: 验证码明文。
    """
    get_sms_backend().send_code(phone, code)


def like_cooldown_key(user_id: int) -> str:
    """「新的喜欢」推送的冷却键。

    Args:
        user_id: 接收者账号 id。

    Returns:
        Redis 缓存键。
    """
    return f"push:like:{user_id}"


def message_dedup_key(dedupe_key: str) -> str:
    """新消息推送的幂等键(按消息 id)。

    imserver 侧的重试、Django 侧的重投都可能让同一个事件到两次;
    同一条消息只该响一次。

    Args:
        dedupe_key: 由 imserver 事件带过来的消息标识(``msg_id``)。

    Returns:
        Redis 缓存键。
    """
    return f"push:msg:{dedupe_key}"


def message_payload(from_nickname: str, preview: str, from_user_id: int) -> dict:
    """构造新消息推送的标题 / 正文 / 附加数据。

    Args:
        from_nickname: 发送者昵称(可为空)。
        preview: 消息预览文本(可能是空串,如纯图片消息)。
        from_user_id: 发送者账号 id,用于点击跳转会话。

    Returns:
        ``{"title": str, "alert": str, "extras": dict}``。
    """
    title = from_nickname or "新消息"
    alert = (preview or "").strip()[:PREVIEW_MAX] or "给你发来一条消息"
    return {
        "title": title,
        "alert": alert,
        "extras": {
            "kind": "message",
            # 客户端按这个路径打开对应会话(与 App 的 go_router 路径一致)
            "deeplink": f"/home/chats/{from_user_id}",
            "peer": str(from_user_id),
        },
    }


def _active_devices(user) -> list[str]:
    """取该用户当前可投递的设备。

    Args:
        user: 接收者账号。

    Returns:
        registration_id 列表;空表示没有设备可推。
    """
    return list(PushDevice.objects.filter(user=user).values_list("registration_id",
                                                                 flat=True))


@shared_task(**RETRY_POLICY)
def send_push(user_id: int, kind: str, title: str, alert: str, extras: dict) -> None:
    """按偏好与设备发送一条「喜欢 / 配对 / 系统」推送;任一步不满足都静默返回。

    Args:
        user_id: 接收者账号 id。
        kind: 通知类型,``like`` / ``match`` / ``system``。
        title: 通知标题。
        alert: 通知正文。
        extras: 附加数据(含 ``deeplink``)。

    Raises:
        RuntimeError: 推送通道返回失败,触发 Celery 重试。
    """
    if provider_name() == PROVIDER_OFF:
        metrics.push_skipped(PUSH_SKIP_PROVIDER_OFF)
        return
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        metrics.push_skipped(PUSH_SKIP_NO_USER)
        return
    if not NotificationPreference.for_user(user).allows(kind):
        metrics.push_skipped(PUSH_SKIP_PREFERENCE)
        return
    registration_ids = _active_devices(user)
    if not registration_ids:
        metrics.push_skipped(PUSH_SKIP_NO_DEVICE)
        return

    cooldown_key = None
    if kind == "like":
        cooldown_key = like_cooldown_key(user_id)
        if not cache.add(cooldown_key, 1, settings.PUSH_LIKE_COOLDOWN_SECONDS):
            metrics.push_skipped(PUSH_SKIP_DUPLICATE)
            return
    try:
        ok = get_push_client().send(registration_ids, title=title, alert=alert, extras=extras)
    except Exception:
        if cooldown_key:
            cache.delete(cooldown_key)
        raise
    metrics.push_sent(provider_name(), ok)
    if not ok:
        if cooldown_key:
            cache.delete(cooldown_key)
        raise RuntimeError("推送发送失败")


@shared_task(**RETRY_POLICY)
def send_message_push(to_user_id: int, from_user_id: int, from_nickname: str,
                      preview: str, dedupe_key: str) -> None:
    """给「离线且收到新消息」的一侧发一条推送。

    触发方是 **imserver**(用户消息落库后、目标不在线时发内部事件过来),
    所以这里要自己再核一遍权限与偏好 —— 不能相信上游已经过滤干净。

    Args:
        to_user_id: 接收者账号 id。
        from_user_id: 发送者账号 id。
        from_nickname: 发送者昵称(用于标题)。
        preview: 消息预览(文本消息给正文,图片/语音给固定文案)。
        dedupe_key: 消息标识(同一消息只推一次)。

    Raises:
        RuntimeError: 推送通道返回失败,触发 Celery 重试。
    """
    if provider_name() == PROVIDER_OFF:
        metrics.push_skipped(PUSH_SKIP_PROVIDER_OFF)
        return
    user = get_user_model().objects.filter(id=to_user_id).first()
    if user is None:
        metrics.push_skipped(PUSH_SKIP_NO_USER)
        return
    # 封禁账号不推:重封禁全站 403、轻封禁只禁滑卡,但两者的消息都不该再打扰对方
    profile = getattr(user, "profile", None)
    if profile is not None and profile.is_banned:
        metrics.push_skipped(PUSH_SKIP_BANNED)
        return
    if not NotificationPreference.for_user(user).allows("message"):
        metrics.push_skipped(PUSH_SKIP_PREFERENCE)
        return
    registration_ids = _active_devices(user)
    if not registration_ids:
        metrics.push_skipped(PUSH_SKIP_NO_DEVICE)
        return

    key = message_dedup_key(dedupe_key)
    if not cache.add(key, 1, settings.PUSH_DEDUP_TTL):
        metrics.push_skipped(PUSH_SKIP_DUPLICATE)
        return
    payload = message_payload(from_nickname, preview, from_user_id)
    try:
        ok = get_push_client().send(registration_ids, **payload)
    except Exception:
        cache.delete(key)   # 交给重试,别让「这次失败」占掉幂等位
        raise
    metrics.push_sent(provider_name(), ok)
    if not ok:
        cache.delete(key)
        raise RuntimeError("推送发送失败")
