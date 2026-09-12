from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django_redis import get_redis_connection
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from accounts import services, sms_codes
from im import tasks as im_tasks
from accounts.throttles import SmsSendThrottle
from accounts.tokens import SessionRefreshToken
from users.models import Photo, PhotoStatus, Profile, ProfileStatus

User = get_user_model()

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32   # 最小假 JPEG 内容(不校验格式,只当字节存)


class UserManagerTests(TestCase):
    def test_create_user_requires_phone(self):
        user = User.objects.create_user(phone="13800138000")
        self.assertEqual(user.phone, "13800138000")
        self.assertFalse(user.has_usable_password())  # 验证码登录:无密码

    def test_create_superuser(self):
        admin = User.objects.create_superuser(phone="13900139000", password="admin-pass")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)


class HealthTests(APITestCase):
    def test_health_ok(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


class SmsSendTests(APITestCase):
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
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def issue_code(self, phone=None):
        phone = phone or self.phone
        cache.delete(f"sms:send:{phone}")   # 测试里绕过 60 秒重发间隔的服务端占位
        sms_codes.store(phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE

    def verify(self, code, phone=None):
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
    def test_im_user_id_is_u_prefixed_id(self):
        user = User.objects.create_user(phone="13800138000")
        self.assertEqual(user.im_user_id, f"u{user.id}")


class ImImportOnRegisterTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def issue_code(self):
        cache.delete(f"sms:send:{self.phone}")
        sms_codes.store(self.phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE

    def verify(self):
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
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")

    def test_refresh_rotates_and_blacklists_old_token(self):
        old = str(SessionRefreshToken.for_user(self.user))
        resp = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.json())
        new = resp.json()["refresh"]
        self.assertNotEqual(new, old)
        again = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(again.status_code, 401)
        self.assertEqual(again.json()["code"], 401)


class SingleDeviceSessionTests(APITestCase):
    """单设备登录:后登录的设备作废先登录设备的 access/refresh(40101)。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def login(self):
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
        call_command("seed_fake_users", count=count, stdout=None)

    def created(self, origin_id):
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

