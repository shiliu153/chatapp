from celery import shared_task

from .backends import get_sms_backend


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=5)
def send_sms_code(phone: str, code: str) -> None:
    get_sms_backend().send_code(phone, code)
