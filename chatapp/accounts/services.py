import logging
import random

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import Throttled, ValidationError

logger = logging.getLogger(__name__)


def _code_key(phone):
    return f"sms:code:{phone}"


def _sent_key(phone):
    return f"sms:sent:{phone}"


def _attempts_key(phone):
    return f"sms:attempts:{phone}"


def _lock_key(phone):
    return f"sms:lock:{phone}"


def send_code(phone: str) -> str:
    if cache.get(_sent_key(phone)):
        raise Throttled(detail="发送太频繁,请稍后再试")
    if settings.SMS_DEV_MODE:
        code = settings.SMS_DEV_CODE
    else:
        code = f"{random.randint(0, 999999):06d}"
    cache.set(_code_key(phone), code, settings.SMS_CODE_TTL)
    cache.set(_sent_key(phone), 1, settings.SMS_RESEND_INTERVAL)
    cache.delete(_attempts_key(phone))   # 重新发码 = 重置错误计数;但不清 lock,防绕过锁定
    logger.info("[开发模式] 验证码 phone=%s code=%s", phone, code)
    return code


def check_code(phone: str, code: str) -> None:
    if cache.get(_lock_key(phone)):
        raise Throttled(detail="错误次数过多,请稍后再试")
    saved = cache.get(_code_key(phone))
    if saved is None:
        raise ValidationError("验证码已过期,请重新获取")
    if saved != code:
        attempts = cache.get(_attempts_key(phone), 0) + 1
        if attempts >= settings.SMS_MAX_ATTEMPTS:
            cache.set(_lock_key(phone), 1, settings.SMS_LOCK_TTL)
            cache.delete(_code_key(phone))
            raise Throttled(detail="错误次数过多,请稍后再试")
        cache.set(_attempts_key(phone), attempts, settings.SMS_CODE_TTL)
        raise ValidationError("验证码错误")
    cache.delete(_code_key(phone))
    cache.delete(_attempts_key(phone))
