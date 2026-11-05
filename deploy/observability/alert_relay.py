"""把 Alertmanager 的告警转成邮件,走「服务器日报」同一条发信链路(notify)。

背景:
    2026-11-03 上线的通道是「Alertmanager → 本脚本 → 企业微信群机器人」, 但机器人
    地址一直没配, 告警只落日志(等于没人看得到)。2026-11-05 用户决定**不再接群机器人**,
    改为复用每天 22:00 服务器日报那条邮件链路 —— ``/opt/notify/bin/notify send``
    (阿里云邮件推送, 同一份发信配额、去重状态与发送日志, 见 docs/ops/observability.md §4)。

设计要点:
    1. **只做翻译, 不做状态机**:分组 / 去重(4h 重复)/ 静默都归 Alertmanager,
       这里再自造一套去重只会两边打架;
    2. ``--dedup-key`` 取 ``groupKey + status``:同一组告警的 firing 只发一封、
       resolved 单独发一封;``--dedup-window`` 默认 60 分钟兜住「同组反复进出」,
       免得凌晨抖动刷出几十封邮件(notify 自己的配额是 5/分钟、50/天);
    3. **失败返回 500**, 让 Alertmanager 按它自己的指数退避重试, 这里不自建重试;
    4. 异常绝不逃出 ``do_POST``:一个格式化 bug 不能把整条告警通道打死。

运行形态(2026-11-05 起):不再是容器, 而是 systemd 服务 ``chatapp-alert-relay``
(``deploy/observability/alert-relay.service``)。因为发信要读 ``/opt/notify`` 与
``/etc/notify/env``、写 ``~/.local/state/notify``, 放在宿主机上比往容器里挂四处目录干净。

环境变量(全部可选):
    ALERT_RELAY_PORT      监听端口, 默认 9099(只监听 127.0.0.1)
    ALERT_NOTIFY_BIN      notify 入口, 默认 /opt/notify/bin/notify
    ALERT_NOTIFY_CONFIG   传给 notify 的 NOTIFY_CONFIG(告警用单独配置, 见
                          deploy/observability/notify-alerts.ini.tmpl)
    ALERT_DEDUP_WINDOW    notify 去重窗口(分钟), 默认 60
    ALERT_RELAY_DRY_RUN   置 1 时只打印不真发(本地调试用)

手工验证:
    python3 deploy/observability/alert_relay.py --print-payload sample.json
    python3 -m unittest discover -s deploy/observability -p 'test_*.py' -v
"""

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

logger = logging.getLogger("alert_relay")

DEFAULT_PORT = 9099
DEFAULT_NOTIFY_BIN = "/opt/notify/bin/notify"
DEFAULT_DEDUP_WINDOW_MIN = 60
NOTIFY_TIMEOUT_SECONDS = 30
MAX_BODY_BYTES = 256 * 1024


class AlertMessage(NamedTuple):
    """一封待发邮件的全部内容。

    Attributes:
        title: 邮件标题(不含 notify 自己的主题前缀与级别前缀)。
        body: 正文(纯文本;notify 会同时渲染一份 HTML)。
        level: notify 的级别, 取值 ``info`` / ``warn`` / ``error``。
        dedup_key: notify 的去重键;同键在去重窗口内只发一次。
    """

    title: str
    body: str
    level: str
    dedup_key: str


def _clip(text: str, limit: int = 500) -> str:
    """把过长的自由文本截断, 避免一封邮件被日志里的长堆栈撑爆。

    Args:
        text: 原始文本。
        limit: 保留的最大字符数。

    Returns:
        截断后的文本(超出时补省略号)。
    """
    text = (text or "").strip().replace("\r\n", "\n")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _alert_names(alerts: List[Dict[str, Any]]) -> List[str]:
    """取出本组告警涉及的 alertname 列表(去重且保持出现顺序)。

    Args:
        alerts: Alertmanager 载荷里的 ``alerts`` 数组。

    Returns:
        alertname 列表, 如 ``["ApiDown", "ApiHighErrorRate"]``;空时返回占位名。
    """
    names: List[str] = []
    for alert in alerts:
        name = (alert.get("labels") or {}).get("alertname") or "UnknownAlert"
        if name not in names:
            names.append(name)
    return names or ["UnknownAlert"]


def _worst_level(alerts: List[Dict[str, Any]]) -> str:
    """按 severity 取最严重的 notify 级别。

    Args:
        alerts: Alertmanager 载荷里的 ``alerts`` 数组。

    Returns:
        ``error``(有 critical)/ ``warn``(有 warning)/ ``info``(其余)。
    """
    severities = {(alert.get("labels") or {}).get("severity", "") for alert in alerts}
    if "critical" in severities:
        return "error"
    if "warning" in severities:
        return "warn"
    return "info"


