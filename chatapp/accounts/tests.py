"""账号与鉴权应用的测试。

覆盖场景:
    - 建号管理器(手机号建号、admin 建号);
    - 健康检查与就绪探针(数据库/Redis 任一不可用时返回 503);
    - 发码:落码、60 秒重发间隔、入队失败回滚、手机号格式、IP 限流;
    - 校验登录:自动建号、幂等重放、错误/过期、连错锁定、IP 限流、响应头;
    - 验证码状态机(HMAC 存储、重放窗口、锁定、不存明文);
    - IM 账号约定 ``u{id}``、新用户导入与老用户「待踢旧会话」标记;
    - 令牌刷新与单设备登录(第二次登录作废第一个设备的两类令牌);
    - Web 的 Cookie 分支(登录/刷新/注销、轮换宽限);
    - 造数命令(资料完善、生日不小于 18 岁、号码续编、号池耗尽);
    - 认证通过时刷新在线状态。
"""

import base64
from datetime import date
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import F
from django.test import SimpleTestCase, TestCase, override_settings
from django_redis import get_redis_connection
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from accounts import services, sms_codes
from accounts import totp
from accounts.management.commands.seed_fake_users import Command
from im import tasks as im_tasks
from accounts.throttles import SmsSendThrottle
from accounts.tokens import SessionRefreshToken
from users.models import Photo, PhotoStatus, Profile, ProfileStatus, calculate_age

User = get_user_model()

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32   # 最小假 JPEG 内容(不校验格式,只当字节存)


class UserManagerTests(TestCase):
    """建号管理器:普通用户无可用密码,超级用户有真实密码。"""

    def test_create_user_requires_phone(self):
        user = User.objects.create_user(phone="13800138000")
        self.assertEqual(user.phone, "13800138000")
        self.assertFalse(user.has_usable_password())  # 验证码登录:无密码

    def test_create_superuser(self):
        admin = User.objects.create_superuser(phone="13900139000", password="admin-pass")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)


class HealthTests(APITestCase):
    """存活探针:不触碰数据库与 Redis,恒定返回 ok。"""

    def test_health_ok(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_throttled(self):
        """探针按 IP 限流,超限 429(L1)。"""
        from accounts.throttles import ProbeThrottle

        cache.clear()
        with patch.object(ProbeThrottle, "rate", "2/hour", create=True):
            self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
            self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
            self.assertEqual(self.client.get("/api/v1/health").status_code, 429)


class ReadyZTests(APITestCase):
    """就绪探针:逐项探测数据库与 Redis,任一不可用即 503。"""

    def test_readyz_ok(self):
        resp = self.client.get("/api/v1/readyz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok", "checks": {"db": "ok", "redis": "ok"}})

    def test_readyz_db_down_returns_503(self):
        with patch("accounts.views._probe_db", side_effect=RuntimeError("db down")):
            resp = self.client.get("/api/v1/readyz")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["checks"], {"db": "error", "redis": "ok"})

    def test_readyz_redis_down_returns_503(self):
        with patch("accounts.views._probe_redis", side_effect=RuntimeError("redis down")):
            resp = self.client.get("/api/v1/readyz")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["checks"], {"db": "ok", "redis": "error"})


