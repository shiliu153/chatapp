"""通知应用的测试:覆盖短信后端、发送任务、推送模型与接口。

覆盖场景:
    - 控制台后端把验证码写进日志;
    - 发送任务把调用透传给后端(不真的发短信);
    - 推送设备:registration_id 全局唯一、随用户删除级联清理;
    - 通知偏好:默认全开、只建一行、未知类型一律不发。
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from notifications.backends import ConsoleSmsBackend
from notifications.models import NotificationPreference, PushDevice, PushPlatform
from notifications.tasks import send_sms_code

User = get_user_model()


class SmsBackendTests(TestCase):
    """短信后端:开发期控制台实现的行为。"""

    def test_console_backend_logs_code(self):
        with self.assertLogs("notifications", level="INFO") as captured:
            ConsoleSmsBackend().send_code("13800138000", "123456")
        self.assertIn("123456", captured.output[0])


class SendSmsCodeTaskTests(TestCase):
    """短信发送任务:只负责把调用透传给后端。"""

    def test_task_delegates_to_backend(self):
        with patch("notifications.tasks.get_sms_backend") as backend:
            send_sms_code.run("13800138000", "123456")
        backend.return_value.send_code.assert_called_once_with("13800138000", "123456")


class PushDeviceModelTests(TestCase):
    """推送设备:registration_id 全局唯一,随用户删除级联清理。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_registration_id_is_globally_unique(self):
        PushDevice.objects.create(user=self.a, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PushDevice.objects.create(user=self.b, registration_id="rid-1",
                                          platform=PushPlatform.IOS)

    def test_devices_are_deleted_with_user(self):
        PushDevice.objects.create(user=self.a, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        self.a.delete()
        self.assertFalse(PushDevice.objects.exists())


class NotificationPreferenceModelTests(TestCase):
    """通知偏好:默认全开、只建一行、未知类型一律不发。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")

    def test_for_user_creates_defaults_once(self):
        pref = NotificationPreference.for_user(self.user)
        self.assertTrue(pref.likes)
        self.assertTrue(pref.matches)
        self.assertTrue(pref.system)

        again = NotificationPreference.for_user(self.user)
        self.assertEqual(again.pk, pref.pk)
        self.assertEqual(NotificationPreference.objects.count(), 1)

    def test_allows_known_and_unknown_kinds(self):
        pref = NotificationPreference.for_user(self.user)
        self.assertTrue(pref.allows("like"))
        self.assertTrue(pref.allows("match"))
        self.assertTrue(pref.allows("system"))
        self.assertFalse(pref.allows("message"))

    def test_preference_is_deleted_with_user(self):
        NotificationPreference.for_user(self.user)
        self.user.delete()
        self.assertFalse(NotificationPreference.objects.exists())