def _format_one(index: int, alert: Dict[str, Any]) -> str:
    """把单条告警渲染成几行纯文本。

    Args:
        index: 序号(从 1 开始)。
        alert: 单条告警字典。

    Returns:
        多行文本块。
    """
    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}
    summary = _clip(annotations.get("summary") or "", 200)
    description = _clip(annotations.get("description") or "", 500)
    lines = ["{}. [{}] {}".format(
        index,
        alert.get("status", "unknown"),
        labels.get("alertname", "UnknownAlert"),
    )]
    if labels.get("severity"):
        lines.append("   级别: " + labels["severity"])
    if summary:
        lines.append("   摘要: " + summary)
    if description:
        lines.append("   详情: " + description)
    if alert.get("startsAt"):
        lines.append("   开始: " + alert["startsAt"])
    ends_at = alert.get("endsAt") or ""
    if ends_at and not ends_at.startswith("0001-"):
        lines.append("   结束: " + ends_at)
    # alertname / severity 已单独成行, 其余标签原样带上(job/instance/queue 等定位信息)。
    extra = {k: v for k, v in labels.items() if k not in ("alertname", "severity")}
    if extra:
        lines.append("   标签: " + ", ".join("{}={}".format(k, extra[k]) for k in sorted(extra)))
    return "\n".join(lines)


def build_message(payload: Dict[str, Any]) -> AlertMessage:
    """把 Alertmanager 的一次 webhook 载荷渲染成一封邮件。

    Args:
        payload: Alertmanager 的 JSON 体, 至少含 ``status`` 与 ``alerts``。

    Returns:
        待发邮件;``dedup_key`` 由 ``groupKey`` 与 ``status`` 派生, 同一组同一状态只发一次。

    Raises:
        ValueError: 载荷不是合法结构(缺 ``alerts`` 数组或为空)。
    """
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        raise ValueError("载荷里没有 alerts 数组")
    status = str(payload.get("status") or alerts[0].get("status") or "firing")
    firing = status == "firing"
    names = _alert_names(alerts)
    level = _worst_level(alerts) if firing else "info"

    common = payload.get("commonLabels") or {}
    if common:
        grouped = ", ".join("{}={}".format(k, common[k]) for k in sorted(common))
    else:
        grouped = "-"
    body = "{} {} 条告警\n分组: {}\n\n".format(
        "触发" if firing else "恢复", len(alerts), grouped)
    body += "\n\n".join(_format_one(i, alert) for i, alert in enumerate(alerts, start=1))
    if payload.get("externalURL"):
        body += "\n\nAlertmanager: " + str(payload["externalURL"])
    body += "\n\n—— 由 alert_relay 转发, 处置顺序见 docs/ops/runbook.md §3\n"

    group_key = str(payload.get("groupKey") or "")
    if not group_key:
        # 没有 groupKey(手工构造的测试载荷)时按告警名派生, 仍然是稳定的。
        group_key = "names:" + ",".join(sorted(names))
    digest = hashlib.sha1("{}|{}".format(group_key, status).encode("utf-8")).hexdigest()
    return AlertMessage(
        title="{} {}".format("[告警]" if firing else "[恢复]", " / ".join(names)),
        body=body,
        level=level,
        dedup_key="alertmanager:" + digest,
    )


