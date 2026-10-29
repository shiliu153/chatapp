"""短信后端:开发期只打日志;接入真实短信商时在这里加实现并由 settings 选择。

设计要点:
    1. 调用方只认 ``get_sms_backend().send_code(phone, code)`` 这一个入口,
       因此换成腾讯云短信等真实通道时,业务代码(``accounts/services.py``、
       ``notifications/tasks.py``)完全不需要改;
    2. **验证码只在开发模式写日志**:``SMS_DEV_MODE=0`` 时这里既不发送也不打码,
       只记一条 error(接入真实短信商前,生产不会有明文码落进日志,H-3)。
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


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


class ConsoleSmsBackend:
    """开发期后端:把验证码打进日志,不真的发短信。"""

    def send_code(self, phone: str, code: str) -> None:
        """开发模式写日志;非开发模式只报告「短信商未接入」。

        Args:
            phone: 接收手机号。
            code: 验证码明文(仅开发模式会出现在日志里)。
        """
        if not settings.SMS_DEV_MODE:
            # 走到这里说明生产没接短信商:用户收不到码,但绝不能把码写进日志
            logger.error("[短信] 未接入真实短信商(SMS_DEV_MODE=0),phone=%s 未发送",
                         _mask_phone(phone))
            return
        logger.info("[短信-控制台] phone=%s code=%s", _mask_phone(phone), code)


def get_sms_backend():
    """按配置返回短信后端实例。

    Returns:
        当前使用的后端;``SMS_DEV_MODE`` 为假时同样返回控制台实现 ——
        生产实现尚未接入,接入后改为按 ``settings.SMS_BACKEND`` 选择。
    """
    if settings.SMS_DEV_MODE:
        return ConsoleSmsBackend()
    return ConsoleSmsBackend()   # 生产实现接入后:按 settings.SMS_BACKEND 选择