class SmsSendTests(APITestCase):
    """发送验证码:落码、重发间隔、入队失败回滚、格式校验与 IP 限流。"""

    def setUp(self):
        cache.clear()               # 缓存是进程级的,测试之间必须清
        self.addCleanup(cache.clear)

    def test_send_stores_code_and_returns_ok(self):
        with patch("notifications.tasks.send_sms_code.delay") as delay:
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        self.assertIs(sms_codes.verify("13800138000", "123456"), sms_codes.CodeResult.OK)
        delay.assert_called_once_with("13800138000", "123456")

    def test_send_twice_within_interval_is_throttled(self):
        with patch("notifications.tasks.send_sms_code.delay"):
            self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["code"], 42901)
        self.assertIn("Retry-After", resp.headers)

    def test_enqueue_failure_rolls_back_and_returns_503(self):
        with patch("notifications.tasks.send_sms_code.delay", side_effect=Exception("broker down")):
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["code"], 50301)
        # 已回滚:立刻重发应成功(而不是被 60 秒间隔卡住)
        with patch("notifications.tasks.send_sms_code.delay"):
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 200)

    def test_send_invalid_phone_rejected(self):
        resp = self.client.post("/api/v1/auth/sms/send", {"phone": "12345"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 400)

    def test_send_ip_throttle(self):
        # DRF 的 THROTTLE_RATES 是类属性快照,测试里直接临时改 rate 才生效
        with patch.object(SmsSendThrottle, "rate", "2/hour", create=True):
            for i in range(2):
                resp = self.client.post("/api/v1/auth/sms/send", {"phone": f"1380013800{i}"}, format="json")
                self.assertEqual(resp.status_code, 200)
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138009"}, format="json")
            self.assertEqual(resp.status_code, 429)


class SmsVerifyTests(APITestCase):
    """校验验证码并登录:建号、令牌、错误分支、锁定、重放与限流。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def issue_code(self, phone=None):
        """直接往 Redis 里放一个验证码,绕开 60 秒重发间隔。

        Args:
            phone: 目标手机号;``None`` 表示用 ``self.phone``。

        Returns:
            写入的验证码(开发模式下固定为 ``settings.SMS_DEV_CODE``)。
        """
        phone = phone or self.phone
        cache.delete(f"sms:send:{phone}")   # 测试里绕过 60 秒重发间隔的服务端占位
        sms_codes.store(phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE

    def verify(self, code, phone=None):
        """调用校验接口。

        Args:
            code: 提交的验证码。
            phone: 目标手机号;``None`` 表示用 ``self.phone``。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": phone or self.phone, "code": code}, format="json")

    def test_verify_creates_user_and_returns_tokens(self):
        code = self.issue_code()
        resp = self.verify(code)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_new_user"])
        user = User.objects.get(phone=self.phone)
        self.assertEqual(data["user_id"], user.id)
        self.assertEqual(AccessToken(data["access"])["user_id"], str(user.id))  # claim 是字符串

    def test_verify_second_time_is_not_new_user(self):
        self.verify(self.issue_code())
        code = self.issue_code()
        resp = self.verify(code)
        self.assertFalse(resp.json()["is_new_user"])
        self.assertEqual(User.objects.filter(phone=self.phone).count(), 1)

    def test_verify_wrong_code(self):
        self.issue_code()
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 40002)
        self.assertFalse(User.objects.filter(phone=self.phone).exists())

    def test_verify_expired_code(self):
        resp = self.verify("123456")   # 从没发过码
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 40001)

    def test_lock_after_five_failures(self):
        code = self.issue_code()
        for _ in range(5):
            self.verify("000000")
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["code"], 42902)
        resp = self.verify(code)       # 锁定期间即使码对也不行
        self.assertEqual(resp.status_code, 429)

    def test_replay_within_window_issues_new_tokens(self):
        code = self.issue_code()
        first = self.verify(code)
        self.assertEqual(first.status_code, 200)
        second = self.verify(code)     # 60 秒重放窗口内:同码可再换令牌
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["access"], second.json()["access"])

    def test_verify_ip_throttle(self):
        from accounts.throttles import SmsVerifyThrottle
        with patch.object(SmsVerifyThrottle, "rate", "3/hour", create=True):
            for i in range(3):
                resp = self.verify("000000", phone=f"1380013800{i}")
                self.assertEqual(resp.status_code, 400)   # 码错(限流额度内)
            resp = self.verify("000000", phone="13800138009")
        self.assertEqual(resp.status_code, 429)

    def test_lock_response_carries_retry_after(self):
        self.issue_code()
        for _ in range(settings.SMS_MAX_ATTEMPTS):
            self.verify("000000")
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.headers.get("Retry-After"), str(settings.SMS_LOCK_TTL))

    def test_verify_path_never_calls_im_rest(self):
        """响应路径零外部调用:登录成功只入队任务,绝不同步打腾讯(第 1 期铁律的回归)。"""
        code = self.issue_code()
        with patch("im.client._request") as rest, patch("im.tasks.import_account.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify(code)
        self.assertEqual(resp.status_code, 200)
        rest.assert_not_called()


class SmsCodeStateTests(TestCase):
    """验证码状态机:HMAC 存储 + Lua 原子校验 + 重放窗口。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def test_store_then_verify_ok(self):
        sms_codes.store(self.phone, "123456")
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.OK)

    def test_verify_wrong_code(self):
        sms_codes.store(self.phone, "123456")
        self.assertIs(sms_codes.verify(self.phone, "000000"), sms_codes.CodeResult.WRONG)

    def test_verify_without_code_is_expired(self):
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.EXPIRED)

    def test_five_wrong_attempts_lock(self):
        sms_codes.store(self.phone, "123456")
        for _ in range(settings.SMS_MAX_ATTEMPTS - 1):
            self.assertIs(sms_codes.verify(self.phone, "000000"), sms_codes.CodeResult.WRONG)
        self.assertIs(sms_codes.verify(self.phone, "000000"), sms_codes.CodeResult.JUST_LOCKED)
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.LOCKED)

    def test_success_shrinks_ttl_to_replay_window_and_allows_replay(self):
        sms_codes.store(self.phone, "123456")
        sms_codes.verify(self.phone, "123456")
        ttl = get_redis_connection("default").ttl(f"sms:code:{self.phone}")
        self.assertLessEqual(ttl, settings.SMS_REPLAY_TTL)
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.OK)

    def test_code_is_not_stored_in_plaintext(self):
        sms_codes.store(self.phone, "123456")
        stored = get_redis_connection("default").hgetall(f"sms:code:{self.phone}")
        self.assertNotIn(b"123456", stored.values())


class ImUserIdTests(TestCase):
    """IM 账号约定:一律是 ``u{账号 id}``。"""

    def test_im_user_id_is_u_prefixed_id(self):
        user = User.objects.create_user(phone="13800138000")
        self.assertEqual(user.im_user_id, f"u{user.id}")


class ImImportOnRegisterTests(APITestCase):
    """登录时的 IM 副作用:新用户导入、老用户标记待踢、入队失败不阻断登录。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def issue_code(self):
        """直接落一个验证码,绕开重发间隔。

        Returns:
            写入的验证码。
        """
        cache.delete(f"sms:send:{self.phone}")
        sms_codes.store(self.phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE

    def verify(self):
        """走一次完整的校验登录流程。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": self.phone, "code": self.issue_code()}, format="json")

    def test_new_user_triggers_import(self):
        with patch("im.tasks.import_account.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify()
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(phone=self.phone)
        delay.assert_called_once_with(user.id)

    def test_existing_login_marks_kick_pending(self):
        self.verify()
        user = User.objects.get(phone=self.phone)
        cache.delete(im_tasks.kick_pending_key(user.id))
        with patch("im.tasks.kick_pending.apply_async") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                self.verify()
        self.assertEqual(cache.get(im_tasks.kick_pending_key(user.id)), 1)
        enqueue.assert_called_once_with(args=[user.id],
                                        countdown=im_tasks.KICK_BACKSTOP_DELAY)

    def test_enqueue_failure_does_not_break_login(self):
        with patch("im.tasks.import_account.delay", side_effect=Exception("broker down")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify()
        self.assertEqual(resp.status_code, 200)   # on_commit(robust=True)兜住


class TokenRefreshTests(APITestCase):
    """刷新令牌:换发新的 access + refresh,旧 refresh 立即进黑名单。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")

    def test_refresh_rotates_and_returns_new_pair(self):
        old = str(SessionRefreshToken.for_user(self.user))
        resp = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.json())
        new = resp.json()["refresh"]
        self.assertNotEqual(new, old)
        # 新 refresh 可以继续换发下一轮
        again = self.client.post("/api/v1/auth/token/refresh", {"refresh": new}, format="json")
        self.assertEqual(again.status_code, 200)

    def test_reuse_within_grace_returns_same_new_pair(self):
        """多标签页并发刷新:后到者拿旧 token 仍能拿到同一对新令牌。"""
        old = str(SessionRefreshToken.for_user(self.user))
        first = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        new = first.json()["refresh"]
        second = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["refresh"], new)
        self.assertIn("access", second.json())

    @override_settings(REFRESH_REUSE_GRACE=0)
    def test_reuse_after_grace_is_rejected(self):
        """超出宽限期的重复使用视为泄露重放。"""
        old = str(SessionRefreshToken.for_user(self.user))
        self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        again = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(again.status_code, 401)
        self.assertEqual(again.json()["code"], 401)

    def test_grace_does_not_revive_kicked_session(self):
        """宽限期不能绕过单设备登录:账号已被顶下线时旧 token 仍然 40101。"""
        old = str(SessionRefreshToken.for_user(self.user))
        self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        User.objects.filter(pk=self.user.pk).update(session_version=F("session_version") + 1)
        again = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(again.status_code, 401)
        self.assertEqual(again.json()["code"], 40101)

    def test_missing_refresh_is_rejected(self):
        resp = self.client.post("/api/v1/auth/token/refresh", {}, format="json")
        self.assertEqual(resp.status_code, 401)


