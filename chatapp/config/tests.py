"""config 项目的测试:错误信封、缓存、Celery 接线、请求 ID 与两套门禁。

覆盖场景:
    - 错误响应统一成 ``{code, message, request_id}`` 信封;
    - 缓存与 Celery broker 在测试期走独立 Redis DB(绝不写开发库);
    - 请求 ID 的生成、透传、写进错误体与日志,以及跨进程随消息 header 传递;
    - 接口文档门禁(``ApiDocsCoverageTests``)与注释规范门禁
      (``CommentCoverageTests``)及其检查模块自身的单元测试。
"""

import io
import json
import logging
import re
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import path
from django_redis import get_redis_connection
from PIL import Image
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.test import APITestCase
from rest_framework.views import APIView

from config import images
from config import metrics
from config import settings as settings_module
from config.celery import ping
from config.cursor import decode_cursor, encode_cursor, read_before, wants_legacy_offset
from config.exceptions import server_error
from config.net import client_ip
from config.params import int_param, optional_id


class ErrorEnvelopeTests(APITestCase):
    """错误响应信封:失败一律带 ``code`` / ``message`` / ``request_id``。"""

    def test_error_response_uses_code_message_envelope(self):
        resp = self.client.post("/api/v1/health")  # health 只允许 GET,触发 405
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json()["code"], 405)
        self.assertIn("message", resp.json())


class CacheBackendTests(TestCase):
    """默认缓存必须是 Redis,且测试期落在独立 DB。"""

    def test_default_cache_is_redis_and_roundtrips(self):
        self.assertIn("django_redis", settings.CACHES["default"]["BACKEND"])
        cache.set("cache:smoke", "ok", 10)
        self.assertEqual(cache.get("cache:smoke"), "ok")

    def test_testing_uses_isolated_redis_db(self):
        db = get_redis_connection("default").connection_pool.connection_kwargs["db"]
        self.assertEqual(db, 15)   # 测试绝不写开发库(DB0)


class CelerySkeletonTests(TestCase):
    """Celery 接线:任务可达,broker 在测试期指向独立 DB。"""

    def test_ping_task_returns_pong(self):
        self.assertEqual(ping.apply().get(), "pong")

    def test_broker_uses_isolated_db_in_tests(self):
        # 注意:Celery 的 broker_url 属性会优先读环境变量 CELERY_BROKER_URL,
        # 所以 .env 里的键必须叫 BROKER_URL,否则测试任务会漏进开发 broker(DB1)
        from config.celery import app
        self.assertTrue(app.conf.broker_url.endswith("/14"),
                        f"测试 broker 应指向 DB14,实际: {app.conf.broker_url}")


class JsonLogTests(SimpleTestCase):
    """JSON 日志:字段白名单、异常序列化、不泄漏任意 extra。"""

    def _record(self, **extra) -> logging.LogRecord:
        """构造一条带指定 extra 的日志记录。

        Args:
            **extra: 要附加到记录上的字段。

        Returns:
            ``logging.LogRecord`` 实例。
        """
        record = logging.LogRecord("chatapp.request", logging.INFO, __file__, 1,
                                   "GET /x -> 200 12ms", None, None)
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def test_whitelisted_fields_are_emitted(self):
        """约定字段全部出现,且是合法 JSON。"""
        from config.logging import JsonFormatter

        payload = json.loads(JsonFormatter().format(self._record(
            request_id="rid-1", user_id=7, route="api/v1/posts", status=200,
            duration_ms=12.5, sql_count=3)))
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["request_id"], "rid-1")
        self.assertEqual(payload["user_id"], 7)
        self.assertEqual(payload["route"], "api/v1/posts")
        self.assertEqual(payload["status"], 200)
        self.assertEqual(payload["duration_ms"], 12.5)
        self.assertEqual(payload["sql_count"], 3)
        self.assertIn("ts", payload)

    def test_unknown_extra_is_not_leaked(self):
        """白名单之外字段(可能是手机号)不能进日志。"""
        from config.logging import JsonFormatter

        payload = json.loads(JsonFormatter().format(
            self._record(phone="13800138000", request_id="rid-2")))
        self.assertNotIn("phone", payload)

    def test_client_error_fields_are_emitted(self):
        """客户端错误上报的字段(platform/client_*/app_version)必须进 JSON 日志。"""
        from config.logging import JsonFormatter

        payload = json.loads(JsonFormatter().format(self._record(
            request_id="rid-3", platform="web", app_version="1.0.2",
            user_agent="Mozilla/5.0", client_message="TypeError: x",
            client_stack="at ChatPage.vue:42", client_route="/chats/u9",
            client_request_id="abc123")))
        self.assertEqual(payload["platform"], "web")
        self.assertEqual(payload["app_version"], "1.0.2")
        self.assertEqual(payload["client_message"], "TypeError: x")
        self.assertEqual(payload["client_stack"], "at ChatPage.vue:42")
        self.assertEqual(payload["client_route"], "/chats/u9")
        self.assertEqual(payload["client_request_id"], "abc123")
        self.assertEqual(payload["user_agent"], "Mozilla/5.0")

    def test_exception_is_serialized_into_exc_field(self):
        """异常堆栈进 ``exc`` 字段,而不是拼进 message。"""
        from config.logging import JsonFormatter

        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord("chatapp.request", logging.ERROR, __file__, 1,
                                       "unhandled_exception", None, sys.exc_info())
        payload = json.loads(JsonFormatter().format(record))
        self.assertIn("ValueError", payload["exc"])
        self.assertEqual(payload["message"], "unhandled_exception")

    @override_settings(REQUEST_SLOW_MS=0)
    def test_request_log_carries_structured_fields(self):
        """访问日志带上 status/route/duration_ms,供 Loki 按字段检索。"""
        with self.assertLogs("chatapp.request", level="WARNING") as captured:
            self.client.get("/api/v1/health", HTTP_X_REQUEST_ID="rid-3")
        record = captured.records[0]
        self.assertEqual(record.status, 200)
        self.assertEqual(record.route, "api/v1/health")
        self.assertGreaterEqual(record.duration_ms, 0)


