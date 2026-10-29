"""通知应用的测试:覆盖短信后端与发送任务。

覆盖场景:
    - 控制台后端把验证码写进日志;
    - 发送任务把调用透传给后端(不真的发短信)。
"""

from unittest.mock import patch

from django.test import TestCase, override_settings

from notifications.backends import ConsoleSmsBackend
from notifications.tasks import send_sms_code


class SmsBackendTests(TestCase):
    """短信后端:开发期控制台实现的行为。"""

    @override_settings(SMS_DEV_MODE=True)
    def test_console_backend_logs_code(self):
        with self.assertLogs("notifications", level="INFO") as captured:
            ConsoleSmsBackend().send_code("13800138000", "123456")
        self.assertIn("123456", captured.output[0])

    @override_settings(SMS_DEV_MODE=False)
    def test_console_backend_never_logs_code_in_production(self):
        """未接短信商时只报错,不把验证码写进日志(H-3)。"""
        with self.assertLogs("notifications", level="ERROR") as captured:
            ConsoleSmsBackend().send_code("13800138000", "123456")
        joined = "\n".join(captured.output)
        self.assertNotIn("123456", joined)
        self.assertIn("138****8000", joined)


class SendSmsCodeTaskTests(TestCase):
    """短信发送任务:只负责把调用透传给后端。"""

    def test_task_delegates_to_backend(self):
        with patch("notifications.tasks.get_sms_backend") as backend:
            send_sms_code.run("13800138000", "123456")
        backend.return_value.send_code.assert_called_once_with("13800138000", "123456")