class WebCookieAuthTests(APITestCase):
    """Web 分支:refresh 走 HttpOnly Cookie,响应体不返回 refresh。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"
        self.user = User.objects.create_user(phone=self.phone)

    def issue_code(self):
        """绕过 60 秒重发间隔写入验证码。

        Returns:
            写入的验证码(开发模式下固定为 ``settings.SMS_DEV_CODE``)。
        """
        cache.delete(f"sms:send:{self.phone}")
        sms_codes.store(self.phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE

    def web_login(self):
        """带 ``X-Client: web`` 走一次校验登录。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": self.phone, "code": self.issue_code()},
                                format="json", HTTP_X_CLIENT="web")

    def test_web_login_sets_cookie_and_hides_refresh(self):
        resp = self.web_login()
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("refresh", resp.json())
        cookie = resp.cookies[settings.REFRESH_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/api/v1/auth/")
        self.assertTrue(cookie.value)

    def test_app_login_returns_refresh_without_cookie(self):
        resp = self.client.post("/api/v1/auth/sms/verify",
                                {"phone": self.phone, "code": self.issue_code()}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("refresh", resp.json())
        self.assertNotIn(settings.REFRESH_COOKIE_NAME, resp.cookies)

    def test_cookie_refresh_rotates_and_sets_new_cookie(self):
        raw = self.web_login().cookies[settings.REFRESH_COOKIE_NAME].value
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        resp = self.client.post("/api/v1/auth/token/refresh", {}, format="json",
                                HTTP_X_CLIENT="web")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.json())
        self.assertNotIn("refresh", resp.json())
        rotated = resp.cookies[settings.REFRESH_COOKIE_NAME].value
        self.assertNotEqual(rotated, raw)

    def test_cookie_refresh_without_client_header_still_works(self):
        """带了 Cookie 就按 Web 处理,不强制要求 X-Client 头(容错)。"""
        raw = self.web_login().cookies[settings.REFRESH_COOKIE_NAME].value
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        resp = self.client.post("/api/v1/auth/token/refresh", {}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("refresh", resp.json())

    def test_logout_blacklists_refresh_and_clears_cookie(self):
        raw = self.web_login().cookies[settings.REFRESH_COOKIE_NAME].value
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        resp = self.client.post("/api/v1/auth/logout", {}, format="json", HTTP_X_CLIENT="web")
        self.assertEqual(resp.status_code, 204)
        cleared = resp.cookies[settings.REFRESH_COOKIE_NAME]
        self.assertEqual(cleared["max-age"], 0)
        # 被拉黑后不能再刷新
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        again = self.client.post("/api/v1/auth/token/refresh", {}, format="json",
                                 HTTP_X_CLIENT="web")
        self.assertEqual(again.status_code, 401)

    def test_logout_is_idempotent(self):
        resp = self.client.post("/api/v1/auth/logout", {}, format="json")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.cookies[settings.REFRESH_COOKIE_NAME]["max-age"], 0)


class SingleDeviceSessionTests(APITestCase):
    """单设备登录:后登录的设备作废先登录设备的 access/refresh(40101)。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def login(self):
        """走一次完整的校验登录,返回响应。

        Returns:
            DRF 测试客户端的响应对象,``json()`` 内含 access / refresh。
        """
        cache.delete(f"sms:send:{self.phone}")   # 绕过 60 秒重发间隔的服务端占位
        code = settings.SMS_DEV_CODE
        sms_codes.store(self.phone, code)
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": self.phone, "code": code}, format="json")

    def test_second_login_invalidates_first_access_token(self):
        first = self.login().json()["access"]
        second = self.login().json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {first}")
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], 40101)
        self.assertIn("其他设备", resp.json()["message"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {second}")
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 200)

    def test_second_login_invalidates_first_refresh_token(self):
        first_refresh = self.login().json()["refresh"]
        self.login()
        resp = self.client.post("/api/v1/auth/token/refresh", {"refresh": first_refresh}, format="json")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], 40101)

class SeedFakeUsersTests(TestCase):
    """造数命令 seed_fake_users:建「资料已完善 + 过审照片」的女号(手测发现页用)。"""

    def setUp(self):
        self.origin = User.objects.create_user(phone="13800138000")
        self.im = patch("accounts.management.commands.seed_fake_users.im_client")
        self.im_mock = self.im.start()
        self.addCleanup(self.im.stop)
        self.dl = patch("accounts.management.commands.seed_fake_users._download", return_value=JPEG)
        self.dl_mock = self.dl.start()
        self.addCleanup(self.dl.stop)

    def seed(self, count):
        """跑一次造数命令。

        Args:
            count: 要创建的人数。
        """
        call_command("seed_fake_users", count=count, stdout=None)

    def created(self, origin_id):
        """取出本次造数新建的用户。

        Args:
            origin_id: 造数前已存在的最大用户 id。

        Returns:
            新建的用户列表,按 id 升序。
        """
        return list(User.objects.filter(id__gt=origin_id).order_by("id"))

    def test_creates_complete_female_profiles_with_photos(self):
        self.seed(3)
        users = self.created(self.origin.id)
        self.assertEqual(len(users), 3)

        # 号码段从 13900000001 起,按序分配
        self.assertEqual([u.phone for u in users], ["13900000001", "13900000002", "13900000003"])
        for user in users:
            profile = user.profile
            self.assertEqual(profile.gender, "female")
            self.assertEqual(profile.status, ProfileStatus.COMPLETE)
            self.assertTrue(profile.nickname and profile.city and profile.bio and profile.birthday)
            self.assertGreaterEqual(profile.age, 18)
            self.assertLessEqual(profile.age, 45)
            self.assertGreaterEqual(profile.tags.count(), 1)
            self.assertEqual(profile.preference.target_gender, "male")

            photos = list(user.photos.all())
            self.assertEqual(len(photos), 2)
            self.assertEqual([p.status for p in photos], [PhotoStatus.APPROVED] * 2)
            self.assertEqual([p.order for p in photos], [0, 1])
            self.assertTrue(all(p.file.name for p in photos))

            # IM 三件事:导入账号、同步昵称、同步头像
            self.im_mock.ensure_account.assert_any_call(user.im_user_id, profile.nickname)
            self.im_mock.set_profile_nick.assert_any_call(user.im_user_id, profile.nickname)
            self.im_mock.set_profile_avatar.assert_any_call(user.im_user_id, photos[0].file.url)

    def test_random_birthday_never_yields_under_18(self):
        """回归(2026-10-13 CI 实测红):抽到 age=18 且月/日取到「晚于今天」的最坏值时,算出来是 17。

        造数命令承诺 18–45,但「age 年前的随机月/日」在**今年的生日还没过**时会被
        `calculate_age` 算成 age-1 —— 于是可能造出未满 18 岁的账号(平台明令禁止)。
        这里把随机源钉在「最坏组合」:年龄取下界 18,月与日都取各自上界。
        """
        cmd = Command()
        today = date(2026, 10, 13)

        def worst_case(a, b):
            return 18 if (a, b) == (18, 45) else b   # 年龄取下界;其余一律取上界

        with patch("accounts.management.commands.seed_fake_users.random.randint",
                   side_effect=worst_case), \
                patch("django.utils.timezone.localdate", return_value=today):
            birthday = cmd._random_birthday()

        self.assertEqual(calculate_age(birthday, today=today), 18,
                         msg=f"birthday={birthday}")

    def test_rerun_continues_after_existing_numbers(self):
        # 号码从「已分配的最大序号 + 1」续编;跑满 99 后再跑 = 号码段耗尽
        self.seed(3)
        self.seed(3)
        users = self.created(self.origin.id)
        self.assertEqual([u.phone for u in users],
                         ["13900000001", "13900000002", "13900000003",
                          "13900000004", "13900000005", "13900000006"])
        self.assertEqual(User.objects.count(), 7)   # 没有重复建号

    def test_phone_pool_overflow_raises(self):
        User.objects.create_user(phone="13900000099")   # 占满号码段末位
        with self.assertRaises(CommandError):
            self.seed(3)

    def test_skip_im_still_creates_users(self):
        call_command("seed_fake_users", count=2, skip_im=True, stdout=None)
        self.assertEqual(len(self.created(self.origin.id)), 2)
        self.im_mock.ensure_account.assert_not_called()



class PresenceHookTests(APITestCase):
    """在线状态钩子:认证通过即刷新,匿名与被顶号的旧令牌都不算活跃。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")

    def _login(self):
        """给测试客户端装上当前用户的令牌。"""
        token = SessionRefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_authenticated_request_touches_presence(self):
        self._login()
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(cache.get(f"presence:{self.user.id}"))

    def test_anonymous_request_does_not_touch(self):
        self.client.get("/api/v1/health")
        self.assertIsNone(cache.get(f"presence:{self.user.id}"))

    def test_rejected_stale_token_does_not_touch(self):
        # 被顶号的旧令牌(40101)不算一次「活跃」
        self._login()
        self.user.session_version += 1
        self.user.save(update_fields=["session_version"])
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 401)
        self.assertIsNone(cache.get(f"presence:{self.user.id}"))