class CeleryQueueTests(SimpleTestCase):
    """队列分级与限速(削峰):紧急任务不能被通知洪水堵住。"""

    def test_routes_split_queues_by_urgency(self):
        """封禁/踢人走 critical,通知走 notify,资料同步走 bulk。"""
        routes = settings.CELERY_TASK_ROUTES
        self.assertEqual(routes["im.tasks.ban_notice"]["queue"], "critical")
        self.assertEqual(routes["im.tasks.send_match_notice"]["queue"], "notify")
        self.assertEqual(routes["im.tasks.sync_profile"]["queue"], "bulk")

    def test_notify_tasks_are_rate_limited(self):
        """notify 类任务带速率上限,critical 类不带。"""
        from im import tasks

        expected = f"{settings.IM_NOTICE_RATE_PER_SEC}/s"
        self.assertEqual(tasks.send_match_notice.rate_limit, expected)
        self.assertEqual(tasks.post_commented.rate_limit, expected)
        self.assertIsNone(tasks.ban_notice.rate_limit)

    def test_queue_depth_refresh_sets_gauges(self):
        """队列深度抓取:llen 的结果写进 celery_queue_depth。"""
        from unittest.mock import MagicMock

        fake = MagicMock()
        fake.llen.side_effect = lambda queue: {"notify": 7, "critical": 2}.get(queue, 0)
        with patch("redis.Redis.from_url", return_value=fake):
            metrics.refresh_queue_depths()
        self.assertEqual(
            metrics.REGISTRY.get_sample_value("celery_queue_depth", {"queue": "notify"}), 7)
        self.assertEqual(
            metrics.REGISTRY.get_sample_value("celery_queue_depth", {"queue": "critical"}), 2)


class RequestIdTests(APITestCase):
    """请求 ID:透传或生成,并回写响应头、写进错误体与日志。"""

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
    """请求 ID 跨进程传递:入队注入 header,worker 侧绑定与清理。"""

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


class ApiDocsCoverageTests(SimpleTestCase):
    """接口文档门禁:URLconf ↔ docs/api 信息行双向比对(漏写/残留即红)。"""

    def test_docs_cover_every_endpoint(self):
        from config.api_doc_coverage import endpoints_from_docs, endpoints_from_urlconf

        missing = sorted(endpoints_from_urlconf() - set(endpoints_from_docs()))
        self.assertEqual(
            missing, [],
            "以下接口未写文档,请补到 docs/api/ 对应分册:\n" +
            "\n".join(f"  {m} {p}" for m, p in missing))

    def test_docs_have_no_stale_endpoints(self):
        from config.api_doc_coverage import endpoints_from_docs, endpoints_from_urlconf

        real = endpoints_from_urlconf()
        stale = sorted(set(endpoints_from_docs()) - real)
        self.assertEqual(
            stale, [],
            "以下文档信息行在 URLconf 中已不存在,请删除或修正:\n" +
            "\n".join(f"  {m} {p}" for m, p in stale))


