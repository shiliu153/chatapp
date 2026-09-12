from unittest.mock import patch

from django.test import TestCase

from notifications.backends import ConsoleSmsBackend
from notifications.tasks import send_sms_code


class SmsBackendTests(TestCase):
    def test_console_backend_logs_code(self):
        with self.assertLogs("notifications", level="INFO") as captured:
            ConsoleSmsBackend().send_code("13800138000", "123456")
        self.assertIn("123456", captured.output[0])


class SendSmsCodeTaskTests(TestCase):
    def test_task_delegates_to_backend(self):
        with patch("notifications.tasks.get_sms_backend") as backend:
            send_sms_code.run("13800138000", "123456")
        backend.return_value.send_code.assert_called_once_with("13800138000", "123456")
