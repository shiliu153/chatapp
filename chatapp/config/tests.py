"""config 项目的测试:错误信封、缓存、Celery 接线、请求 ID 与两套门禁。

覆盖场景:
    - 错误响应统一成 ``{code, message, request_id}`` 信封;
    - 缓存与 Celery broker 在测试期走独立 Redis DB(绝不写开发库);
    - 请求 ID 的生成、透传、写进错误体与日志,以及跨进程随消息 header 传递;
    - 接口文档门禁(``ApiDocsCoverageTests``)与注释规范门禁
      (``CommentCoverageTests``)及其检查模块自身的单元测试。
"""

import tempfile
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django_redis import get_redis_connection
from rest_framework.test import APITestCase

from config.celery import ping


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