class OpenApiSchemaTests(SimpleTestCase):
    """OpenAPI 生成物门禁(D-5 第 1 步):schema 能生成,且与 URLconf 的操作集合一致。

    设计要点:
        本类只比「方法 + 路径」这一层,是生成管道的冒烟测试;字段级双向比对在
        ``config/test_schema_contract.py``(第 2 步)。这里刻意与
        ``ApiDocsCoverageTests`` 用同一份 ``endpoints_from_urlconf()``,保证
        「代码 / 人读文档 / 机器可读契约」三者不会各说各话。
    """

    schema: dict = {}

    @classmethod
    def setUpClass(cls):
        """生成一次 schema 供本类各用例复用(生成有固定开销,不重复跑)。"""
        super().setUpClass()
        from drf_spectacular.generators import SchemaGenerator

        cls.schema = SchemaGenerator().get_schema(request=None, public=True)

    def test_schema_is_openapi_3(self):
        self.assertTrue(self.schema["openapi"].startswith("3."))

    def test_schema_operations_match_urlconf(self):
        from config.api_doc_coverage import endpoints_from_urlconf

        operations = {
            (method.upper(), path)
            for path, item in self.schema["paths"].items()
            for method in item
            if method in ("get", "post", "patch", "put", "delete")
        }
        self.assertEqual(operations, endpoints_from_urlconf())

    def test_bearer_auth_scheme_is_registered(self):
        scheme = self.schema["components"]["securitySchemes"]["bearerAuth"]
        self.assertEqual(scheme["scheme"], "bearer")
        self.assertEqual(scheme["bearerFormat"], "JWT")


class CommentCoverageLogicTests(SimpleTestCase):
    """注释门禁检查模块自身的单元测试(用临时目录,不依赖真实代码)。"""

    def _write(self, tmp, body):
        """把源码写进临时目录的 demo.py,返回其路径。

        Args:
            tmp: 临时目录路径。
            body: 要写入的 Python 源码。

        Returns:
            写好的 demo.py 路径。
        """
        path = Path(tmp) / "demo.py"
        path.write_text(body, encoding="utf-8")
        return path

    def test_clean_file_passes(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\ndef foo() -> None:\n'
                                    '    """做一件事。"""\n')
            self.assertEqual(check_file(path), [])

    def test_missing_module_docstring_is_reported(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "x = 1\n")
            self.assertTrue(any("缺少模块 docstring" in p for p in check_file(path)))

    def test_missing_function_docstring_is_reported(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\ndef foo() -> None:\n    pass\n')
            self.assertTrue(any("foo 缺少 docstring" in p for p in check_file(path)))

    def test_missing_class_docstring_is_reported(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\nclass Foo:\n    pass\n')
            self.assertTrue(any("Foo 缺少 docstring" in p for p in check_file(path)))

    def test_test_functions_are_exempt(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\ndef test_foo():\n    pass\n')
            self.assertEqual(check_file(path), [])

    def test_lifecycle_hooks_are_exempt(self):
        """setUp 等框架钩子豁免(全项目 54 处,补 docstring 是噪音)。"""
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\nclass FooTests:\n'
                                    '    """演示测试类。"""\n\n'
                                    "    def setUp(self):\n        pass\n\n"
                                    "    def tearDown(self):\n        pass\n")
            self.assertEqual(check_file(path), [])

    def test_nested_functions_are_exempt(self):
        """函数体内的闭包与局部类豁免(测试里大量 3 行打桩属于此类)。"""
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\ndef outer():\n'
                                    '    """外层函数。"""\n\n'
                                    "    def fake_request():\n        pass\n\n"
                                    "    class FakeTask:\n        pass\n\n"
                                    "    return fake_request, FakeTask\n")
            self.assertEqual(check_file(path), [])

    def test_top_level_helper_still_requires_docstring(self):
        """豁免不能过宽:非 test_ 的顶层辅助函数仍必须有 docstring。"""
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\ndef _make_user():\n    pass\n')
            self.assertTrue(any("_make_user 缺少 docstring" in p for p in check_file(path)))

    def test_decoration_symbol_is_reported(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。⚠️"""\n')
            self.assertTrue(any("含装饰符号" in p for p in check_file(path)))

    def test_display_path_falls_back_outside_backend_root(self):
        """临时目录不在 chatapp/ 下,展示路径必须降级为文件名而不是抛 ValueError。"""
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "x = 1\n")
            self.assertTrue(all(p.startswith("demo.py:") for p in check_file(path)))

    def test_pitfalls_reference_is_not_a_tone_warning(self):
        """「踩坑记录:docs/pitfalls/...」是规范模板要求的写法,不能被口语词黑名单误报。"""
        from config.comment_coverage import find_tone_warnings

        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, '"""演示模块。\n\n关联文档:\n'
                             '    - 踩坑记录:docs/pitfalls/backend.md「管理命令」\n"""\n')
            self.assertEqual(find_tone_warnings(root=Path(tmp)), [])

    def test_casual_word_is_still_reported(self):
        """黑名单本身仍然生效(豁免只针对「踩坑」这个复合词)。"""
        from config.comment_coverage import find_tone_warnings

        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, '"""演示模块。这里有个坑,数据量小时够用。"""\n')
            self.assertTrue(find_tone_warnings(root=Path(tmp)))

    def test_meta_class_is_exempt(self):
        """Meta 是框架读取的声明式内部类,不强制 docstring。"""
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\nclass Foo:\n'
                                    '    """演示序列化器。"""\n\n'
                                    "    class Meta:\n"
                                    "        model = object\n")
            self.assertEqual(check_file(path), [])

    def test_public_function_with_params_needs_args_section(self):
        """公开函数带参数却没写 Args 小节时,结构提示必须点名。"""
        from config.comment_coverage import find_structure_warnings

        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, '"""演示模块。"""\n\n\ndef greet(name):\n'
                             '    """向某人问好。"""\n')
            warnings = find_structure_warnings(root=Path(tmp))
        self.assertTrue(any("greet" in w and "Args" in w for w in warnings))

    def test_function_with_args_section_passes_structure_check(self):
        """写了 Args 小节的公开函数不再出现在结构提示里。"""
        from config.comment_coverage import find_structure_warnings

        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, '"""演示模块。"""\n\n\ndef greet(name):\n'
                             '    """向某人问好。\n\n'
                             "    Args:\n"
                             "        name: 被问候者的名字。\n"
                             '    """\n')
            self.assertEqual(find_structure_warnings(root=Path(tmp)), [])

    def test_private_function_is_exempt_from_args_section(self):
        """私有函数允许只写首行,不要求 Args 小节。"""
        from config.comment_coverage import find_structure_warnings

        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, '"""演示模块。"""\n\n\ndef _greet(name):\n'
                             '    """向某人问好。"""\n')
            self.assertEqual(find_structure_warnings(root=Path(tmp)), [])

    def test_test_function_is_exempt_from_args_section(self):
        """test_* 用例豁免 Args 小节(用例名即文档)。"""
        from config.comment_coverage import find_structure_warnings

        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, '"""演示模块。"""\n\n\ndef test_greet(name):\n'
                             '    """验证问候语。"""\n')
            self.assertEqual(find_structure_warnings(root=Path(tmp)), [])

    def test_function_without_params_is_exempt_from_args_section(self):
        """没有参数的函数不需要 Args 小节。"""
        from config.comment_coverage import find_structure_warnings

        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, '"""演示模块。"""\n\n\ndef greet():\n'
                             '    """返回问候语。"""\n')
            self.assertEqual(find_structure_warnings(root=Path(tmp)), [])


