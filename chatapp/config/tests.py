from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django_redis import get_redis_connection
from rest_framework.test import APITestCase

from config.celery import ping


class ErrorEnvelopeTests(APITestCase):
    def test_error_response_uses_code_message_envelope(self):
        resp = self.client.post("/api/v1/health")  # health 只允许 GET,触发 405
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json()["code"], 405)
        self.assertIn("message", resp.json())


class CacheBackendTests(TestCase):
    def test_default_cache_is_redis_and_roundtrips(self):
        self.assertIn("django_redis", settings.CACHES["default"]["BACKEND"])
        cache.set("cache:smoke", "ok", 10)
        self.assertEqual(cache.get("cache:smoke"), "ok")

    def test_testing_uses_isolated_redis_db(self):
        db = get_redis_connection("default").connection_pool.connection_kwargs["db"]
        self.assertEqual(db, 15)   # 测试绝不写开发库(DB0)


class CelerySkeletonTests(TestCase):
    def test_ping_task_returns_pong(self):
        self.assertEqual(ping.apply().get(), "pong")

    def test_broker_uses_isolated_db_in_tests(self):
        # ⚠️ Celery 的 broker_url 属性会优先读环境变量 CELERY_BROKER_URL,
        # 所以 .env 里的键必须叫 BROKER_URL,否则测试任务会漏进开发 broker(DB1)
        from config.celery import app
        self.assertTrue(app.conf.broker_url.endswith("/14"),
                        f"测试 broker 应指向 DB14,实际: {app.conf.broker_url}")
