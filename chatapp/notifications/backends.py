"""短信后端:开发期只打日志;生产短信商(M4 接入)在这里加实现并由 settings 选择。"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class ConsoleSmsBackend:
    def send_code(self, phone: str, code: str) -> None:
        logger.info("[短信-控制台] phone=%s code=%s", phone, code)


def get_sms_backend():
    if settings.SMS_DEV_MODE:
        return ConsoleSmsBackend()
    return ConsoleSmsBackend()   # M4:按 settings.SMS_BACKEND 选生产实现