class QueryParamTests(SimpleTestCase):
    """查询参数校验:非法整数 400,越界收敛,可选 id 非法返回 None。"""

    def setUp(self):
        """准备一个不经过 URL 路由的请求工厂。"""
        self.factory = RequestFactory()

    def _get(self, query):
        """构造带查询串的 GET 请求。

        Args:
            query: 查询参数字典。

        Returns:
            Django ``WSGIRequest``。
        """
        return self.factory.get("/x", query)

    def test_missing_or_empty_returns_default(self):
        """参数缺失或为空串时返回默认值。"""
        self.assertEqual(int_param(self._get({}), "limit", default=10), 10)
        self.assertEqual(int_param(self._get({"limit": ""}), "limit", default=10), 10)

    def test_non_integer_raises_validation_error(self):
        """非整数抛 DRF ValidationError(最终是 400,不是 500)。"""
        with self.assertRaises(ValidationError):
            int_param(self._get({"limit": "abc"}), "limit", default=10)

    def test_out_of_range_is_clamped(self):
        """越界值收敛到边界,不报错也不透传给切片。"""
        self.assertEqual(
            int_param(self._get({"limit": "-1"}), "limit", default=10, minimum=1, maximum=20), 1)
        self.assertEqual(
            int_param(self._get({"limit": "999"}), "limit", default=10, minimum=1, maximum=20), 20)

    def test_optional_id_rejects_invalid_values(self):
        """非法主键过滤参数返回 None,由调用方忽略该过滤。"""
        self.assertEqual(optional_id("12"), 12)
        self.assertIsNone(optional_id("abc"))
        self.assertIsNone(optional_id("-3"))
        self.assertIsNone(optional_id(""))


class RequestIdHeaderTests(APITestCase):
    """客户端传来的 X-Request-Id 必须清洗,防止日志注入(L2)。"""

    def test_unsafe_id_is_replaced(self):
        """含空格/标点的 ID 被替换成 32 位十六进制。"""
        resp = self.client.get("/api/v1/health", HTTP_X_REQUEST_ID="bad id!")
        self.assertEqual(len(resp["X-Request-Id"]), 32)

    def test_safe_id_passes_through(self):
        """合规的 ID 原样回显,便于前后端对账。"""
        resp = self.client.get("/api/v1/health", HTTP_X_REQUEST_ID="req-20261028-0001")
        self.assertEqual(resp["X-Request-Id"], "req-20261028-0001")


class ProxySettingsTests(SimpleTestCase):
    """DRF 只信任一层代理,否则伪造 XFF 可绕过 IP 限流(M1)。"""

    def test_num_proxies_is_configured(self):
        """``NUM_PROXIES`` 必须是正整数(默认 1)。"""
        self.assertEqual(settings.REST_FRAMEWORK["NUM_PROXIES"], 1)


