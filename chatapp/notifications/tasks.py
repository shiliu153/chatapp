"""通知类副作用任务:短信发送与推送。

设计要点:
    发短信 / 发推送都是跨系统调用,必须走队列 —— 响应路径不做第三方网络调用
    (见 ``docs/standards/python.md`` 所属的项目契约)。
    两类任务都套用与 IM 任务相同的重试策略(指数退避 + 抖动);
    推送任务额外按「偏好 → 设备 → 冷却」逐层短路,任一层不满足就静默返回。
"""

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from .backends import get_sms_backend
from .models import NotificationPreference, PushDevice
from .push import get_push_client


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


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=3)
def send_push(user_id: int, kind: str, title: str, alert: str, extras: dict) -> None:
    """按偏好与设备发送一条推送;任一步不满足都静默返回。

    Args:
        user_id: 接收者账号 id。
        kind: 通知类型,``like`` / ``match`` / ``system``。
        title: 通知标题。
        alert: 通知正文。
        extras: 附加数据(含 ``deeplink``)。

    Raises:
        RuntimeError: 推送通道返回失败,触发 Celery 重试。
    """
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return
    if not NotificationPreference.for_user(user).allows(kind):
        return
    registration_ids = list(
        PushDevice.objects.filter(user=user).values_list("registration_id", flat=True))
    if not registration_ids:
        return

    cooldown_key = None
    if kind == "like":
        cooldown_key = like_cooldown_key(user_id)
        if not cache.add(cooldown_key, 1, settings.PUSH_LIKE_COOLDOWN_SECONDS):
            return
    try:
        ok = get_push_client().send(registration_ids, title=title, alert=alert, extras=extras)
    except Exception:
        if cooldown_key:
            cache.delete(cooldown_key)
        raise
    if not ok:
        if cooldown_key:
            cache.delete(cooldown_key)
        raise RuntimeError("推送发送失败")
