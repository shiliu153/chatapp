"""短信后端:开发期只打日志;接入真实短信商时在这里加实现并由 settings 选择。

设计要点:
    调用方只认 ``get_sms_backend().send_code(phone, code)`` 这一个入口,
    因此换成腾讯云短信等真实通道时,业务代码(``accounts/services.py``、
    ``notifications/tasks.py``)完全不需要改。
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class ConsoleSmsBackend:
    """开发期后端:把验证码打进日志,不真的发短信。"""

    def send_code(self, phone: str, code: str) -> None:
        """把验证码写进日志。

        Args:
            phone: 接收手机号。
            code: 验证码明文。
        """
        logger.info("[短信-控制台] phone=%s code=%s", phone, code)


def get_sms_backend():
    """按配置返回短信后端实例。

    Returns:
        当前使用的后端;``SMS_DEV_MODE`` 为假时同样返回控制台实现 ——
        生产实现尚未接入,接入后改为按 ``settings.SMS_BACKEND`` 选择。
    """
    if settings.SMS_DEV_MODE:
        return ConsoleSmsBackend()
    return ConsoleSmsBackend()   # 生产实现接入后:按 settings.SMS_BACKEND 选择