class SecretKeyGuardTests(SimpleTestCase):
    """生产拒绝开发默认 ``SECRET_KEY``(H-2)。"""

    def test_rejects_default_key_in_production(self):
        """``DEBUG=0`` 且仍是默认密钥时必须拒绝启动。"""
        with self.assertRaises(ImproperlyConfigured):
            settings_module.assert_production_secret_key("dev-insecure-change-me", False)

    def test_allows_custom_key_in_production(self):
        """生产配了自定义密钥时正常通过。"""
        settings_module.assert_production_secret_key("a" * 50, False)

    def test_allows_default_key_in_debug(self):
        """本地 DEBUG 下仍允许默认密钥,方便起服务。"""
        settings_module.assert_production_secret_key("dev-insecure-change-me", True)


class ClientIpTests(SimpleTestCase):
    """客户端 IP 解析:只有可信代理转发的头才采信(M-3)。"""

    def _request(self, remote="127.0.0.1", **extra):
        """构造一个带指定 REMOTE_ADDR 的请求。

        Args:
            remote: 直连对端地址。
            **extra: 额外的 META 项(如 ``HTTP_X_REAL_IP``)。

        Returns:
            Django 请求对象。
        """
        request = RequestFactory().get("/", **extra)
        request.META["REMOTE_ADDR"] = remote
        return request

    def test_trusted_proxy_real_ip_is_used(self):
        """回环代理转发的 X-Real-IP 才是真实客户端。"""
        request = self._request(HTTP_X_REAL_IP="203.0.113.7")
        self.assertEqual(client_ip(request), "203.0.113.7")

    def test_forwarded_for_uses_last_hop(self):
        """没有 X-Real-IP 时取 XFF 最后一段(nginx 追加的那一段)。"""
        request = self._request(HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7")
        self.assertEqual(client_ip(request), "203.0.113.7")

    def test_untrusted_peer_ignores_headers(self):
        """直连(非可信代理)时伪造头无效,只认 REMOTE_ADDR。"""
        request = self._request(remote="198.51.100.9", HTTP_X_REAL_IP="203.0.113.7")
        self.assertEqual(client_ip(request), "198.51.100.9")

    def test_ipv4_mapped_loopback_is_trusted(self):
        """``::ffff:127.0.0.1`` 按 IPv4 处理,仍算可信代理。"""
        request = self._request(remote="::ffff:127.0.0.1", HTTP_X_REAL_IP="203.0.113.7")
        self.assertEqual(client_ip(request), "203.0.113.7")

    def test_missing_remote_addr_returns_empty(self):
        """拿不到对端地址时返回空串,不误信头。"""
        request = RequestFactory().get("/", HTTP_X_REAL_IP="203.0.113.7")
        request.META.pop("REMOTE_ADDR", None)
        self.assertEqual(client_ip(request), "")


class ImageGuardTests(SimpleTestCase):
    """图片校验:格式白名单、像素上限、EXIF 剥离与方向校正(M3/M4/L5)。"""

    def _encoded(self, fmt="PNG", size=(1, 1), exif=None):
        """生成一张测试图片的字节。

        Args:
            fmt: Pillow 格式名。
            size: 宽高。
            exif: 可选的 EXIF 对象。

        Returns:
            编码后的字节。
        """
        buffer = io.BytesIO()
        image = Image.new("RGB", size, "red")
        if exif is None:
            image.save(buffer, fmt)
        else:
            image.save(buffer, fmt, exif=exif)
        return buffer.getvalue()

    def test_rejects_format_outside_whitelist(self):
        """GIF 不在 jpg/png/webp 白名单内,直接拒绝。"""
        with self.assertRaises(images.UnsupportedImage):
            images.open_checked(self._encoded("GIF"))

    def test_rejects_non_image(self):
        """完全无法解码的字节按「请上传图片文件」处理。"""
        with self.assertRaises(images.ImageError):
            images.open_checked(b"not an image")

    def test_rejects_too_many_pixels(self):
        """像素总数超过上限时在解码前拒绝。"""
        with patch("config.images.MAX_IMAGE_PIXELS", 100):
            with self.assertRaises(images.ImageTooLarge):
                images.open_checked(self._encoded(size=(20, 20)))

    def test_normalize_strips_exif_and_fixes_orientation(self):
        """重编码后方向摆正,EXIF(含 GPS)不再存在。"""
        exif = Image.Exif()
        exif[0x0112] = 6            # Orientation = 顺时针 90°
        exif[0x010F] = "TestCamera"  # Make
        gps = exif.get_ifd(0x8825)
        gps[1] = "N"
        gps[2] = (31.0, 14.0, 0.0)
        raw = self._encoded("JPEG", size=(10, 20), exif=exif)

        normalized = images.normalize(images.open_checked(raw))
        self.assertEqual((normalized.width, normalized.height), (20, 10))

        reopened = Image.open(io.BytesIO(normalized.data))
        metadata = reopened.getexif()
        self.assertNotIn(0x010F, metadata)
        self.assertNotIn(0x8825, metadata)


class DependencyLockTests(SimpleTestCase):
    """L6 门禁:``requirements.lock`` 必须精确锁定并覆盖 ``requirements.txt`` 的直接依赖。"""

    @staticmethod
    def _parse(path: Path) -> dict[str, str]:
        """解析 requirements 文件为「规范化包名 → 原始行」。

        Args:
            path: requirements 文件路径。

        Returns:
            包名统一小写、下划线转连字符后的字典;注释与空行忽略。
        """
        entries = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0]
            entries[name.lower().replace("_", "-")] = line
        return entries

    def test_lock_covers_direct_requirements(self):
        """直接依赖漏进 lock 会让生产装错版本,必须红。"""
        base = Path(settings.BASE_DIR)
        direct = self._parse(base / "requirements.txt")
        lock = self._parse(base / "requirements.lock")
        self.assertEqual(sorted(set(direct) - set(lock)), [],
                         "requirements.lock 缺少直接依赖,请重新生成")

    def test_lock_is_exactly_pinned(self):
        """lock 里出现区间/通配符等于没锁,必须红。"""
        lock = self._parse(Path(settings.BASE_DIR) / "requirements.lock")
        unpinned = sorted(line for line in lock.values()
                          if not re.fullmatch(r"[A-Za-z0-9._-]+==[0-9][^\s]*", line))
        self.assertEqual(unpinned, [], "锁定文件存在非精确版本")


