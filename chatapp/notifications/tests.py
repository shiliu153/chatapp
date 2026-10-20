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
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

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


class PushDeviceApiTests(APITestCase):
    """设备上报:幂等、单设备、换账号易主、解绑幂等。"""

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13900139000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _register(self, rid="rid-1", platform="android", version="1.0.0"):
        """上报一台设备。

        Args:
            rid: registration_id。
            platform: 平台。
            version: App 版本。

        Returns:
            DRF 响应对象。
        """
        return self.client.post("/api/v1/push/devices", {
            "registration_id": rid, "platform": platform, "app_version": version,
        }, format="json")

    def test_register_creates_device(self):
        resp = self._register()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"registration_id": "rid-1", "platform": "android"})
        device = PushDevice.objects.get(registration_id="rid-1")
        self.assertEqual(device.user_id, self.me.id)
        self.assertEqual(device.app_version, "1.0.0")

    def test_register_is_idempotent(self):
        self._register()
        self._register()
        self.assertEqual(PushDevice.objects.count(), 1)

    def test_register_keeps_only_latest_device(self):
        self._register("rid-1")
        self._register("rid-2")
        self.assertEqual(
            list(PushDevice.objects.filter(user=self.me).values_list("registration_id", flat=True)),
            ["rid-2"],
        )

    def test_register_takes_over_device_from_previous_account(self):
        PushDevice.objects.create(user=self.other, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        resp = self._register("rid-1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PushDevice.objects.get(registration_id="rid-1").user_id, self.me.id)
        self.assertFalse(PushDevice.objects.filter(user=self.other).exists())

    def test_invalid_platform_rejected(self):
        resp = self._register(platform="windows")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PushDevice.objects.exists())

    def test_unregister_is_idempotent(self):
        self._register()
        first = self.client.delete("/api/v1/push/devices/rid-1")
        second = self.client.delete("/api/v1/push/devices/rid-1")
        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)
        self.assertFalse(PushDevice.objects.exists())

    def test_cannot_unregister_other_users_device(self):
        PushDevice.objects.create(user=self.other, registration_id="rid-9",
                                  platform=PushPlatform.ANDROID)
        resp = self.client.delete("/api/v1/push/devices/rid-9")
        self.assertEqual(resp.status_code, 204)
        self.assertTrue(PushDevice.objects.filter(registration_id="rid-9").exists())

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self._register().status_code, 401)
