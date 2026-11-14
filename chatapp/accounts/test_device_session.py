"""多端在线的端会话表与按端鉴权(批次 K / K-1)。

覆盖工单验收的六条:
    1. App 登录后 Web 登录,App 的 access 仍 200;
    2. 同端第二次登录顶掉前一个(401 + 40101);
    3. ``version_of`` 两端各一行、互不覆盖;
    4. 老令牌(不带 ``ct`` claim)仍能通过鉴权;
    5. Web 的 refresh 换出的 access 仍是 web 端,不会把 App 顶掉;
    6. ``logout/all`` 之后两端 access 都 401。

外加 Task 2 的两条:「待踢旧会话」标记按端、``user_sig`` 只踢本端。

文件信息:
    文件名称          accounts/test_device_session.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from accounts import sms_codes
from accounts.device_session import CLIENT_APP, CLIENT_WEB, version_of
from accounts.models import User
from im.tasks import kick_pending_key


class DeviceSessionTestCase(APITestCase):
    """公共夹具:一个账号 + 走真实短信登录链路的辅助方法。"""

    def setUp(self):
        """准备干净缓存与一个测试账号,每个用例前重建。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800000001"
        self.user = User.objects.create_user(phone=self.phone)

    def issue_code(self):
        """直接落一个验证码,绕开 60 秒重发间隔。

        参数说明:
            无。

        返回参数:
            写入的验证码(开发期固定码)。

        使用示例:
            ``self.issue_code()``

        备注信息:
            先删 ``sms:send:{phone}`` 占位键,否则第二次发码会被 60 秒间隔挡下。
        """
        cache.delete(f"sms:send:{self.phone}")
        sms_codes.store(self.phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE

    def login(self, client_type=CLIENT_APP):
        """走一次完整的校验登录。

        参数说明:
            client_type: ``app`` / ``web``;``None`` 表示不带 ``X-Client`` 头。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.login(CLIENT_WEB)``

        备注信息:
            走真实短信登录链路;``client_type`` 只决定请求头,``None`` 时按 app 兜底。
        """
        headers = {"HTTP_X_CLIENT": client_type} if client_type else {}
        return self.client.post(
            "/api/v1/auth/sms/verify",
            {"phone": self.phone, "code": self.issue_code()}, format="json", **headers)

    def get_me(self, access):
        """用给定 access 请求 ``GET /users/me``。

        参数说明:
            access: access token 原文。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.get_me(access_app)``

        备注信息:
            用它验证令牌是否还可用:被顶掉的端应返回 401 + ``40101``。
        """
        return self.client.get("/api/v1/users/me",
                               HTTP_AUTHORIZATION=f"Bearer {access}")


class DeviceSessionAuthTests(DeviceSessionTestCase):
    """一个 App + 一个网页可同时在线;同类互顶。"""

    def test_app_and_web_coexist(self):
        """App 登录后 Web 登录,App 的 access 仍然可用。

        参数说明:
            无。
        """
        access_app = self.login(CLIENT_APP).data["access"]
        access_web = self.login(CLIENT_WEB).data["access"]
        for token in (access_app, access_web):
            self.assertEqual(self.get_me(token).status_code, 200)

    def test_same_client_kicks_previous(self):
        """同端第二次登录顶掉前一个(401 + 40101)。

        参数说明:
            无。
        """
        first = self.login(CLIENT_APP).data["access"]
        self.login(CLIENT_APP)
        response = self.get_me(first)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["code"], 40101)

    def test_version_is_per_client(self):
        """两端各有一行、各数各的,互不覆盖。

        参数说明:
            无。
        """
        self.login(CLIENT_APP)
        self.login(CLIENT_APP)
        app_version = version_of(self.user.id, CLIENT_APP)
        self.assertEqual(app_version, 3)
        self.login(CLIENT_WEB)
        self.assertEqual(version_of(self.user.id, CLIENT_APP), app_version)
        self.assertEqual(version_of(self.user.id, CLIENT_WEB), 2)

    def test_legacy_token_without_ct_still_authenticates(self):
        """升级前签的老令牌没有 ct claim,按 app 兜底后仍然可用。

        参数说明:
            无。
        """
        self.login(CLIENT_APP)
        token = AccessToken.for_user(self.user)          # 老令牌:无 session_version / ct
        token["session_version"] = version_of(self.user.id, CLIENT_APP)
        self.assertEqual(self.get_me(str(token)).status_code, 200)

    def test_missing_client_header_counts_as_app(self):
        """不带 ``X-Client`` 的登录按 app 处理(线上老 APK 不能因此掉线)。

        参数说明:
            无。
        """
        self.login(None)
        self.assertEqual(version_of(self.user.id, CLIENT_APP), 2)
        self.assertIsNone(version_of(self.user.id, CLIENT_WEB))

    def test_web_refresh_stays_web(self):
        """Web 的 refresh 换出的 access 仍是 web 端,不会把 App 顶掉。

        参数说明:
            无。
        """
        self.login(CLIENT_APP)
        access_app = self.login(CLIENT_APP).data["access"]   # App 端版本 3
        web = self.login(CLIENT_WEB)                          # Web 端版本 2
        self.assertEqual(web.status_code, 200)

        refreshed = self.client.post("/api/v1/auth/token/refresh", {}, format="json")
        self.assertEqual(refreshed.status_code, 200)
        access_web = refreshed.data["access"]
        self.assertEqual(AccessToken(access_web)["ct"], CLIENT_WEB)
        # 两端都还能用:ct 若在换发时丢掉,web 的 access 会被当成 app 端(v3)而 401
        self.assertEqual(self.get_me(access_web).status_code, 200)
        self.assertEqual(self.get_me(access_app).status_code, 200)

    def test_logout_all_invalidates_both_clients(self):
        """``logout/all`` 之后两端 access 都 401。

        参数说明:
            无。
        """
        access_app = self.login(CLIENT_APP).data["access"]
        access_web = self.login(CLIENT_WEB).data["access"]
        with patch("im.tasks.kick_all_devices.delay") as kick_all:
            response = self.client.post("/api/v1/auth/logout/all",
                                        HTTP_AUTHORIZATION=f"Bearer {access_app}")
        self.assertEqual(response.status_code, 204)
        kick_all.assert_called_once_with(self.user.id)   # 踢 IM 会话走队列,响应路径不直连
        for token in (access_app, access_web):
            self.assertEqual(self.get_me(token).status_code, 401)