class CommentCoverageTests(SimpleTestCase):
    """注释规范门禁:模块头与函数/类 docstring 必须齐全(规则见 docs/standards/python.md)。"""

    def test_every_module_and_symbol_is_documented(self):
        """全量代码必须零缺口,否则列出所有待补位置。"""
        from config.comment_coverage import find_problems

        problems = find_problems()
        self.assertEqual(
            problems, [],
            "以下位置缺少注释或含装饰符号,请按 docs/standards/python.md 修正:\n" +
            "\n".join(f"  {p}" for p in problems))


class MetricsTests(APITestCase):
    """可观测性:路由模板打标签、``/metrics`` 访问控制、抓取自身不计数。"""

    def test_counter_uses_route_template(self):
        """真实路径里的 id 不能进标签,否则时间序列基数会爆炸。"""
        resp = self.client.get("/api/v1/users/123")
        value = metrics.REGISTRY.get_sample_value(
            "http_requests_total",
            {"method": "GET", "route": "api/v1/users/<int:user_id>",
             "status": str(resp.status_code)})
        self.assertIsNotNone(value)

    def test_raw_path_is_not_used_as_label(self):
        """同一请求不应产生 ``users/123`` 这样的标签。"""
        resp = self.client.get("/api/v1/users/123")
        self.assertIsNone(metrics.REGISTRY.get_sample_value(
            "http_requests_total",
            {"method": "GET", "route": "api/v1/users/123", "status": str(resp.status_code)}))

    def test_metrics_endpoint_skips_itself(self):
        """抓取请求不能污染延迟分布。"""
        self.assertEqual(self.client.get("/metrics").status_code, 200)
        self.assertIsNone(metrics.REGISTRY.get_sample_value(
            "http_requests_total",
            {"method": "GET", "route": "metrics", "status": "200"}))

    @override_settings(METRICS_TOKEN="s3cret")
    def test_token_required_when_configured(self):
        """配了令牌后,无令牌 403、带令牌 200。"""
        self.assertEqual(self.client.get("/metrics").status_code, 403)
        resp = self.client.get("/metrics", HTTP_X_METRICS_TOKEN="s3cret")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"http_requests_total", resp.content)

    @override_settings(METRICS_TOKEN="s3cret")
    def test_bearer_token_is_accepted(self):
        """Prometheus 的 authorization 头也要能用。"""
        resp = self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer s3cret")
        self.assertEqual(resp.status_code, 200)

    @override_settings(METRICS_TOKEN="")
    def test_loopback_allowed_without_token(self):
        """开发期本机直连可抓取。"""
        self.assertEqual(self.client.get("/metrics").status_code, 200)

    @override_settings(METRICS_TOKEN="")
    def test_non_loopback_is_hidden_without_token(self):
        """未配令牌时对非回环返回 404,不暴露端点存在。"""
        resp = self.client.get("/metrics", REMOTE_ADDR="203.0.113.9")
        self.assertEqual(resp.status_code, 404)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_metrics_is_exempt_from_https_redirect(self):
        """Prometheus 走 http 直连回环:不能被 301 到 https(否则抓取变成 TLS 握手)。"""
        self.assertEqual(self.client.get("/metrics").status_code, 200)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_business_paths_still_redirect_to_https(self):
        """豁免只针对 /metrics,业务接口仍强制 https。"""
        self.assertEqual(self.client.get("/api/v1/health").status_code, 301)