class TotpTests(SimpleTestCase):
    """TOTP:标准测试向量、时间窗、密钥与 otpauth 地址(H6)。"""

    def test_matches_rfc6238_sha1_vector(self):
        """RFC 6238 的 SHA1 向量(取 6 位)必须一致。"""
        secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        self.assertEqual(totp.code_at(secret, 59), "287082")

    def test_verify_allows_one_step_window(self):
        """前后一个时间步内都算有效,超出则拒绝。"""
        secret = totp.generate_secret()
        code = totp.code_at(secret, 1_700_000_000)
        self.assertTrue(totp.verify(secret, code, moment=1_700_000_000))
        self.assertTrue(totp.verify(secret, code, moment=1_700_000_030))
        self.assertFalse(totp.verify(secret, code, moment=1_700_000_120))
        self.assertFalse(totp.verify(secret, "000000", moment=1_700_000_000))

    def test_provisioning_uri_contains_secret_and_issuer(self):
        """otpauth 地址要带密钥、发行方与 6 位/30 秒参数。"""
        uri = totp.provisioning_uri("ABC234", "13800138000")
        self.assertTrue(uri.startswith("otpauth://totp/"))
        self.assertIn("secret=ABC234", uri)
        self.assertIn("issuer=chat_app", uri)
        self.assertIn("digits=6", uri)
        self.assertIn("period=30", uri)


class LoginThrottleTests(TestCase):
    """后台登录失败锁定:账号维度达到上限后,正确密码也拒绝(H6)。"""

    def setUp(self):
        """建一个可登录的运营账号,并清空失败计数。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.staff = User.objects.create_user(phone="13700137000", is_staff=True)
        self.staff.set_password("ops-pass-123")
        self.staff.save(update_fields=["password"])

    def test_locks_after_max_attempts(self):
        """连续 5 次错密码后,第 6 次即使密码正确也返回 None。"""
        for _ in range(5):
            self.assertIsNone(authenticate(username="13700137000", password="wrong"))
        self.assertIsNone(authenticate(username="13700137000", password="ops-pass-123"))
        self.assertEqual(int(cache.get("ops:login:fail:account:13700137000")), 5)

    def test_success_clears_account_counter(self):
        """失败几次后登录成功,账号维度的计数被清空。"""
        for _ in range(3):
            authenticate(username="13700137000", password="wrong")
        self.assertIsNotNone(authenticate(username="13700137000", password="ops-pass-123"))
        self.assertIsNone(cache.get("ops:login:fail:account:13700137000"))
