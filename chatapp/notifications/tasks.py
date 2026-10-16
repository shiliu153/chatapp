"""通知类副作用任务:短信发送。

设计要点:
    发短信是跨系统调用,必须走队列 —— 响应路径不做第三方网络调用
    (见 ``docs/standards/python.md`` 所属的项目契约)。
    这里套用与 IM 任务相同的重试策略(指数退避 + 抖动,最多 5 次)。
"""

from celery import shared_task

from .backends import get_sms_backend


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=5)
def send_sms_code(phone: str, code: str) -> None:
    """发送验证码短信。

    Args:
        phone: 接收手机号。
        code: 验证码明文。
    """
    get_sms_backend().send_code(phone, code)
