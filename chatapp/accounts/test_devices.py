"""登录设备列表与单端下线(批次 M / T1)。

覆盖工单的六条验收口径:
    1. ``GET /api/v1/devices`` 两端各一行,``current`` 只由请求头 ``X-Client`` 判定,
       从没登录过的端不返回;
    2. ``DELETE /api/v1/devices/{client_type}`` 递增该端版本并经 Celery 踢该端 IM,
       返回 204;另一端不受影响;
    3. 踢 ``web`` 之后:web 的旧 access 返 ``401`` + ``40101``,app 的 access 仍 ``200``;
    4. 重复 ``DELETE`` 同一端仍 204(幂等);非法 ``client_type`` 返 ``400`` + ``40001``;
    5. ``last_active_at`` 在登录签发令牌与 ``/auth/token/refresh`` 成功时更新;
    6. 刷新 / 登录都不会误刷另一端的活跃时间(端维度不串)。

测试一律把 ``im.tasks`` 的入队打桩:响应路径不许有外部调用,断言只看「是否入队」。
"""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts import sms_codes
from accounts.device_session import CLIENT_APP, CLIENT_WEB
from accounts.models import DeviceSession, User


class DeviceApiTestCase(APITestCase):
    """公共夹具:一个账号 + 走真实短信登录链路、带端类型取令牌。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800000001"
        self.user = User.objects.create_user(phone=self.phone)

    def issue_code(self):
        """直接落一个验证码,绕开 60 秒重发间隔。

        Returns:
            写入的验证码(开发期固定码)。
        """
        cache.delete(f"sms:send:{self.phone}")
        sms_codes.store(self.phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE

    def login(self, client_type=CLIENT_APP):
        """走一次完整的校验登录。

        Args:
            client_type: ``app`` / ``web``;``None`` 表示不带 ``X-Client`` 头。

        Returns:
            DRF 测试客户端的响应对象。
        """
        headers = {"HTTP_X_CLIENT": client_type} if client_type else {}
        return self.client.post(
            "/api/v1/auth/sms/verify",
            {"phone": self.phone, "code": self.issue_code()}, format="json", **headers)

    def get_devices(self, access, client_type=CLIENT_APP):
        """请求登录设备列表。

        Args:
            access: access token 原文。
            client_type: 请求头 ``X-Client`` 的取值;``None`` 表示不带该头。

        Returns:
            DRF 测试客户端的响应对象。
        """
        headers = {"HTTP_X_CLIENT": client_type} if client_type else {}
        return self.client.get("/api/v1/devices",
                               HTTP_AUTHORIZATION=f"Bearer {access}", **headers)

    def delete_device(self, access, client_type):
        """下线指定端。

        Args:
            access: access token 原文。
            client_type: 路径里的端类型。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.delete(f"/api/v1/devices/{client_type}",
                                  HTTP_AUTHORIZATION=f"Bearer {access}")

    def get_me(self, access):
        """用给定 access 请求 ``GET /users/me``。

        Args:
            access: access token 原文。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.get("/api/v1/users/me",
                               HTTP_AUTHORIZATION=f"Bearer {access}")


class DeviceListTests(DeviceApiTestCase):
    """列表:只列登录过的端,``current`` 由请求头判定。"""

    def test_lists_both_clients_with_labels(self):
        """App + Web 各一行,标签取自模型 choices,``current`` 只有一行是 true。"""
        self.login(CLIENT_APP)
        access_web = self.login(CLIENT_WEB).data["access"]

        response = self.get_devices(access_web, CLIENT_WEB)
        self.assertEqual(response.status_code, 200)
        rows = response.data["results"]
        self.assertEqual([row["client_type"] for row in rows], [CLIENT_APP, CLIENT_WEB])
        self.assertEqual([row["client_label"] for row in rows], ["App", "网页端"])
        self.assertEqual([row["current"] for row in rows], [False, True])
        for row in rows:
            self.assertIsNotNone(row["created_at"])
            self.assertIsNotNone(row["last_active_at"])

    def test_current_follows_request_header(self):
        """同一个 token 换成 ``X-Client: app`` 时 ``current`` 落在 app 那行。"""
        access_app = self.login(CLIENT_APP).data["access"]
        self.login(CLIENT_WEB)

        rows = self.get_devices(access_app, CLIENT_APP).data["results"]
        currents = {row["client_type"]: row["current"] for row in rows}
        self.assertEqual(currents, {CLIENT_APP: True, CLIENT_WEB: False})

    def test_missing_header_counts_as_app(self):
        """不带 ``X-Client`` 时 ``current`` 按 app 判定(与签发令牌同口径)。"""
        self.login(CLIENT_APP)
        access_web = self.login(CLIENT_WEB).data["access"]

        rows = self.get_devices(access_web, None).data["results"]
        currents = {row["client_type"]: row["current"] for row in rows}
        self.assertEqual(currents, {CLIENT_APP: True, CLIENT_WEB: False})

    def test_unused_client_is_absent(self):
        """只登录过 App 时,Web 那行不存在(最多两行,且不返回空端)。"""
        access = self.login(CLIENT_APP).data["access"]
        rows = self.get_devices(access).data["results"]
        self.assertEqual([row["client_type"] for row in rows], [CLIENT_APP])

    def test_requires_authentication(self):
        """未带令牌 → 401。"""
        self.assertEqual(self.client.get("/api/v1/devices").status_code, 401)


class DeviceLogoutTests(DeviceApiTestCase):
    """单端下线:该端失效、另一端仍可用、幂等、非法端类型。"""

    def test_kick_web_keeps_app_alive(self):
        """踢 web 后 web 的 access 401/40101,app 的 access 仍 200。"""
        access_app = self.login(CLIENT_APP).data["access"]
        access_web = self.login(CLIENT_WEB).data["access"]

        with patch("im.tasks.kick_device.delay") as kick:
            response = self.delete_device(access_app, CLIENT_WEB)
        self.assertEqual(response.status_code, 204)
        kick.assert_called_once_with(self.user.id, CLIENT_WEB)   # 走队列,不直连 IM

        web_after = self.get_me(access_web)
        self.assertEqual(web_after.status_code, 401)
        self.assertEqual(web_after.data["code"], 40101)
        self.assertEqual(self.get_me(access_app).status_code, 200)

    def test_kick_current_client_is_allowed(self):
        """踢当前这一端等同注销本端:自己的 access 随即 401。"""
        access_app = self.login(CLIENT_APP).data["access"]
        with patch("im.tasks.kick_device.delay"):
            self.assertEqual(self.delete_device(access_app, CLIENT_APP).status_code, 204)
        self.assertEqual(self.get_me(access_app).status_code, 401)

    def test_repeat_kick_is_idempotent(self):
        """重复踢同一端仍 204(已下线 / 从未登录过都不报错)。"""
        access_app = self.login(CLIENT_APP).data["access"]
        with patch("im.tasks.kick_device.delay") as kick:
            self.assertEqual(self.delete_device(access_app, CLIENT_WEB).status_code, 204)
            self.assertEqual(self.delete_device(access_app, CLIENT_WEB).status_code, 204)
        self.assertEqual(kick.call_count, 2)

    def test_invalid_client_type_is_rejected(self):
        """非法端类型 → 400 + 40001,且不入队踢人。"""
        access = self.login(CLIENT_APP).data["access"]
        with patch("im.tasks.kick_device.delay") as kick:
            response = self.delete_device(access, "pad")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], 40001)
        kick.assert_not_called()

    def test_kick_requires_authentication(self):
        """未带令牌 → 401,不会改任何版本。"""
        with patch("im.tasks.kick_device.delay") as kick:
            response = self.client.delete("/api/v1/devices/web")
        self.assertEqual(response.status_code, 401)
        kick.assert_not_called()


class LastActiveTests(TestCase):
    """``last_active_at`` 只在登录与刷新成功时更新,且按端各记各的。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800000002"
        self.user = User.objects.create_user(phone=self.phone)

    def _login(self, client_type):
        """落码后走一次校验登录。

        Args:
            client_type: ``app`` / ``web``。

        Returns:
            DRF 测试客户端的响应对象。
        """
        cache.delete(f"sms:send:{self.phone}")
        sms_codes.store(self.phone, settings.SMS_DEV_CODE)
        return self.client.post(
            "/api/v1/auth/sms/verify",
            {"phone": self.phone, "code": settings.SMS_DEV_CODE}, format="json",
            HTTP_X_CLIENT=client_type)

    def _row(self, client_type):
        """取该端的端会话行。

        Args:
            client_type: ``app`` / ``web``。

        Returns:
            ``DeviceSession`` 实例。
        """
        return DeviceSession.objects.get(user=self.user, client_type=client_type)

    def test_login_stamps_last_active(self):
        """登录成功后该端有 ``last_active_at``。"""
        self._login(CLIENT_APP)
        self.assertIsNotNone(self._row(CLIENT_APP).last_active_at)

    def test_refresh_advances_last_active_only_for_own_client(self):
        """刷新只推进本端时间:web 刷新不动 app 的那一行。"""
        self._login(CLIENT_APP)
        self._login(CLIENT_WEB)
        stale = timezone.now() - timedelta(days=2)
        DeviceSession.objects.filter(user=self.user).update(last_active_at=stale)

        refreshed = self.client.post("/api/v1/auth/token/refresh", {}, format="json")
        self.assertEqual(refreshed.status_code, 200)

        web_row = self._row(CLIENT_WEB)
        app_row = self._row(CLIENT_APP)
        self.assertGreater(web_row.last_active_at, stale)
        self.assertEqual(app_row.last_active_at, stale)   # 端维度不串

    def test_failed_refresh_does_not_touch(self):
        """没有可用 refresh 时不写库(否则「随便点一下」也算活跃)。"""
        self._login(CLIENT_APP)
        stale = timezone.now() - timedelta(days=2)
        DeviceSession.objects.filter(user=self.user).update(last_active_at=stale)

        response = self.client.post("/api/v1/auth/token/refresh", {}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self._row(CLIENT_APP).last_active_at, stale)
