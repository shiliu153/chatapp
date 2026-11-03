"""客户端错误上报接口的测试。

覆盖四件事:
    1. 匿名也能上报(登录页白屏是最有价值的信号,那时还没有令牌);
    2. 合法上报写进 ``chatapp.client_error`` 日志,字段与 ``request_id`` 对得上;
    3. 非法字段回 400(说明客户端代码有 bug,值得在日志里看见);
    4. 超长堆栈被拒(匿名接口不能变成日志放大器)。
"""

from django.test import TestCase
from rest_framework.test import APIClient

from config import metrics

URL = "/api/v1/client-errors"


class ClientErrorReportTests(TestCase):
    """``POST /api/v1/client-errors`` 的行为。"""

    def setUp(self):
        """准备一个匿名客户端。"""
        self.client = APIClient()

    def test_anonymous_report_is_accepted_and_logged(self):
        """匿名上报返回 204,并写出带 platform/route 的 error 日志。"""
        payload = {
            "platform": "web",
            "message": "TypeError: Cannot read properties of undefined",
            "stack": "at ChatPage.vue:42",
            "route": "/chats/u9",
            "app_version": "1.0.2",
            "request_id": "abc123",
        }
        with self.assertLogs("chatapp.client_error", level="ERROR") as logs:
            response = self.client.post(URL, payload, format="json")

        self.assertEqual(response.status_code, 204)
        record = logs.records[0]
        self.assertEqual(record.platform, "web")
        self.assertEqual(record.client_route, "/chats/u9")
        self.assertEqual(record.client_request_id, "abc123")
        self.assertIn("Cannot read properties", record.client_message)
        self.assertEqual(record.user_id, None)   # 匿名上报没有 user_id

    def test_minimal_payload_is_accepted(self):
        """只给 platform + message 也接受(其余字段有默认值)。"""
        with self.assertLogs("chatapp.client_error", level="ERROR"):
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

        with self.assertLogs("chatapp.client_error", level="ERROR") as logs:
            response = self.client.post(
                URL, {"platform": "app", "message": "boom"}, format="json")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(logs.records[0].user_id, user.id)

    def test_metric_is_incremented(self):
        """Prometheus 计数器按端累加:Grafana 才能对「前端错误突增」告警。"""
        before = metrics.CLIENT_ERRORS.labels(platform="web")._value.get()
        with self.assertLogs("chatapp.client_error", level="ERROR"):
            self.client.post(URL, {"platform": "web", "message": "boom"}, format="json")

        after = metrics.CLIENT_ERRORS.labels(platform="web")._value.get()
        self.assertEqual(after, before + 1)
