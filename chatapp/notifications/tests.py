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

文件信息:
    文件名称          notifications/tests.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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
        """控制台后端把验证码写进 notifications 的 INFO 日志。"""
        with self.assertLogs("notifications", level="INFO") as captured:
            ConsoleSmsBackend().send_code("13800138000", "123456")
        self.assertIn("123456", captured.output[0])


class SendSmsCodeTaskTests(TestCase):
    """短信发送任务:只负责把调用透传给后端。"""

    def test_task_delegates_to_backend(self):
        """发送任务把手机号与验证码原样交给短信后端。"""
        with patch("notifications.tasks.get_sms_backend") as backend:
            send_sms_code.run("13800138000", "123456")
        backend.return_value.send_code.assert_called_once_with("13800138000", "123456")


class PushDeviceModelTests(TestCase):
    """推送设备:registration_id 全局唯一,随用户删除级联清理。"""

    def setUp(self):
        """每个用例前建好两个账号。

        备注信息:
            两个账号用来验证 registration_id 跨账号唯一。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_registration_id_is_globally_unique(self):
        """同一 registration_id 挂到第二个账号会撞唯一约束。"""
        PushDevice.objects.create(user=self.a, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PushDevice.objects.create(user=self.b, registration_id="rid-1",
                                          platform=PushPlatform.IOS)

    def test_devices_are_deleted_with_user(self):
        """账号删除后其推送设备级联清理。"""
        PushDevice.objects.create(user=self.a, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        self.a.delete()
        self.assertFalse(PushDevice.objects.exists())


class NotificationPreferenceModelTests(TestCase):
    """通知偏好:默认全开、只建一行、未知类型一律不发。"""

    def setUp(self):
        """每个用例前建好账号。

        备注信息:
            偏好与账号一对一,用例内再按需调用 ``for_user`` 建行。
        """
        self.user = User.objects.create_user(phone="13800138000")

    def test_for_user_creates_defaults_once(self):
        """首次取偏好建一行默认全开,再取复用同一行。"""
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
        """已知五类放行,未知类型一律不放。"""
        pref = NotificationPreference.for_user(self.user)
        self.assertTrue(pref.allows("like"))
        self.assertTrue(pref.allows("match"))
        self.assertTrue(pref.allows("message"))
        self.assertTrue(pref.allows("system"))
        self.assertTrue(pref.allows("social"))
        self.assertFalse(pref.allows("promo"))

    def test_preference_is_deleted_with_user(self):
        """账号删除后偏好行级联清理。"""
        NotificationPreference.for_user(self.user)
        self.user.delete()
        self.assertFalse(NotificationPreference.objects.exists())


class PushDeviceApiTests(APITestCase):
    """设备上报:幂等、单设备、换账号易主、解绑幂等。"""

    def setUp(self):
        """每个用例前建好本人与他人两个账号,并给客户端带上本人 access token。

        备注信息:
            他人账号用来验证「不能解绑别人的设备」与设备易主两个场景。
        """
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13900139000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _register(self, rid="rid-1", platform="android", version="1.0.0"):
        """上报一台设备。

        参数说明:
            rid: registration_id。
            platform: 平台。
            version: App 版本。

        返回参数:
            DRF 响应对象。

        使用示例:
            ``self._register("rid-2", platform="ios", version="1.0.1")``

        备注信息:
            走 POST /api/v1/push/devices,请求体按 JSON 提交。
        """
        return self.client.post("/api/v1/push/devices", {
            "registration_id": rid, "platform": platform, "app_version": version,
        }, format="json")

    def test_register_creates_device(self):
        """首次上报会新建设备行,并落库 App 版本。"""
        resp = self._register()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"registration_id": "rid-1", "platform": "android"})
        device = PushDevice.objects.get(registration_id="rid-1")
        self.assertEqual(device.user_id, self.me.id)
        self.assertEqual(device.app_version, "1.0.0")

    def test_register_is_idempotent(self):
        """同一 rid 重复上报只留一行设备。"""
        self._register()
        self._register()
        self.assertEqual(PushDevice.objects.count(), 1)

    def test_register_keeps_only_latest_device(self):
        """同一账号换 rid 上报后,旧设备行被清掉。"""
        self._register("rid-1")
        self._register("rid-2")
        self.assertEqual(
            list(PushDevice.objects.filter(user=self.me)
                 .values_list("registration_id", flat=True)),
            ["rid-2"],
        )

    def test_register_takes_over_device_from_previous_account(self):
        """rid 已被别的账号占用时,设备行改挂到当前账号。"""
        PushDevice.objects.create(user=self.other, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        resp = self._register("rid-1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PushDevice.objects.get(registration_id="rid-1").user_id, self.me.id)
        self.assertFalse(PushDevice.objects.filter(user=self.other).exists())

    def test_transfer_notifies_previous_account(self):
        """设备易主会给原账号留一条 system 站内通知,并打一条 warning 日志。"""
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
        """同账号重复上报同一 rid,既不建通知也不打 warning。"""
        self._register("rid-1")
        with self.assertNoLogs("notifications.views", level="WARNING"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self._register("rid-1")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(InAppNotification.objects.exists())

    def test_new_registration_id_does_not_notify(self):
        """换新 rid 报同一账号不产生任何通知。"""
        self._register("rid-1")
        with self.captureOnCommitCallbacks(execute=True):
            self._register("rid-2")
        self.assertFalse(InAppNotification.objects.exists())

    def test_invalid_platform_rejected(self):
        """平台不在枚举内时返回 400,且不落库。"""
        resp = self._register(platform="windows")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PushDevice.objects.exists())

    def test_unregister_is_idempotent(self):
        """连续两次解绑同一 rid 都返回 204。"""
        self._register()
        first = self.client.delete("/api/v1/push/devices/rid-1")
        second = self.client.delete("/api/v1/push/devices/rid-1")
        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)
        self.assertFalse(PushDevice.objects.exists())

    def test_cannot_unregister_other_users_device(self):
        """解绑别人的设备返回 204,但设备行仍保留。"""
        PushDevice.objects.create(user=self.other, registration_id="rid-9",
                                  platform=PushPlatform.ANDROID)
        resp = self.client.delete("/api/v1/push/devices/rid-9")
        self.assertEqual(resp.status_code, 204)
        self.assertTrue(PushDevice.objects.filter(registration_id="rid-9").exists())

    def test_requires_auth(self):
        """未登录上报设备返回 401。"""
        self.client.credentials()
        self.assertEqual(self._register().status_code, 401)


class PushPreferenceApiTests(APITestCase):
    """通知偏好:默认全开、局部更新、非法值 400。"""

    def setUp(self):
        """每个用例前建好本人账号,并给客户端带上 access token。

        备注信息:
            偏好接口只认本人,故不建他人账号。
        """
        self.me = User.objects.create_user(phone="13800138000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def test_get_returns_defaults(self):
        """首次读偏好返回五类全开的默认值。"""
        resp = self.client.get("/api/v1/push/preferences")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"likes": True, "matches": True, "messages": True,
                                     "system": True, "social": True})

    def test_patch_updates_only_given_field(self):
        """PATCH 只改传入字段,其余四类保持默认开。"""
        resp = self.client.patch("/api/v1/push/preferences", {"likes": False}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"likes": False, "matches": True, "messages": True,
                                     "system": True, "social": True})
        self.assertFalse(NotificationPreference.for_user(self.me).likes)

    def test_patch_can_turn_off_message_push(self):
        """可以单独关掉新消息推送开关。"""
        resp = self.client.patch("/api/v1/push/preferences", {"messages": False},
                                 format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(NotificationPreference.for_user(self.me).messages)

    def test_patch_rejects_non_boolean(self):
        """非布尔值被拒为 400,库里的原值不变。"""
        resp = self.client.patch("/api/v1/push/preferences", {"likes": "maybe"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(NotificationPreference.for_user(self.me).likes)

    def test_requires_auth(self):
        """未登录读偏好返回 401。"""
        self.client.credentials()
        self.assertEqual(self.client.get("/api/v1/push/preferences").status_code, 401)


class PushClientTests(SimpleTestCase):
    """推送客户端:三态选择;极光载荷正确;网络错误不抛;缺 key 不静默降级。"""

    def test_log_client_returns_true_and_logs(self):
        """日志通道发送成功后返回 True,并写一条 INFO 日志。"""
        with self.assertLogs("notifications", level="INFO") as captured:
            ok = LogPushClient().send(["rid-1"], title="t", alert="a", extras={})
        self.assertTrue(ok)
        self.assertIn("推送-日志", captured.output[0])

    @override_settings(PUSH_PROVIDER=PROVIDER_JPUSH, JPUSH_APP_KEY="k",
                       JPUSH_MASTER_SECRET="s")
    def test_jpush_provider_returns_jpush_client(self):
        """PUSH_PROVIDER=jpush 且密钥齐全时返回极光客户端。"""
        self.assertIsInstance(get_push_client(), JPushClient)

    @override_settings(PUSH_PROVIDER=PROVIDER_LOG)
    def test_log_provider_returns_log_client(self):
        """PUSH_PROVIDER=log 时返回日志客户端。"""
        self.assertIsInstance(get_push_client(), LogPushClient)

    @override_settings(PUSH_PROVIDER=PROVIDER_OFF)
    def test_off_provider_returns_off_client(self):
        """PUSH_PROVIDER=off 时返回空实现客户端。"""
        self.assertIsInstance(get_push_client(), OffPushClient)

    @override_settings(PUSH_PROVIDER="nonsense")
    def test_unknown_provider_falls_back_to_off(self):
        """通道名不认识时退化为空实现,不当成 jpush。"""
        self.assertIsInstance(get_push_client(), OffPushClient)

    @override_settings(PUSH_PROVIDER=PROVIDER_JPUSH, JPUSH_APP_KEY="",
                       JPUSH_MASTER_SECRET="")
    def test_jpush_without_keys_raises(self):
        """宁可炸出来,也不要静默退化成「只打日志」。"""
        with self.assertRaises(ImproperlyConfigured):
            get_push_client()

    @patch("notifications.push.requests.post")
    def test_jpush_client_posts_expected_payload(self, post):
        """极光客户端按 SDK 口径拼 audience、extras,并带 Basic 鉴权头。"""
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
        """网络异常被吞掉,只返回 False 不向上抛。"""
        self.assertFalse(JPushClient("key", "secret").send(
            ["rid-1"], title="t", alert="a", extras={}))

    @patch("notifications.push.requests.post")
    def test_jpush_client_reports_non_2xx(self, post):
        """极光返回非 2xx 时返回 False。"""
        post.return_value.status_code = 401
        post.return_value.text = "unauthorized"
        self.assertFalse(JPushClient("key", "secret").send(
            ["rid-1"], title="t", alert="a", extras={}))


@override_settings(PUSH_PROVIDER=PROVIDER_LOG)
class SendPushTaskTests(TestCase):
    """推送任务:偏好、设备、冷却、失败重试的边界。"""

    def setUp(self):
        """每个用例前清空缓存,建好账号与一台 Android 设备。

        备注信息:
            类级 override_settings 把通道压成 log,用例内再按需覆盖。
        """
        cache.clear()
        self.user = User.objects.create_user(phone="13800138000")
        PushDevice.objects.create(user=self.user, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)

    def test_skips_when_provider_off(self):
        """通道为 off 时直接返回,连推送客户端都不取。"""
        with override_settings(PUSH_PROVIDER=PROVIDER_OFF):
            with patch("notifications.tasks.get_push_client") as factory:
                send_push.run(self.user.id, "match", "t", "a", {})
        factory.assert_not_called()

    def test_skips_when_preference_disabled(self):
        """对应偏好关闭时不取推送客户端。"""
        NotificationPreference.objects.create(user=self.user, likes=False)
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "like", "t", "a", {})
        factory.assert_not_called()

    def test_skips_without_devices(self):
        """账号没有设备时不取推送客户端。"""
        PushDevice.objects.all().delete()
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "match", "t", "a", {})
        factory.assert_not_called()

    def test_skips_unknown_user(self):
        """账号不存在时不取推送客户端。"""
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(999999, "match", "t", "a", {})
        factory.assert_not_called()

    def test_sends_to_all_devices(self):
        """一次推送把该账号所有设备的 registration_id 一起下发。"""
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
        """同类推送落在冷却窗口内时只发第一条。"""
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "like", "t", "a", {})
            send_push.run(self.user.id, "like", "t", "a", {})
        self.assertEqual(factory.return_value.send.call_count, 1)

    def test_failed_send_releases_cooldown_and_raises(self):
        """发送失败抛 RuntimeError,同时释放冷却键以便重试。"""
        with patch("notifications.tasks.get_push_client") as factory:
            factory.return_value.send.return_value = False
            with self.assertRaises(RuntimeError):
                send_push.run(self.user.id, "like", "t", "a", {})
        self.assertIsNone(cache.get(like_cooldown_key(self.user.id)))


@override_settings(PUSH_PROVIDER=PROVIDER_LOG)
class SendMessagePushTaskTests(TestCase):
    """离线新消息推送:封禁、偏好、设备、按 msg_id 去重、失败释放幂等位。"""

    def setUp(self):
        """每个用例前清空缓存,建好收件人(带昵称与设备)与发件人账号。

        备注信息:
            收件人的 Profile 必须是 COMPLETE 状态,任务会按状态跳过封禁账号。
        """
        cache.clear()
        self.to_user = User.objects.create_user(phone="13800138000")
        self.from_user = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.to_user, nickname="收件人", status=ProfileStatus.COMPLETE)
        PushDevice.objects.create(user=self.to_user, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)

    def _run(self, dedupe_key="msg-1", preview="在吗", nickname="发件人"):
        """跑一次任务(同步执行,便于断言)。

        参数说明:
            dedupe_key: 幂等键,默认 ``msg-1``。
            preview: 消息预览文本,默认「在吗」。
            nickname: 发件人昵称,默认「发件人」。

        返回参数:
            无返回值。

        使用示例:
            ``self._run(dedupe_key="msg-42", preview="晚上一起吃饭吗")``

        备注信息:
            直接调 ``send_message_push.run``,不经 broker,断言可立刻查。
        """
        send_message_push.run(self.to_user.id, self.from_user.id, nickname, preview,
                              dedupe_key)

    def test_sends_with_deeplink_and_preview(self):
        """推送里带发件人昵称、预览、聊天跳转链接与 peer 参数。"""
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
        """通道为 off 时不推。"""
        with override_settings(PUSH_PROVIDER=PROVIDER_OFF):
            with patch("notifications.tasks.get_push_client") as factory:
                self._run()
        factory.assert_not_called()

    def test_skips_banned_user(self):
        """收件人被重封禁时不推。"""
        Profile.objects.filter(user=self.to_user).update(status=ProfileStatus.BANNED_HEAVY)
        with patch("notifications.tasks.get_push_client") as factory:
            self._run()
        factory.assert_not_called()

    def test_skips_when_message_switch_off(self):
        """新消息开关关闭时不推。"""
        NotificationPreference.objects.create(user=self.to_user, messages=False)
        with patch("notifications.tasks.get_push_client") as factory:
            self._run()
        factory.assert_not_called()

    def test_skips_without_device(self):
        """收件人没有登记设备时不推。"""
        PushDevice.objects.all().delete()
        with patch("notifications.tasks.get_push_client") as factory:
            self._run()
        factory.assert_not_called()

    def test_skips_unknown_user(self):
        """收件账号不存在时不推。"""
        with patch("notifications.tasks.get_push_client") as factory:
            send_message_push.run(999999, self.from_user.id, "x", "y", "msg-9")
        factory.assert_not_called()

    def test_same_message_is_pushed_once(self):
        """同一 msg_id 重复投递只推一次。"""
        with patch("notifications.tasks.get_push_client") as factory:
            self._run(dedupe_key="msg-42")
            self._run(dedupe_key="msg-42")
        self.assertEqual(factory.return_value.send.call_count, 1)

    def test_failed_send_releases_dedup_key(self):
        """发送失败抛 RuntimeError,并释放幂等位以便重投。"""
        with patch("notifications.tasks.get_push_client") as factory:
            factory.return_value.send.return_value = False
            with self.assertRaises(RuntimeError):
                self._run(dedupe_key="msg-77")
        self.assertIsNone(cache.get(message_dedup_key("msg-77")))

    def test_empty_preview_uses_placeholder(self):
        """预览为空时用占位标题与正文。"""
        payload = message_payload("", "", 7)
        self.assertEqual(payload["title"], "新消息")
        self.assertEqual(payload["alert"], "给你发来一条消息")

    def test_preview_is_truncated(self):
        """超长预览被截断到 40 字以内。"""
        payload = message_payload("张三", "很" * 100, 7)
        self.assertLessEqual(len(payload["alert"]), 40)


@override_settings(IM_SELF_INTERNAL_SECRET=SECRET)
class InternalPushEndpointTests(TestCase):
    """imserver → Django 的内部事件入口:验签、时间戳窗口、字段校验、方法限制。"""

    def setUp(self):
        """每个用例前清空缓存,建好收发双方账号。

        备注信息:
            不建 Profile 与设备:内部事件用例只验签、校验字段并断言入队。
        """
        cache.clear()
        self.to_user = User.objects.create_user(phone="13800138000")
        self.from_user = User.objects.create_user(phone="13900139000")

    def _body(self, **overrides):
        """构造事件体(JSON 字符串)。

        参数说明:
            **overrides: 覆盖默认字段。

        返回参数:
            JSON 字符串。

        使用示例:
            ``self._body(from_user_id=self.to_user.id)``

        备注信息:
            默认填入收件、发件、昵称、预览与 msg_id;序列化时不转义中文、不加空格。
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

        参数说明:
            body: 请求体字符串。
            timestamp: 时间戳,默认当前秒。
            secret: 签名密钥。
            path: 用于计算签名的路径。
            signature: 直接指定签名,默认按 secret 现算。

        返回参数:
            Django 测试客户端响应。

        使用示例:
            ``self._post(body, timestamp=ts, path=INTERNAL_PATH)``

        备注信息:
            请求头固定带 X-IM-Timestamp 与 X-IM-Signature,签名覆盖时间戳 + 路径 + 请求体。
        """
        ts = str(int(time.time())) if timestamp is None else str(timestamp)
        sig = signature if signature is not None else signature_for(ts, path, body, secret)
        return self.client.post(INTERNAL_PATH, data=body,
                                content_type="application/json",
                                HTTP_X_IM_TIMESTAMP=ts, HTTP_X_IM_SIGNATURE=sig)

    def test_valid_event_is_queued(self):
        """合法事件验签通过后返回 202,并把推送任务入队。"""
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
        """签名对不上时返回 401。"""
        resp = self._post(self._body(), signature="deadbeef")
        self.assertEqual(resp.status_code, 401)

    def test_signature_for_other_path_rejected(self):
        """用别的路径算出的签名返回 401。"""
        body = self._body()
        ts = str(int(time.time()))
        sig = signature_for(ts, "/internal/other", body, SECRET)
        resp = self._post(body, signature=sig)
        self.assertEqual(resp.status_code, 401)

    def test_stale_timestamp_rejected(self):
        """时间戳超出容忍窗口时返回 401。"""
        resp = self._post(self._body(), timestamp=int(time.time()) - 3600)
        self.assertEqual(resp.status_code, 401)

    def test_missing_headers_rejected(self):
        """没带签名头时返回 401。"""
        resp = self.client.post(INTERNAL_PATH, data=self._body(),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 401)

    def test_no_secret_configured_rejected(self):
        """未配置内部密钥时一律返回 401。"""
        with override_settings(IM_SELF_INTERNAL_SECRET=""):
            resp = self._post(self._body())
        self.assertEqual(resp.status_code, 401)

    def test_invalid_json_rejected(self):
        """请求体不是合法 JSON 时返回 400。"""
        resp = self._post("not-json")
        self.assertEqual(resp.status_code, 400)

    def test_same_sender_and_receiver_rejected(self):
        """收发双方是同一个账号时返回 400。"""
        resp = self._post(self._body(from_user_id=self.to_user.id))
        self.assertEqual(resp.status_code, 400)

    def test_missing_msg_id_rejected(self):
        """缺 msg_id 字段时返回 400。"""
        body = self._body()
        data = json.loads(body)
        data.pop("msg_id")
        resp = self._post(json.dumps(data, separators=(",", ":")))
        self.assertEqual(resp.status_code, 400)

    def test_get_method_not_allowed(self):
        """GET 方法不被允许,返回 405。"""
        self.assertEqual(self.client.get(INTERNAL_PATH).status_code, 405)


@override_settings(PUSH_PROVIDER=PROVIDER_LOG)
class PushTestCommandTests(TestCase):
    """push_test 命令:三类各发一条;缺设备 / 缺 peer 明确报错。"""

    def setUp(self):
        """每个用例前清空缓存,并建好已登记设备的账号。

                备注信息:
                    只建最小账号不建 Profile:命令用例只跑推送链路,不需要完整资料。
                """
        cache.clear()
        self.user = User.objects.create_user(phone="13800138000")
        PushDevice.objects.create(user=self.user, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)

    def test_sends_all_three_with_peer(self):
        """kind=all 时三类各发一条,跳转链接分别为配对、聊天、系统通知。"""
        with patch("notifications.tasks.get_push_client") as factory:
            call_command("push_test", user=self.user.id, kind="all", peer=99, force=True)
        client = factory.return_value
        self.assertEqual(client.send.call_count, 3)
        deeplinks = [call.kwargs["extras"]["deeplink"]
                     for call in client.send.call_args_list]
        self.assertEqual(deeplinks, ["/likes", "/chat/99", "/chat/system_notice"])

    def test_requires_registered_device(self):
        """账号没有登记设备时命令抛 CommandError。"""
        PushDevice.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("push_test", user=self.user.id, kind="system")

    def test_match_requires_peer(self):
        """kind=match 缺 peer 参数时命令抛 CommandError。"""
        with self.assertRaises(CommandError):
            call_command("push_test", user=self.user.id, kind="match")

    def test_unknown_user_is_rejected(self):
        """账号不存在时命令抛 CommandError。"""
        with self.assertRaises(CommandError):
            call_command("push_test", user=999999, kind="system")

    def test_disabled_preference_is_skipped(self):
        """系统通知开关关闭时不调用推送客户端。"""
        NotificationPreference.objects.create(user=self.user, system=False)
        with patch("notifications.tasks.get_push_client") as factory:
            call_command("push_test", user=self.user.id, kind="system")
        factory.assert_not_called()
