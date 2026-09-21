import tempfile
from pathlib import Path

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


class ApiDocCoverageLogicTests(SimpleTestCase):
    """检查模块自身的单元测试(用临时目录,不依赖真实文档)。"""

    def test_normalize_route_params(self):
        from config.api_doc_coverage import normalize_route

        self.assertEqual(normalize_route("me/photos/<int:photo_id>"),
                         "me/photos/{photo_id}")
        self.assertEqual(normalize_route("blocks/<int:user_id>"),
                         "blocks/{user_id}")

    def test_endpoints_from_urlconf_covers_api_v1(self):
        from config.api_doc_coverage import endpoints_from_urlconf

        found = endpoints_from_urlconf()
        self.assertIn(("GET", "/api/v1/users/me"), found)
        self.assertIn(("PATCH", "/api/v1/users/me"), found)
        self.assertIn(("DELETE", "/api/v1/users/me/photos/{photo_id}"), found)
        self.assertIn(("POST", "/api/v1/auth/token/refresh"), found)
        # ops/admin 不在 /api/v1 下,不应被枚举到
        self.assertFalse(any(p.startswith("/ops") for _, p in found))

    def test_endpoints_from_docs_parses_info_line(self):
        from config.api_doc_coverage import endpoints_from_docs

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.md"
            path.write_text(
                "# 演示分册\n\n"
                "### 1.1 演示接口\n\n"
                "> `POST` `/api/v1/demo/thing` · 需要鉴权 · 无额外限流\n\n"
                "正文里提到 `GET /api/v1/other` 不算信息行。\n",
                encoding="utf-8")
            found = endpoints_from_docs(Path(tmp))
        self.assertEqual(set(found), {("POST", "/api/v1/demo/thing")})

    def test_fenced_code_blocks_are_ignored(self):
        """代码围栏里的示例(如 README 的模板样例)不算文档标记。"""
        from config.api_doc_coverage import endpoints_from_docs

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "demo.md").write_text(
                "# 模板说明\n\n"
                "```markdown\n"
                "> `POST` `/api/v1/example/thing` · 需要鉴权 · 无额外限流\n"
                "```\n",
                encoding="utf-8")
            found = endpoints_from_docs(Path(tmp))
        self.assertEqual(found, {})

    def test_find_problems_reports_both_directions(self):
        from config.api_doc_coverage import find_problems

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "demo.md").write_text(
                "> `GET` `/api/v1/demo/gone` · 需要鉴权 · 无额外限流\n",
                encoding="utf-8")
            problems = find_problems(Path(tmp))
        joined = "\n".join(problems)
        self.assertIn("未写文档", joined)            # URLconf 有、文档没有
        self.assertIn("/api/v1/demo/gone", joined)   # 文档有、URLconf 没有
