from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APITestCase

from accounts import services
from accounts.throttles import SmsSendThrottle

User = get_user_model()


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