def metric_value(metric_name: str, **labels) -> float:
    """读一个指标的当前值(标签组合还没出现过时按 0 处理)。

    Args:
        metric_name: 指标名(如 ``logins_total``)。
        **labels: 标签组合。

    Returns:
        当前累计值;不存在时为 0.0(便于直接断言增量)。
    """
    value = metrics.REGISTRY.get_sample_value(metric_name, labels)
    return 0.0 if value is None else value


class BusinessMetricTests(APITestCase):
    """业务指标(E-4 ③):登录、滑卡、配对、IM 调用四类事件都要能被 Prometheus 读到。

    口径说明:这些是**进程内累计计数**,同一进程里测试之间会累加,所以全部断言「增量」
    (先读一次、动作后再读一次),不写死绝对值 —— 否则单独跑和全量跑会得到不同结果。
    """

    def setUp(self):
        """清缓存(验证码与限流计数都在 Redis 缓存里)。"""
        cache.clear()
        self.addCleanup(cache.clear)

    def _make_user(self, phone, gender="female"):
        """造一个资料完善、带已过审照片的用户。

        Args:
            phone: 手机号,同时用作昵称。
            gender: 性别。

        Returns:
            新建的用户实例。
        """
        from accounts.models import User
        from users.models import Photo, PhotoStatus, Profile, ProfileStatus

        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=phone, gender=gender, birthday="2000-01-01",
                               city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def test_login_success_and_rejection_are_counted(self):
        """登录成功记 ``success``,验证码错记 ``rejected``。"""
        from accounts import sms_codes

        before_ok = metric_value("logins_total", result="success")
        before_bad = metric_value("logins_total", result="rejected")

        sms_codes.store("13800138000", settings.SMS_DEV_CODE)
        ok = self.client.post("/api/v1/auth/sms/verify",
                              {"phone": "13800138000", "code": settings.SMS_DEV_CODE},
                              format="json")
        self.assertEqual(ok.status_code, 200)

        sms_codes.store("13900139000", settings.SMS_DEV_CODE)
        bad = self.client.post("/api/v1/auth/sms/verify",
                               {"phone": "13900139000", "code": "000000"}, format="json")
        self.assertGreaterEqual(bad.status_code, 400)

        self.assertEqual(1.0, metric_value("logins_total", result="success") - before_ok)
        self.assertEqual(1.0, metric_value("logins_total", result="rejected") - before_bad)

    def test_swipe_and_match_are_counted(self):
        """双方互喜:滑卡各记一次 ``like``,配对只涨 1。"""
        from rest_framework_simplejwt.tokens import RefreshToken

        me = self._make_user("13800138000", gender="male")
        target = self._make_user("13900139000")
        before_swipe = metric_value("swipes_total", action="like")
        before_match = metric_value("matches_total")

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(me).access_token}")
        self.client.post("/api/v1/discovery/swipe",
                         {"target_user_id": target.id, "action": "like"}, format="json")

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(target).access_token}")
        resp = self.client.post("/api/v1/discovery/swipe",
                                {"target_user_id": me.id, "action": "like"}, format="json")
        self.assertEqual({"matched": True, "shared_tags": []}, resp.json())

        self.assertEqual(2.0, metric_value("swipes_total", action="like") - before_swipe)
        self.assertEqual(1.0, metric_value("matches_total") - before_match)

    def test_im_call_success_and_failure_are_counted(self):
        """Django → imserver 的调用成与败各记一档,端点用内部 API 路径。"""
        from im import self_client

        path = "/internal/metrics-selftest"
        before_ok = metric_value("im_calls_total", endpoint=path, result="ok")
        before_err = metric_value("im_calls_total", endpoint=path, result="error")

        with patch.object(self_client.requests, "post") as post:
            post.return_value.raise_for_status.return_value = None
            self.assertTrue(self_client._post(path, {"uid": 1}))
        with patch.object(self_client.requests, "post", side_effect=OSError("boom")):
            self.assertFalse(self_client._post(path, {"uid": 1}))

        self.assertEqual(1.0, metric_value("im_calls_total", endpoint=path, result="ok")
                         - before_ok)
        self.assertEqual(1.0, metric_value("im_calls_total", endpoint=path, result="error")
                         - before_err)


