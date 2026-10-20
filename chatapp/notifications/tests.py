"""通知应用的测试:覆盖短信后端、发送任务、推送模型、客户端、接口与测试命令。

覆盖场景:
    - 控制台后端把验证码写进日志;
    - 发送任务把调用透传给后端(不真的发短信);
    - 推送设备:registration_id 全局唯一、随用户删除级联清理;
    - 通知偏好:默认全开、只建一行、未知类型一律不发;
    - 推送客户端:日志后端不触网、极光载荷正确、网络错误不抛;
    - 推送任务:偏好/设备/冷却/失败重试的边界;
    - push_test 命令:三类各发一条、缺设备/缺 peer 报错。
"""

from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from notifications.backends import ConsoleSmsBackend
from notifications.models import NotificationPreference, PushDevice, PushPlatform
from notifications.push import JPushClient, LogPushClient, get_push_client
from notifications.tasks import like_cooldown_key, send_push, send_sms_code

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


class PushPreferenceApiTests(APITestCase):
    """通知偏好:默认全开、局部更新、非法值 400。"""

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def test_get_returns_defaults(self):
        resp = self.client.get("/api/v1/push/preferences")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"likes": True, "matches": True, "system": True})

    def test_patch_updates_only_given_field(self):
        resp = self.client.patch("/api/v1/push/preferences", {"likes": False}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"likes": False, "matches": True, "system": True})
        self.assertFalse(NotificationPreference.for_user(self.me).likes)

    def test_patch_rejects_non_boolean(self):
        resp = self.client.patch("/api/v1/push/preferences", {"likes": "maybe"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(NotificationPreference.for_user(self.me).likes)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get("/api/v1/push/preferences").status_code, 401)


class PushClientTests(SimpleTestCase):
    """推送客户端:日志后端不触网;极光载荷正确;网络错误不抛。"""

    def test_log_client_returns_true_and_logs(self):
        with self.assertLogs("notifications", level="INFO") as captured:
            ok = LogPushClient().send(["rid-1"], title="t", alert="a", extras={})
        self.assertTrue(ok)
        self.assertIn("推送-日志", captured.output[0])

    @override_settings(PUSH_ENABLED=True, JPUSH_APP_KEY="k", JPUSH_MASTER_SECRET="s")
    def test_enabled_with_keys_returns_jpush_client(self):
        self.assertIsInstance(get_push_client(), JPushClient)

    @override_settings(PUSH_ENABLED=False)
    def test_disabled_returns_log_client(self):
        self.assertIsInstance(get_push_client(), LogPushClient)

    @patch("notifications.push.requests.post")
    def test_jpush_client_posts_expected_payload(self, post):
        post.return_value.status_code = 200
        client = JPushClient("key", "secret")
        ok = client.send(["rid-1"], title="有人喜欢了你", alert="去看看是谁",
                         extras={"deeplink": "/likes"})
        self.assertTrue(ok)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.jpush.cn/v3/push")
        self.assertEqual(kwargs["json"]["audience"]["registration_id"], ["rid-1"])
        self.assertEqual(kwargs["json"]["notification"]["android"]["extras"]["deeplink"], "/likes")
        self.assertTrue(kwargs["headers"]["Authorization"].startswith("Basic "))

    @patch("notifications.push.requests.post",
           side_effect=requests.RequestException("boom"))
    def test_jpush_client_swallows_network_error(self, _post):
        self.assertFalse(JPushClient("key", "secret").send(
            ["rid-1"], title="t", alert="a", extras={}))

    @patch("notifications.push.requests.post")
    def test_jpush_client_reports_non_2xx(self, post):
        post.return_value.status_code = 401
        post.return_value.text = "unauthorized"
        self.assertFalse(JPushClient("key", "secret").send(
            ["rid-1"], title="t", alert="a", extras={}))


class SendPushTaskTests(TestCase):
    """推送任务:偏好、设备、冷却、失败重试的边界。"""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(phone="13800138000")
        PushDevice.objects.create(user=self.user, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)

    def test_skips_when_preference_disabled(self):
        NotificationPreference.objects.create(user=self.user, likes=False)
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "like", "t", "a", {})
        factory.assert_not_called()

    def test_skips_without_devices(self):
        PushDevice.objects.all().delete()
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "match", "t", "a", {})
        factory.assert_not_called()

    def test_skips_unknown_user(self):
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(999999, "match", "t", "a", {})
        factory.assert_not_called()

    def test_sends_to_all_devices(self):
        PushDevice.objects.create(user=self.user, registration_id="rid-2",
                                  platform=PushPlatform.IOS)
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "match", "配对成功", "你们互相喜欢了", {"deeplink": "/chat/2"})
        client = factory.return_value
        client.send.assert_called_once()
        ids = client.send.call_args.args[0]
        self.assertEqual(set(ids), {"rid-1", "rid-2"})

    def test_like_cooldown_blocks_second_send(self):
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "like", "t", "a", {})
            send_push.run(self.user.id, "like", "t", "a", {})
        self.assertEqual(factory.return_value.send.call_count, 1)

    def test_failed_send_releases_cooldown_and_raises(self):
        with patch("notifications.tasks.get_push_client") as factory:
            factory.return_value.send.return_value = False
            with self.assertRaises(RuntimeError):
                send_push.run(self.user.id, "like", "t", "a", {})
        self.assertIsNone(cache.get(like_cooldown_key(self.user.id)))


class PushTestCommandTests(TestCase):
    """push_test 命令:三类各发一条;缺设备 / 缺 peer 明确报错。"""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(phone="13800138000")
        PushDevice.objects.create(user=self.user, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)

    def test_sends_all_three_with_peer(self):
        with patch("notifications.tasks.get_push_client") as factory:
            call_command("push_test", user=self.user.id, kind="all", peer=99, force=True)
        client = factory.return_value
        self.assertEqual(client.send.call_count, 3)
        deeplinks = [call.kwargs["extras"]["deeplink"] for call in client.send.call_args_list]
        self.assertEqual(deeplinks, ["/likes", "/chat/99", "/chat/system_notice"])

    def test_requires_registered_device(self):
        PushDevice.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("push_test", user=self.user.id, kind="system")

    def test_match_requires_peer(self):
        with self.assertRaises(CommandError):
            call_command("push_test", user=self.user.id, kind="match")

    def test_unknown_user_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("push_test", user=999999, kind="system")

    def test_disabled_preference_is_skipped(self):
        NotificationPreference.objects.create(user=self.user, system=False)
        with patch("notifications.tasks.get_push_client") as factory:
            call_command("push_test", user=self.user.id, kind="system")
        factory.assert_not_called()
