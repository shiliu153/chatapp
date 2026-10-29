"""短信验证码的生成、限流与校验。

验证码本身存在 Redis(见 ``sms_codes``);真实短信发送由调用方入队 Celery
任务完成,响应路径不做任何第三方网络调用。

关联文档:
    - 接口契约:docs/api/auth.md
"""

import logging
import secrets

from django.conf import settings
from django.core.cache import cache

from . import sms_codes
from .exceptions import SmsCodeExpired, SmsCodeWrong, SmsLocked, SmsSendTooFrequent

logger = logging.getLogger(__name__)


def _sent_key(phone):
    """拼出该手机号最近一次发送的限流键。"""
    return f"sms:send:{phone}"


def _mask_phone(phone: str) -> str:
    """把手机号脱敏成 ``138****8000``,日志里不再出现完整号码。

    Args:
        phone: 原始手机号。

    Returns:
        脱敏后的手机号;长度不足时原样返回。
    """
    if len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


def issue_code(phone: str) -> str:
    """生成并存储验证码。

    短信入队由调用方负责(见 ``views.sms_send``);本函数只负责限流、
    生成、落库三步。验证码用 ``secrets`` 生成(CSPRNG);只有开发模式才把
    验证码写进日志 —— 接入真实短信商后日志里不能再出现明文码(H-3)。

    Args:
        phone: 手机号,同时作为发送间隔限流的键。

    Returns:
        本次生成的 6 位验证码;开发模式下固定为 ``settings.SMS_DEV_CODE``。

    Raises:
        SmsSendTooFrequent: 距上次发送不足 ``SMS_RESEND_INTERVAL`` 秒。
    """
    if not cache.add(_sent_key(phone), 1, settings.SMS_RESEND_INTERVAL):
        raise SmsSendTooFrequent(wait=settings.SMS_RESEND_INTERVAL)
    code = (settings.SMS_DEV_CODE if settings.SMS_DEV_MODE
            else f"{secrets.randbelow(1_000_000):06d}")
    sms_codes.store(phone, code)
    if settings.SMS_DEV_MODE:
        logger.info("[开发模式] 验证码 phone=%s code=%s", _mask_phone(phone), code)
    return code


def rollback_send(phone: str) -> None:
    """短信任务入队失败时回滚。

    删掉限流占位与验证码,让用户能立刻重试(见 ``views.sms_send`` 的异常分支)。

    Args:
        phone: 手机号。
    """
    cache.delete(_sent_key(phone))
    sms_codes.delete(phone)


def check_code(phone: str, code: str) -> None:
    """校验验证码,成功即通过。

    含 60 秒重放窗口内的重复校验:窗口内重复提交同一个码仍算成功。

    Args:
        phone: 手机号。
        code: 用户提交的 6 位验证码。

    Raises:
        SmsCodeExpired: 验证码已过期或不存在。
        SmsCodeWrong: 验证码错误。
        SmsLocked: 连错次数超限,账号被临时锁定。
    """
    result = sms_codes.verify(phone, code)
    if result is sms_codes.CodeResult.EXPIRED:
        raise SmsCodeExpired()
    if result is sms_codes.CodeResult.WRONG:
        raise SmsCodeWrong()
    if result in (sms_codes.CodeResult.LOCKED, sms_codes.CodeResult.JUST_LOCKED):
        raise SmsLocked(wait=settings.SMS_LOCK_TTL)
