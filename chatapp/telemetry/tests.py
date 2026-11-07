"""客户端错误上报接口的测试。

覆盖六件事:
    1. 匿名也能上报(登录页白屏是最有价值的信号,那时还没有令牌);
    2. 合法上报写进 ``chatapp.client_error`` 日志,字段与 ``request_id`` 对得上;
    3. 非法字段回 400(说明客户端代码有 bug,值得在日志里看见);
    4. 超长堆栈被拒(匿名接口不能变成日志放大器);
    5. 同一 platform + message 在采样窗口内只落一条日志(指标照常每次累加);
    6. 采样用的 ``cache.add`` 抛异常时照常写日志(fail-open)。
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from config import metrics

URL = "/api/v1/client-errors"


class ClientErrorReportTests(TestCase):
    """``POST /api/v1/client-errors`` 的行为。"""

    def setUp(self):
        """准备匿名客户端,并清掉采样键(Redis 跨用例复用,不清会互相压日志)。"""
        self.client = APIClient()
        cache.clear()
        self.addCleanup(cache.clear)

    def test_anonymous_report_is_accepted_and_logged(self):
        """匿名上报返回 204,并写出带 platform/route 的 warning 日志。"""
        payload = {
            "platform": "web",
            "message": "TypeError: Cannot read properties of undefined",
            "stack": "at ChatPage.vue:42",
            "route": "/chats/u9",
            "app_version": "1.0.2",
            "request_id": "abc123",
        }
        with self.assertLogs("chatapp.client_error", level="WARNING") as logs:
            response = self.client.post(URL, payload, format="json")

        self.assertEqual(response.status_code, 204)
        record = logs.records[0]
        self.assertEqual(record.levelname, "WARNING")   # 本 logger 不参与告警,不写 error
        self.assertEqual(record.platform, "web")
        self.assertEqual(record.client_route, "/chats/u9")
        self.assertEqual(record.client_request_id, "abc123")
        self.assertIn("Cannot read properties", record.client_message)
        self.assertEqual(record.user_id, None)   # 匿名上报没有 user_id

    def test_minimal_payload_is_accepted(self):
        """只给 platform + message 也接受(其余字段有默认值)。"""
        with self.assertLogs("chatapp.client_error", level="WARNING"):
            response = self.client.post(URL, {"platform": "app", "message": "boom"},
                                        format="json")

        self.assertEqual(response.status_code, 204)

    def test_unknown_platform_is_rejected(self):
        """平台取值不在白名单 → 400(错误契约:code + message + request_id)。"""
        response = self.client.post(URL, {"platform": "smarttv", "message": "x"},
                                    format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 400)

    def test_oversize_stack_is_rejected(self):
        """超长堆栈被拒:匿名接口必须有长度上限。"""
        response = self.client.post(
            URL, {"platform": "web", "message": "x", "stack": "a" * 8001}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_authenticated_report_carries_user_id(self):
        """带令牌上报时日志里带上 user_id,便于按用户聚合。"""
        from django.contrib.auth import get_user_model
        from rest_framework_simplejwt.tokens import RefreshToken

        user = get_user_model().objects.create_user(phone="13600136000")
        token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        with self.assertLogs("chatapp.client_error", level="WARNING") as logs:
            response = self.client.post(
                URL, {"platform": "app", "message": "boom"}, format="json")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(logs.records[0].user_id, user.id)

    def test_metric_is_incremented(self):
        """Prometheus 计数器按端累加:Grafana 才能对「前端错误突增」告警。"""
        before = metrics.CLIENT_ERRORS.labels(platform="web")._value.get()
        with self.assertLogs("chatapp.client_error", level="WARNING"):
            self.client.post(URL, {"platform": "web", "message": "boom"}, format="json")

        after = metrics.CLIENT_ERRORS.labels(platform="web")._value.get()
        self.assertEqual(after, before + 1)

    def test_same_platform_and_message_is_logged_only_once_per_window(self):
        """同一 platform + message 在 60 秒采样窗口内只落一条日志。"""
        payload = {"platform": "web", "message": "render loop exploded"}

        with self.assertLogs("chatapp.client_error", level="WARNING") as logs:
            self.client.post(URL, payload, format="json")
            self.assertEqual(len(logs.records), 1)

            # 窗口内的第二、三次上报不该再写日志(assertNoLogs 会吞掉并校验)。
            with self.assertNoLogs("chatapp.client_error", level="WARNING"):
                self.client.post(URL, payload, format="json")
                self.client.post(URL, payload, format="json")

    def test_different_platform_or_message_is_logged_separately(self):
        """采样键是 platform + message:换端或换错误摘要都要各落一条。"""
        with self.assertLogs("chatapp.client_error", level="WARNING") as logs:
            self.client.post(URL, {"platform": "web", "message": "boom"}, format="json")
            self.client.post(URL, {"platform": "app", "message": "boom"}, format="json")
            self.client.post(URL, {"platform": "web", "message": "other"}, format="json")

        self.assertEqual([r.platform for r in logs.records], ["web", "app", "web"])

    def test_metric_still_counts_every_report_while_log_is_sampled(self):
        """采样只压缩日志:同一行错误连报 3 次,指标必须 +3。"""
        payload = {"platform": "web", "message": "sampled but counted"}
        before = metrics.CLIENT_ERRORS.labels(platform="web")._value.get()

        with self.assertLogs("chatapp.client_error", level="WARNING") as logs:
            for _ in range(3):
                self.client.post(URL, payload, format="json")

        after = metrics.CLIENT_ERRORS.labels(platform="web")._value.get()
        self.assertEqual(len(logs.records), 1)      # 日志被采样
        self.assertEqual(after, before + 3)         # 指标不被采样

    def test_cache_failure_still_logs(self):
        """``cache.add`` 抛异常时照常写日志(fail-open),接口仍是 204。"""
        with patch("telemetry.views.cache.add", side_effect=RuntimeError("redis down")):
            with self.assertLogs("chatapp.client_error", level="WARNING") as logs:
                response = self.client.post(
                    URL, {"platform": "web", "message": "redis is down"}, format="json")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].client_message, "redis is down")
