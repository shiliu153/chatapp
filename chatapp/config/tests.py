"""config 项目的测试:错误信封、缓存、Celery 接线、请求 ID 与两套门禁。

覆盖场景:
    - 错误响应统一成 ``{code, message, request_id}`` 信封;
    - 缓存与 Celery broker 在测试期走独立 Redis DB(绝不写开发库);
    - 请求 ID 的生成、透传、写进错误体与日志,以及跨进程随消息 header 传递;
    - 接口文档门禁(``ApiDocsCoverageTests``)与注释规范门禁
      (``CommentCoverageTests``)及其检查模块自身的单元测试。
"""

import io
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django_redis import get_redis_connection
from PIL import Image
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from config import images
from config.celery import ping
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
