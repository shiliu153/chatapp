"""``alert_relay`` 的单元测试:载荷渲染、去重键、HTTP 入口与失败收敛。

跑法(CI 的 contract.yml 会跑同一条命令):
    python -m unittest discover -s deploy/observability -p 'test_*.py' -v
"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import alert_relay


def sample_payload(status="firing", severity="critical"):
    """构造一份接近真实形状的 Alertmanager 载荷。

    Args:
        status: 组状态, ``firing`` 或 ``resolved``。
        severity: 告警的 severity 标签。

    Returns:
        可直接喂给 ``build_message`` 的字典。
    """
    return {
        "version": "4",
        "status": status,
        "groupKey": '{}:{{alertname="ApiDown"}}'.format("{}"),
        "externalURL": "http://127.0.0.1:9093",
        "commonLabels": {"alertname": "ApiDown", "severity": severity,
                         "instance": "127.0.0.1:8000"},
        "alerts": [{
            "status": status,
            "labels": {"alertname": "ApiDown", "severity": severity,
                       "job": "api", "instance": "127.0.0.1:8000"},
            "annotations": {"summary": "API 抓取失败",
                            "description": "gunicorn 进程或端口不可用"},
            "startsAt": "2026-11-05T10:00:00+08:00",
            "endsAt": "0001-01-01T00:00:00Z",
        }],
    }


class BuildMessageTests(unittest.TestCase):
    """载荷 → 邮件的渲染规则。"""

    def test_firing_critical_is_error_level(self):
        """critical 的 firing 告警应发成 error 级, 标题带 [告警]。"""
        message = alert_relay.build_message(sample_payload())
        self.assertEqual("error", message.level)
        self.assertTrue(message.title.startswith("[告警]"))
        self.assertIn("ApiDown", message.title)

    def test_warning_is_warn_level(self):
        """warning 级发成 warn, 不再升级成 error。"""
        message = alert_relay.build_message(sample_payload(severity="warning"))
        self.assertEqual("warn", message.level)

    def test_resolved_is_info_and_separate_dedup_key(self):
        """恢复通知是 info 级, 且去重键与 firing 不同(否则恢复会被去重吃掉)。"""
        firing = alert_relay.build_message(sample_payload())
        resolved = alert_relay.build_message(sample_payload(status="resolved"))
        self.assertEqual("info", resolved.level)
        self.assertTrue(resolved.title.startswith("[恢复]"))
        self.assertNotEqual(firing.dedup_key, resolved.dedup_key)

    def test_dedup_key_is_stable_for_same_group(self):
        """同一组同一状态的重复投递必须落在同一个去重键上。"""
        first = alert_relay.build_message(sample_payload())
        second = alert_relay.build_message(sample_payload())
        self.assertEqual(first.dedup_key, second.dedup_key)
        self.assertTrue(first.dedup_key.startswith("alertmanager:"))

    def test_body_carries_summary_description_and_labels(self):
        """正文要带上摘要、详情与定位用的标签。"""
        body = alert_relay.build_message(sample_payload()).body
        self.assertIn("API 抓取失败", body)
        self.assertIn("gunicorn 进程或端口不可用", body)
        self.assertIn("job=api", body)
        self.assertIn("127.0.0.1:8000", body)
        self.assertIn("触发 1 条告警", body)

    def test_body_omits_placeholder_ends_at(self):
        """``0001-01-01`` 是 Alertmanager 的「尚未结束」占位, 不该出现在正文里。"""
        self.assertNotIn("结束:", alert_relay.build_message(sample_payload()).body)

    def test_multiple_alerts_are_numbered(self):
        """同组多条告警按序编号, 标题列出全部名字。"""
        payload = sample_payload()
        second = json.loads(json.dumps(payload["alerts"][0]))
        second["labels"]["alertname"] = "ApiHighErrorRate"
        payload["alerts"].append(second)
        message = alert_relay.build_message(payload)
        self.assertIn("1. [firing] ApiDown", message.body)
        self.assertIn("2. [firing] ApiHighErrorRate", message.body)
        self.assertIn("ApiDown / ApiHighErrorRate", message.title)

    def test_empty_alerts_is_rejected(self):
        """没有 alerts 数组的载荷必须报错, 而不是发一封空邮件。"""
        with self.assertRaises(ValueError):
            alert_relay.build_message({"status": "firing", "alerts": []})


class SendTests(unittest.TestCase):
    """``send_via_notify`` 的失败收敛(不去真的发邮件)。"""

    def test_dry_run_does_not_shell_out(self):
        """dry-run 直接返回成功, 不依赖 notify 是否存在。"""
        message = alert_relay.build_message(sample_payload())
        ok, detail = alert_relay.send_via_notify(
            message, notify_bin="/nonexistent/notify", dry_run=True)
        self.assertTrue(ok)
        self.assertEqual("dry-run", detail)

    def test_missing_notify_binary_is_reported_not_raised(self):
        """notify 入口不存在时返回 (False, 说明), 绝不抛异常。"""
        message = alert_relay.build_message(sample_payload())
        ok, detail = alert_relay.send_via_notify(
            message, notify_bin="/nonexistent/notify", dry_run=False)
        self.assertFalse(ok)
        self.assertIn("notify", detail)


class HttpEntryTests(unittest.TestCase):
    """HTTP 入口:正常载荷 200、坏载荷 400、健康检查 200。"""

    @classmethod
    def setUpClass(cls):
        """在随机端口起一个 dry-run 的 relay。"""
        handler = alert_relay.make_handler("/nonexistent/notify", "", 60, True)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        """关掉服务并回收端口。"""
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def post(self, payload, path="/alert"):
        """向 relay 发一次 POST。

        Args:
            payload: 要发送的 Python 对象(会被 json 序列化)。
            path: 请求路径。

        Returns:
            状态码。
        """
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "http://127.0.0.1:{}{}".format(self.port, path), data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def test_valid_payload_returns_200(self):
        """正常载荷(dry-run)返回 200。"""
        self.assertEqual(200, self.post(sample_payload()))

    def test_bad_payload_returns_400(self):
        """结构不对的载荷返回 400, 而不是让 Alertmanager 一直重试。"""
        self.assertEqual(400, self.post({"status": "firing"}))

    def test_healthz_returns_200(self):
        """``GET /healthz`` 用来人工确认 relay 活着。"""
        with urllib.request.urlopen(
                "http://127.0.0.1:{}/healthz".format(self.port), timeout=10) as response:
            self.assertEqual(200, response.status)


if __name__ == "__main__":
    unittest.main()
