from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from accounts import services
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
        resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        self.assertEqual(cache.get("sms:code:13800138000"), "123456")

    def test_send_twice_within_interval_is_throttled(self):
        self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["code"], 429)

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
        cache.delete(f"sms:sent:{phone}")   # 测试里绕过 60 秒重发间隔
        return services.send_code(phone)

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
        self.assertIn("message", resp.json())
        self.assertFalse(User.objects.filter(phone=self.phone).exists())

    def test_verify_expired_code(self):
        resp = self.verify("123456")   # 从没发过码
        self.assertEqual(resp.status_code, 400)

    def test_lock_after_five_failures(self):
        code = self.issue_code()
        for _ in range(5):
            self.verify("000000")
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 429)
        resp = self.verify(code)       # 锁定期间即使码对也不行
        self.assertEqual(resp.status_code, 429)


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
        cache.delete(f"sms:sent:{self.phone}")
        return services.send_code(self.phone)

    def verify(self):
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": self.phone, "code": self.issue_code()}, format="json")

    def test_new_user_triggers_im_import(self):
        with patch("accounts.views.import_account") as imp:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify()
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(phone=self.phone)
        imp.assert_called_once_with(user.im_user_id)

    def test_existing_user_does_not_trigger_import(self):
        self.verify()
        with patch("accounts.views.import_account") as imp, \
                patch("accounts.views.kick_and_logout") as kick:   # 重复登录会踢旧会话,别真打腾讯
            with self.captureOnCommitCallbacks(execute=True):
                self.verify()
        imp.assert_not_called()
        kick.assert_called_once()

    def test_im_failure_does_not_break_register(self):
        with patch("im.client._request", side_effect=Exception("im down")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(phone=self.phone).exists())


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
        cache.delete(f"sms:sent:{self.phone}")   # 绕过 60 秒重发间隔
        code = services.send_code(self.phone)
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

    def test_relogin_kicks_old_im_session(self):
        self.login()
        with patch("accounts.views.kick_and_logout") as kick:
            with self.captureOnCommitCallbacks(execute=True):
                self.login()
        user = User.objects.get(phone=self.phone)
        kick.assert_called_once_with(user.im_user_id)

    def test_first_login_does_not_kick(self):
        with patch("accounts.views.kick_and_logout") as kick:
            with self.captureOnCommitCallbacks(execute=True):
                self.login()
        kick.assert_not_called()


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