@override_settings(IM_SELF_WS_URL="wss://im.example/ws",
                   IM_SELF_HTTP_URL="https://im.example/api",
                   IM_SELF_SECRET="t" * 32, IM_SELF_TOKEN_TTL=86400)
class KickChainTests(DeviceSessionTestCase):
    """登录只标记本端待踢;``user_sig`` 只踢本端。"""

    def test_kick_pending_key_is_per_client(self):
        """两端各自一个标记,互不覆盖。

        参数说明:
            无。
        """
        self.assertNotEqual(kick_pending_key(7, CLIENT_APP), kick_pending_key(7, CLIENT_WEB))

    def test_user_sig_kicks_only_own_client(self):
        """``user_sig`` 只踢请求头所指那一端的旧会话,另一端的标记必须留着。

        参数说明:
            无。
        """
        access_app = self.login(CLIENT_APP).data["access"]
        cache.set(kick_pending_key(self.user.id, CLIENT_WEB), 1, 300)
        cache.set(kick_pending_key(self.user.id, CLIENT_APP), 1, 300)
        with patch("im.views.ensure_account", return_value=True), \
                patch("im.views.kick_user") as kick, \
                patch("im.views.set_session_version", return_value=True):
            response = self.client.post("/api/v1/im/user_sig", HTTP_X_CLIENT=CLIENT_APP,
                                        HTTP_AUTHORIZATION=f"Bearer {access_app}")
        self.assertEqual(response.status_code, 200)
        kick.assert_called_once_with(self.user.im_user_id, client_type=CLIENT_APP)
        self.assertIsNone(cache.get(kick_pending_key(self.user.id, CLIENT_APP)))
        self.assertIsNotNone(cache.get(kick_pending_key(self.user.id, CLIENT_WEB)))


class DeviceSessionServiceTests(TestCase):
    """服务层:版本递增在数据库内自增,首登建行返回 2。"""

    def test_bump_creates_row_and_returns_two(self):
        """首次 ``bump`` 建行并返回 2;再次 ``bump`` 返回 3。

        参数说明:
            无。
        """
        from accounts import device_session

        user = User.objects.create_user(phone="13800000002")
        self.assertIsNone(version_of(user.id, CLIENT_APP))
        self.assertEqual(device_session.bump(user, CLIENT_APP), 2)
        self.assertEqual(device_session.bump(user, CLIENT_APP), 3)
        self.assertIsNone(version_of(user.id, CLIENT_WEB))

    def test_ensure_version_does_not_bump(self):
        """``ensure_version`` 只补建行、不递增(存量账号签 IM 凭证用)。

        参数说明:
            无。
        """
        from accounts import device_session

        user = User.objects.create_user(phone="13800000003")
        self.assertEqual(device_session.ensure_version(user, CLIENT_WEB), 1)
        self.assertEqual(device_session.ensure_version(user, CLIENT_WEB), 1)
        self.assertEqual(version_of(user.id, CLIENT_WEB), 1)
