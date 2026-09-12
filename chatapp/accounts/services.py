import logging
import random

from django.conf import settings
from django.core.cache import cache

from . import sms_codes
from .exceptions import SmsCodeExpired, SmsCodeWrong, SmsLocked, SmsSendTooFrequent

logger = logging.getLogger(__name__)


def _sent_key(phone):
    return f"sms:send:{phone}"


def issue_code(phone: str) -> str:
    """生成并存储验证码;短信入队由调用方负责(见 views.sms_send)。"""
    if not cache.add(_sent_key(phone), 1, settings.SMS_RESEND_INTERVAL):
        raise SmsSendTooFrequent(wait=settings.SMS_RESEND_INTERVAL)
    code = settings.SMS_DEV_CODE if settings.SMS_DEV_MODE else f"{random.randint(0, 999999):06d}"
    sms_codes.store(phone, code)
    logger.info("[开发模式] 验证码 phone=%s code=%s", phone, code)
    return code


def rollback_send(phone: str) -> None:
    """短信任务入队失败时回滚:删占位与码,让用户能立刻重试。"""
    cache.delete(_sent_key(phone))
    sms_codes.delete(phone)


def check_code(phone: str, code: str) -> None:
    """校验验证码;成功即通过(含 60 秒重放窗口内的重复校验)。"""
    result = sms_codes.verify(phone, code)
    if result is sms_codes.CodeResult.EXPIRED:
        raise SmsCodeExpired()
    if result is sms_codes.CodeResult.WRONG:
        raise SmsCodeWrong()
    if result in (sms_codes.CodeResult.LOCKED, sms_codes.CodeResult.JUST_LOCKED):
        raise SmsLocked(wait=settings.SMS_LOCK_TTL)
