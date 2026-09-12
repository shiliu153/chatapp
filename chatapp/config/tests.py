from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
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


class RequestIdTests(APITestCase):
    def test_response_echoes_provided_request_id(self):
        resp = self.client.get("/api/v1/health", HTTP_X_REQUEST_ID="rid-123")
        self.assertEqual(resp["X-Request-Id"], "rid-123")

    def test_generates_request_id_when_absent(self):
        resp = self.client.get("/api/v1/health")
        self.assertTrue(resp["X-Request-Id"])

    def test_error_body_carries_request_id(self):
        resp = self.client.post("/api/v1/health", HTTP_X_REQUEST_ID="rid-err")   # 405
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json()["request_id"], "rid-err")

    @override_settings(REQUEST_SLOW_MS=0)
    def test_request_log_carries_request_id(self):
        with self.assertLogs("chatapp.request", level="WARNING") as captured:
            self.client.get("/api/v1/health", HTTP_X_REQUEST_ID="rid-456")
        # request_id 由 Filter 写进 record(再由 formatter 渲染),assertLogs 里看 record 属性
        self.assertEqual(captured.records[0].request_id, "rid-456")
        self.assertIn("GET /api/v1/health", captured.output[0])


class CeleryRequestIdTests(SimpleTestCase):
    def test_inject_request_id_reads_context_var(self):
        from config.celery import _inject_request_id
        from config.request_id import set_request_id

        set_request_id("rid-1")
        self.addCleanup(set_request_id, None)
        headers = {}
        _inject_request_id(headers=headers)
        self.assertEqual(headers["request_id"], "rid-1")

    def test_inject_request_id_noop_without_context(self):
        from config.celery import _inject_request_id
        from config.request_id import set_request_id

        set_request_id(None)
        headers = {}
        _inject_request_id(headers=headers)
        self.assertNotIn("request_id", headers)

    def test_bind_request_id_from_task_headers(self):
        from config.celery import _bind_request_id
        from config.request_id import current_request_id, set_request_id

        set_request_id(None)
        self.addCleanup(set_request_id, None)

        class FakeTask:
            request = type("Req", (), {"headers": {"request_id": "rid-2"}})()

        _bind_request_id(task=FakeTask())
        self.assertEqual(current_request_id(), "rid-2")