def send_via_notify(message: AlertMessage, notify_bin: str = DEFAULT_NOTIFY_BIN,
                    notify_config: str = "",
                    dedup_window_minutes: int = DEFAULT_DEDUP_WINDOW_MIN,
                    dry_run: bool = False) -> Tuple[bool, str]:
    """调用 ``notify send`` 把邮件发出去。

    Args:
        message: 待发邮件。
        notify_bin: notify 入口路径(``/opt/notify/bin/notify``)。
        notify_config: 非空时作为 ``NOTIFY_CONFIG`` 传给 notify, 用单独的告警配置。
        dedup_window_minutes: notify 的去重窗口(分钟)。
        dry_run: True 时只渲染不发送(打印将发送的内容)。

    Returns:
        ``(是否成功, 说明文字)``;任何异常都收敛成 ``False``, 不向上抛。
    """
    if dry_run:
        logger.info("[dry-run] %s\n%s", message.title, message.body)
        return True, "dry-run"

    command = [
        notify_bin, "send",
        "--title", message.title,
        "--body-file", "-",
        "--level", message.level,
        "--dedup-key", message.dedup_key,
        "--dedup-window", str(dedup_window_minutes),
        "--json",
    ]
    env = dict(os.environ)
    if notify_config:
        env["NOTIFY_CONFIG"] = notify_config
    try:
        completed = subprocess.run(
            command,
            input=message.body,
            text=True,
            capture_output=True,
            timeout=NOTIFY_TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "调用 notify 失败: {}".format(exc)
    output = (completed.stdout or "").strip() or (completed.stderr or "").strip()
    if completed.returncode != 0:
        return False, "notify 退出码 {}: {}".format(completed.returncode, _clip(output, 400))
    return True, _clip(output, 400)


def handle_payload(payload: Dict[str, Any], notify_bin: str = DEFAULT_NOTIFY_BIN,
                   notify_config: str = "",
                   dedup_window_minutes: int = DEFAULT_DEDUP_WINDOW_MIN,
                   dry_run: bool = False) -> Tuple[int, str]:
    """处理一次 webhook 载荷, 返回 HTTP 状态码与说明。

    Args:
        payload: Alertmanager 的 JSON 体。
        notify_bin: notify 入口路径。
        notify_config: 传给 notify 的 ``NOTIFY_CONFIG``。
        dedup_window_minutes: notify 去重窗口(分钟)。
        dry_run: True 时只打印不发送。

    Returns:
        ``(状态码, 说明)``:成功 200, 载荷非法 400, 发信失败 500(让 Alertmanager 重试)。
    """
    try:
        message = build_message(payload)
    except (ValueError, TypeError, AttributeError) as exc:
        logger.warning("载荷无法解析: %s", exc)
        return 400, "bad payload: {}".format(exc)
    ok, detail = send_via_notify(message, notify_bin, notify_config,
                                 dedup_window_minutes, dry_run)
    if ok:
        logger.info("告警已处理: %s (%s)", message.title, detail)
        return 200, detail
    # 发信失败时保守返回 500:重复投递一封邮件, 也比丢一份告警好(Alertmanager 会退避重试)。
    logger.error("告警发送失败: %s (%s)", message.title, detail)
    return 500, detail


def make_handler(notify_bin: str, notify_config: str, dedup_window_minutes: int,
                 dry_run: bool):
    """构造绑定好配置的 ``BaseHTTPRequestHandler`` 子类(便于测试直接起服务)。

    Args:
        notify_bin: notify 入口路径。
        notify_config: 传给 notify 的 ``NOTIFY_CONFIG``。
        dedup_window_minutes: notify 去重窗口(分钟)。
        dry_run: True 时只打印不发送。

    Returns:
        可直接交给 ``ThreadingHTTPServer`` 的处理类。
    """

    class AlertRelayHandler(BaseHTTPRequestHandler):
        """接收 Alertmanager 的 ``POST /alert``, 转成邮件后回状态码。"""

        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802  (BaseHTTPRequestHandler 的命名约定)
            """读取 JSON 体并转发;任何异常都收敛成 500, 不让处理线程炸掉。"""
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_BODY_BYTES:
                    self._reply(400, "bad content-length")
                    return
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    self._reply(400, "payload must be an object")
                    return
                code, detail = handle_payload(payload, notify_bin, notify_config,
                                              dedup_window_minutes, dry_run)
                self._reply(code, detail)
            except Exception:  # noqa: BLE001  告警通道不能死于一条坏消息
                logger.exception("处理告警失败")
                self._reply(500, "internal error")

        def do_GET(self):  # noqa: N802  (BaseHTTPRequestHandler 的命名约定)
            """健康检查:``GET /healthz`` 恒回 200, 供人工确认 relay 还活着。"""
            self._reply(200, "ok")

        def _reply(self, code: int, text: str) -> None:
            """回写一个 UTF-8 纯文本响应。

            Args:
                code: HTTP 状态码。
                text: 响应体。
            """
            data = (text or "").encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            """把访问日志并入 logging(默认实现直接写 stderr, 与我们的格式不一致)。

            Args:
                fmt: 日志格式串。
                *args: 格式参数。
            """
            logger.debug("relay %s - %s", self.address_string(), fmt % args)

    return AlertRelayHandler


def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口:起 HTTP 服务,或把一份载荷离线渲染成邮件内容。

    Args:
        argv: 命令行参数, 默认取 ``sys.argv[1:]``。

    Returns:
        进程退出码(0 正常)。
    """
    parser = argparse.ArgumentParser(description="Alertmanager → notify 邮件中转")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("ALERT_RELAY_PORT")
                                    or os.environ.get("LISTEN_PORT") or DEFAULT_PORT))
    parser.add_argument("--notify-bin",
                        default=os.environ.get("ALERT_NOTIFY_BIN", DEFAULT_NOTIFY_BIN))
    parser.add_argument("--notify-config",
                        default=os.environ.get("ALERT_NOTIFY_CONFIG", ""))
    parser.add_argument("--dedup-window", type=int,
                        default=int(os.environ.get("ALERT_DEDUP_WINDOW")
                                    or DEFAULT_DEDUP_WINDOW_MIN))
    parser.add_argument("--dry-run", action="store_true",
                        default=os.environ.get("ALERT_RELAY_DRY_RUN") == "1")
    parser.add_argument("--print-payload", metavar="FILE",
                        help="只把该 JSON 载荷渲染成邮件内容打印出来, 不起服务")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    if args.print_payload:
        with open(args.print_payload, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        message = build_message(payload)
        print("标题: {}\n级别: {}\n去重键: {}\n".format(
            message.title, message.level, message.dedup_key))
        print(message.body)
        return 0

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(args.notify_bin, args.notify_config, args.dedup_window, args.dry_run),
    )
    logger.info("alert-relay 监听 127.0.0.1:%d, 发信走 %s%s", args.port, args.notify_bin,
                " (dry-run)" if args.dry_run else "")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中断, 退出")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
