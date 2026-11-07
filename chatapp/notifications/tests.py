"""通知应用的测试:短信后端、发送任务、推送模型、客户端、接口、内部事件与测试命令。

覆盖场景:
    - 控制台后端把验证码写进日志;
    - 发送任务把调用透传给后端(不真的发短信);
    - 推送设备:registration_id 全局唯一、随用户删除级联清理;
    - 推送设备易主:设备行归新账号,原账号收到 1 条 system 站内通知 + 一条
      ``push_device_transfer`` warning 日志;同账号重复上报与新 rid 都不产生这些副作用;
    - 通知偏好:默认全开(五类)、只建一行、未知类型一律不发;
    - 推送客户端:三态通道选择、极光载荷正确、网络错误不抛、jpush 缺 key 直接报错;
    - 推送任务:通道/偏好/设备/冷却/失败重试的边界;
    - 新消息推送任务:封禁、偏好、设备、按 msg_id 去重、失败释放幂等位;
    - 内部事件入口:HMAC 验签、时间戳窗口、字段校验、方法限制;
    - push_test 命令:三类各发一条、缺设备/缺 peer 报错。
"""

import json
import time
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from notifications.backends import ConsoleSmsBackend
from notifications.internal import INTERNAL_PATH, signature_for
from notifications.models import (InAppNotification, NotificationKind, NotificationPreference,
                                  NotificationTarget, PushDevice, PushPlatform)
from notifications.push import (PROVIDER_JPUSH, PROVIDER_LOG, PROVIDER_OFF, JPushClient,
                                LogPushClient, OffPushClient, get_push_client)
from notifications.tasks import (like_cooldown_key, message_dedup_key, message_payload,
                                 send_message_push, send_push, send_sms_code)
from users.models import Profile, ProfileStatus

User = get_user_model()

