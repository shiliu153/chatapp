"""Alertmanager → 企业微信机器人中转。

为什么需要:Alertmanager 的 webhook 载荷是它自己的 JSON 结构,而企业微信机器人
只接受 ``{"msgtype":"text","text":{"content":"..."}}``;两边没有共同格式,又不值得
为此引入一个第三方服务,所以用 40 行标准库代码转换。

用法:由 ``deploy/observability/docker-compose.yml`` 以容器方式启动,
环境变量 ``WECOM_WEBHOOK`` 填机器人地址;未配置时只打日志(本地调试不报错)。
"""

import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEBHOOK = os.environ.get("WECOM_WEBHOOK", "")
PORT = int(os.environ.get("LISTEN_PORT", "9099"))

EMOJI = {"firing": "🔴", "resolved": "✅"}


def format_alert(payload: dict) -> str:
    """把 Alertmanager 载荷格式化成一段企业微信文本。

    Args:
        payload: Alertmanager webhook 的 JSON 体。

    Returns:
        多行文本;单条告警带 summary 与 description。
    """
    lines = []
    for alert in payload.get("alerts", []):
        status = alert.get("status", payload.get("status", "firing"))
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        name = labels.get("alertname", "unknown")
        lines.append(f"{EMOJI.get(status, '⚪')} [{status}] {name}")
        summary = annotations.get("summary")
        if summary:
            lines.append(summary)
        description = annotations.get("description")
        if description:
            lines.append(description)
        lines.append("")
    return "\n".join(lines).strip() or "Alertmanager 通知(空载荷)"


def send(text: str) -> None:
    """把文本发到企业微信机器人;未配置 webhook 时只打印。

    Args:
        text: 要发送的文本。
    """
    if not WEBHOOK:
        print("[alert_relay] WECOM_WEBHOOK 未配置,仅记录:\n" + text, flush=True)
        return
    body = json.dumps({"msgtype": "text", "text": {"content": text}}).encode()
    request = urllib.request.Request(
        WEBHOOK, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        response.read()


class Handler(BaseHTTPRequestHandler):
    """接收 Alertmanager 的 POST /alert。"""

    def do_POST(self):  # noqa: N802  (BaseHTTPRequestHandler 的命名约定)
        """读取 JSON、转发到企业微信,并回 200。

        无论转发是否成功都回 200:Alertmanager 收到非 2xx 会重试并放大告警噪音,
        失败原因已经打在日志里。
        """
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
            send(format_alert(payload))
        except Exception as error:  # noqa: BLE001  中转服务不能因为一条坏消息挂掉
            print(f"[alert_relay] 处理失败: {error}", file=sys.stderr, flush=True)
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        """把访问日志压到一行,避免容器日志被刷屏。

        Args:
            fmt: 日志格式串。
            *args: 格式参数。
        """
        print("[alert_relay] " + fmt % args, flush=True)


def main() -> None:
    """启动中转 HTTP 服务。"""
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[alert_relay] listening on 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