class MetricsRenderTests(SimpleTestCase):
    """``/metrics`` 渲染:多进程合并开关与失败降级。

    背景:现网 gunicorn 是 ``-w 2``,计数器默认进程内 —— 不合并时每次抓取只反映一个 worker
    (实测 20 次请求后两个 worker 各记 10 / 12)。这里锁住「没有目录就走单进程」「合并出错要降级」。
    """

    def test_multiprocess_is_off_without_env(self):
        """没配 ``PROMETHEUS_MULTIPROC_DIR`` 时保持单进程语义(本地/测试/单 worker)。"""
        self.assertFalse(metrics.multiprocess_enabled())

    def test_render_falls_back_when_merge_fails(self):
        """多进程合并抛异常时必须降级成本进程视图,不能让抓取变 500。"""
        before = metric_value("cache_errors_total", name="metrics_multiprocess")
        with patch.object(metrics, "multiprocess_enabled", return_value=True), \
                patch.object(metrics.multiprocess, "MultiProcessCollector",
                             side_effect=OSError("mmap gone")):
            payload = metrics.render()
        self.assertIn(b"http_requests_total", payload)
        self.assertEqual(1.0, metric_value("cache_errors_total",
                                           name="metrics_multiprocess") - before)

    def test_render_exposes_business_counters(self):
        """业务指标必须出现在同一份 exposition 里(否则看板上永远是空的)。"""
        payload = metrics.render()
        for name in (b"logins_total", b"swipes_total", b"matches_total", b"im_calls_total"):
            self.assertIn(name, payload)


class _BoomView(APIView):
    """测试专用视图:抛出未预期异常,用于验证 500 也是 JSON 契约。"""

    permission_classes = [AllowAny]

    def get(self, request):
        """故意抛 ``RuntimeError``,模拟代码 bug 或 DB 故障。

        Args:
            request: 当前请求(未使用)。

        Raises:
            RuntimeError: 恒抛,供上层异常处理器转成 500。
        """
        raise RuntimeError("boom")


urlpatterns = [path("api/v1/_boom", _BoomView.as_view())]


@override_settings(ROOT_URLCONF="config.tests")
class UnhandledExceptionTests(APITestCase):
    """P2-4:未预期异常必须返回 ``{code,message,request_id}``,不能回 HTML 500。"""

    def test_unhandled_exception_returns_json_500(self):
        """DRF 视图里的 RuntimeError 被转成 500 JSON,且堆栈进日志。"""
        with self.assertLogs("chatapp.request", level="ERROR"):
            resp = self.client.get("/api/v1/_boom")
        self.assertEqual(resp.status_code, 500)
        body = resp.json()
        self.assertEqual(body["code"], 500)
        self.assertIn("message", body)
        self.assertIn("request_id", body)

    def test_handler500_returns_json_for_api_paths(self):
        """非 DRF 路径的兜底 handler 对 ``/api/`` 前缀返回 JSON。"""
        resp = server_error(RequestFactory().get("/api/v1/users/me"))
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(json.loads(resp.content)["code"], 500)

    def test_handler500_keeps_plain_text_outside_api(self):
        """非接口路径保持纯文本,避免把 HTML 页面也改成 JSON。"""
        resp = server_error(RequestFactory().get("/some-page/"))
        self.assertEqual(resp.status_code, 500)
        self.assertIn("text/plain", resp["Content-Type"])

class CursorCodecTests(SimpleTestCase):
    """游标编解码:往返一致、坏游标一律 400、offset 兼容口径。"""

    def test_roundtrip_keeps_microseconds_and_pk(self):
        """编码再解码回来,时间(含微秒)与主键都不许漂。"""
        value = datetime(2026, 11, 4, 3, 20, 11, 123456, tzinfo=timezone.utc)
        self.assertEqual(decode_cursor(encode_cursor(value, 42)), (value, 42))

    def test_cursor_is_url_safe(self):
        """游标里不能出现 ``+`` / ``/`` / ``=``(放进 query 会被改写)。"""
        cursor = encode_cursor(datetime(2026, 11, 4, tzinfo=timezone.utc), 987654321)
        self.assertRegex(cursor, r"^[A-Za-z0-9_-]+$")

    def test_garbage_cursor_is_400(self):
        """不是 base64 / 少了分隔符 / 主键不是数字,全部 400。"""
        for raw in ("not-a-cursor", "", "YWJjZGVm", encode_cursor(datetime(2026, 1, 1, tzinfo=timezone.utc), 1)[:-4] + "!!"):
            with self.assertRaises(ValidationError):
                decode_cursor(raw)

    def test_wants_legacy_offset(self):
        """带 offset 且不带 before 才是老客户端;两者都带时以 before 为准。"""
        self.assertTrue(wants_legacy_offset(RequestFactory().get("/x", {"offset": "0"})))
        self.assertFalse(wants_legacy_offset(RequestFactory().get("/x", {"before": "abc"})))
        self.assertFalse(wants_legacy_offset(
            RequestFactory().get("/x", {"offset": "20", "before": "abc"})))
        self.assertFalse(wants_legacy_offset(RequestFactory().get("/x")))

    def test_read_before_returns_none_without_param(self):
        """不带 before 表示第一页。"""
        self.assertIsNone(read_before(RequestFactory().get("/x")))