SECRET = "test-internal-secret"


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
        self.assertTrue(pref.messages)
        self.assertTrue(pref.system)
        self.assertTrue(pref.social)

        again = NotificationPreference.for_user(self.user)
        self.assertEqual(again.pk, pref.pk)
        self.assertEqual(NotificationPreference.objects.count(), 1)

    def test_allows_known_and_unknown_kinds(self):
        pref = NotificationPreference.for_user(self.user)
        self.assertTrue(pref.allows("like"))
        self.assertTrue(pref.allows("match"))
        self.assertTrue(pref.allows("message"))
        self.assertTrue(pref.allows("system"))
        self.assertTrue(pref.allows("social"))
        self.assertFalse(pref.allows("promo"))

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
            list(PushDevice.objects.filter(user=self.me)
                 .values_list("registration_id", flat=True)),
            ["rid-2"],
        )

    def test_register_takes_over_device_from_previous_account(self):
        PushDevice.objects.create(user=self.other, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        resp = self._register("rid-1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PushDevice.objects.get(registration_id="rid-1").user_id, self.me.id)
        self.assertFalse(PushDevice.objects.filter(user=self.other).exists())

    def test_transfer_notifies_previous_account(self):
        PushDevice.objects.create(user=self.other, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        with self.assertLogs("notifications.views", level="WARNING") as logs:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self._register("rid-1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PushDevice.objects.get(registration_id="rid-1").user_id, self.me.id)
        # 原账号拿到唯一一条系统通知:无 actor(不泄漏是谁把设备挂走了)、无跳转目标。
        notification = InAppNotification.objects.get(user=self.other)
        self.assertEqual(notification.kind, NotificationKind.SYSTEM)
        self.assertEqual(notification.target_kind, NotificationTarget.NONE)
        self.assertIsNone(notification.target_id)
        self.assertIsNone(notification.actor_id)
        self.assertEqual(notification.text, "你的设备已在另一账号登录,推送已切换")
        self.assertFalse(InAppNotification.objects.filter(user=self.me).exists())
        # 留痕:日志里有 rid 与两端账号 id(推格式化参数,不塞 extra)。
        self.assertTrue(any(
            f"push_device_transfer registration_id=rid-1 from_user={self.other.id}"
            f" to_user={self.me.id}" in line for line in logs.output), logs.output)

    def test_reregister_same_account_does_not_notify_or_log_transfer(self):
        self._register("rid-1")
        with self.assertNoLogs("notifications.views", level="WARNING"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self._register("rid-1")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(InAppNotification.objects.exists())

    def test_new_registration_id_does_not_notify(self):
        self._register("rid-1")
        with self.captureOnCommitCallbacks(execute=True):
            self._register("rid-2")
        self.assertFalse(InAppNotification.objects.exists())

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
        self.assertEqual(resp.data, {"likes": True, "matches": True, "messages": True,
                                     "system": True, "social": True})

    def test_patch_updates_only_given_field(self):
        resp = self.client.patch("/api/v1/push/preferences", {"likes": False}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"likes": False, "matches": True, "messages": True,
                                     "system": True, "social": True})
        self.assertFalse(NotificationPreference.for_user(self.me).likes)

    def test_patch_can_turn_off_message_push(self):
        resp = self.client.patch("/api/v1/push/preferences", {"messages": False},
                                 format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(NotificationPreference.for_user(self.me).messages)

    def test_patch_rejects_non_boolean(self):
        resp = self.client.patch("/api/v1/push/preferences", {"likes": "maybe"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(NotificationPreference.for_user(self.me).likes)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get("/api/v1/push/preferences").status_code, 401)


class PushClientTests(SimpleTestCase):
    """推送客户端:三态选择;极光载荷正确;网络错误不抛;缺 key 不静默降级。"""

    def test_log_client_returns_true_and_logs(self):
        with self.assertLogs("notifications", level="INFO") as captured:
            ok = LogPushClient().send(["rid-1"], title="t", alert="a", extras={})
        self.assertTrue(ok)
        self.assertIn("推送-日志", captured.output[0])

    @override_settings(PUSH_PROVIDER=PROVIDER_JPUSH, JPUSH_APP_KEY="k",
                       JPUSH_MASTER_SECRET="s")
    def test_jpush_provider_returns_jpush_client(self):
        self.assertIsInstance(get_push_client(), JPushClient)

    @override_settings(PUSH_PROVIDER=PROVIDER_LOG)
    def test_log_provider_returns_log_client(self):
        self.assertIsInstance(get_push_client(), LogPushClient)

    @override_settings(PUSH_PROVIDER=PROVIDER_OFF)
    def test_off_provider_returns_off_client(self):
        self.assertIsInstance(get_push_client(), OffPushClient)

    @override_settings(PUSH_PROVIDER="nonsense")
    def test_unknown_provider_falls_back_to_off(self):
        self.assertIsInstance(get_push_client(), OffPushClient)

    @override_settings(PUSH_PROVIDER=PROVIDER_JPUSH, JPUSH_APP_KEY="",
                       JPUSH_MASTER_SECRET="")
    def test_jpush_without_keys_raises(self):
        """宁可炸出来,也不要静默退化成「只打日志」。"""
        with self.assertRaises(ImproperlyConfigured):
            get_push_client()

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
        self.assertEqual(kwargs["json"]["notification"]["android"]["extras"]["deeplink"],
                         "/likes")
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


@override_settings(PUSH_PROVIDER=PROVIDER_LOG)
class SendPushTaskTests(TestCase):
    """推送任务:偏好、设备、冷却、失败重试的边界。"""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(phone="13800138000")
        PushDevice.objects.create(user=self.user, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)

    def test_skips_when_provider_off(self):
        with override_settings(PUSH_PROVIDER=PROVIDER_OFF):
            with patch("notifications.tasks.get_push_client") as factory:
                send_push.run(self.user.id, "match", "t", "a", {})
        factory.assert_not_called()

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
            send_push.run(self.user.id, "match", "配对成功", "你们互相喜欢了",
                          {"deeplink": "/chat/2"})
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


@override_settings(PUSH_PROVIDER=PROVIDER_LOG)
class SendMessagePushTaskTests(TestCase):
    """离线新消息推送:封禁、偏好、设备、按 msg_id 去重、失败释放幂等位。"""

    def setUp(self):
        cache.clear()
        self.to_user = User.objects.create_user(phone="13800138000")
        self.from_user = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.to_user, nickname="收件人", status=ProfileStatus.COMPLETE)
        PushDevice.objects.create(user=self.to_user, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)

    def _run(self, dedupe_key="msg-1", preview="在吗", nickname="发件人"):
        """跑一次任务(同步执行,便于断言)。"""
        send_message_push.run(self.to_user.id, self.from_user.id, nickname, preview,
                              dedupe_key)

    def test_sends_with_deeplink_and_preview(self):
        with patch("notifications.tasks.get_push_client") as factory:
            self._run(preview="晚上一起吃饭吗")
        client = factory.return_value
        client.send.assert_called_once()
        kwargs = client.send.call_args.kwargs
        self.assertEqual(kwargs["title"], "发件人")
        self.assertEqual(kwargs["alert"], "晚上一起吃饭吗")
        self.assertEqual(kwargs["extras"]["deeplink"], f"/home/chats/{self.from_user.id}")
        self.assertEqual(kwargs["extras"]["peer"], str(self.from_user.id))

    def test_skips_when_provider_off(self):
        with override_settings(PUSH_PROVIDER=PROVIDER_OFF):
            with patch("notifications.tasks.get_push_client") as factory:
                self._run()
        factory.assert_not_called()

    def test_skips_banned_user(self):
        Profile.objects.filter(user=self.to_user).update(status=ProfileStatus.BANNED_HEAVY)
        with patch("notifications.tasks.get_push_client") as factory:
            self._run()
        factory.assert_not_called()

    def test_skips_when_message_switch_off(self):
        NotificationPreference.objects.create(user=self.to_user, messages=False)
        with patch("notifications.tasks.get_push_client") as factory:
            self._run()
        factory.assert_not_called()

    def test_skips_without_device(self):
        PushDevice.objects.all().delete()
        with patch("notifications.tasks.get_push_client") as factory:
            self._run()
        factory.assert_not_called()

    def test_skips_unknown_user(self):
        with patch("notifications.tasks.get_push_client") as factory:
            send_message_push.run(999999, self.from_user.id, "x", "y", "msg-9")
        factory.assert_not_called()

    def test_same_message_is_pushed_once(self):
        with patch("notifications.tasks.get_push_client") as factory:
            self._run(dedupe_key="msg-42")
            self._run(dedupe_key="msg-42")
        self.assertEqual(factory.return_value.send.call_count, 1)

    def test_failed_send_releases_dedup_key(self):
        with patch("notifications.tasks.get_push_client") as factory:
            factory.return_value.send.return_value = False
            with self.assertRaises(RuntimeError):
                self._run(dedupe_key="msg-77")
        self.assertIsNone(cache.get(message_dedup_key("msg-77")))

    def test_empty_preview_uses_placeholder(self):
        payload = message_payload("", "", 7)
        self.assertEqual(payload["title"], "新消息")
        self.assertEqual(payload["alert"], "给你发来一条消息")

    def test_preview_is_truncated(self):
        payload = message_payload("张三", "很" * 100, 7)
        self.assertLessEqual(len(payload["alert"]), 40)


@override_settings(IM_SELF_INTERNAL_SECRET=SECRET)
class InternalPushEndpointTests(TestCase):
    """imserver → Django 的内部事件入口:验签、时间戳窗口、字段校验、方法限制。"""

    def setUp(self):
        cache.clear()
        self.to_user = User.objects.create_user(phone="13800138000")
        self.from_user = User.objects.create_user(phone="13900139000")

    def _body(self, **overrides):
        """构造事件体(JSON 字符串)。

        Args:
            **overrides: 覆盖默认字段。

        Returns:
            JSON 字符串。
        """
        data = {
            "to_user_id": self.to_user.id,
            "from_user_id": self.from_user.id,
            "from_nickname": "发件人",
            "preview": "在吗",
            "msg_id": 12345,
        }
        data.update(overrides)
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def _post(self, body, *, timestamp=None, secret=SECRET, path=INTERNAL_PATH,
              signature=None):
        """按内部签名口径发一次请求。

        Args:
            body: 请求体字符串。
            timestamp: 时间戳(默认当前秒)。
            secret: 签名密钥。
            path: 用于计算签名的路径。
            signature: 直接指定签名(默认按 secret 计算)。

        Returns:
            Django 测试客户端响应。
        """
        ts = str(int(time.time())) if timestamp is None else str(timestamp)
        sig = signature if signature is not None else signature_for(ts, path, body, secret)
        return self.client.post(INTERNAL_PATH, data=body,
                                content_type="application/json",
                                HTTP_X_IM_TIMESTAMP=ts, HTTP_X_IM_SIGNATURE=sig)

    def test_valid_event_is_queued(self):
        body = self._body()
        with patch("notifications.internal.services.enqueue_message_push") as enqueue:
            resp = self._post(body)
        self.assertEqual(resp.status_code, 202)
        enqueue.assert_called_once()
        kwargs = enqueue.call_args.kwargs
        self.assertEqual(kwargs["to_user_id"], self.to_user.id)
        self.assertEqual(kwargs["from_user_id"], self.from_user.id)
        self.assertEqual(kwargs["dedupe_key"], "12345")

    def test_bad_signature_rejected(self):
        resp = self._post(self._body(), signature="deadbeef")
        self.assertEqual(resp.status_code, 401)

    def test_signature_for_other_path_rejected(self):
        body = self._body()
        ts = str(int(time.time()))
        sig = signature_for(ts, "/internal/other", body, SECRET)
        resp = self._post(body, signature=sig)
        self.assertEqual(resp.status_code, 401)

    def test_stale_timestamp_rejected(self):
        resp = self._post(self._body(), timestamp=int(time.time()) - 3600)
        self.assertEqual(resp.status_code, 401)

    def test_missing_headers_rejected(self):
        resp = self.client.post(INTERNAL_PATH, data=self._body(),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 401)

    def test_no_secret_configured_rejected(self):
        with override_settings(IM_SELF_INTERNAL_SECRET=""):
            resp = self._post(self._body())
        self.assertEqual(resp.status_code, 401)

    def test_invalid_json_rejected(self):
        resp = self._post("not-json")
        self.assertEqual(resp.status_code, 400)

    def test_same_sender_and_receiver_rejected(self):
        resp = self._post(self._body(from_user_id=self.to_user.id))
        self.assertEqual(resp.status_code, 400)

    def test_missing_msg_id_rejected(self):
        body = self._body()
        data = json.loads(body)
        data.pop("msg_id")
        resp = self._post(json.dumps(data, separators=(",", ":")))
        self.assertEqual(resp.status_code, 400)

    def test_get_method_not_allowed(self):
        self.assertEqual(self.client.get(INTERNAL_PATH).status_code, 405)


@override_settings(PUSH_PROVIDER=PROVIDER_LOG)
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
        deeplinks = [call.kwargs["extras"]["deeplink"]
                     for call in client.send.call_args_list]
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
