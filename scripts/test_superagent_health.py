"""``scripts/superagent-health/healthcheck.py`` 的离线自测。

巡检器坏掉的后果是**两种静默**:要么把「正常」报成异常(人被噪音训练成不看告警),
要么把「异常」报成正常(比没有巡检更糟 —— 会给主人一个虚假的安全感)。所以判定逻辑
全部用构造快照钉住,不联网、不碰真实 orchestrator 状态库。
"""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import superagent_health as healthcheck  # noqa: E402


@contextlib.contextmanager
def _local_server() -> Iterator[Tuple[str, int]]:
    """起一个只回 200 的本机 HTTP 服务,充当「一定能通」的靶子。

    参数说明:
        无。

    返回参数:
        上下文迭代出 ``(Host 头, 端口)``;退出时关服务、释放端口。

    使用示例:
        >>> with _local_server() as (host, port):
        ...     healthcheck.check_egress_direct(None, 3, f"http://127.0.0.1:{port}/")

    备注信息:
        出网那几项的判据里「通 / 不通」是全部信息量,用真实公网做断言会让自测在断网的 CI
        上飘;本机回环既快又稳定,而且能把 ``no_proxy`` / ``http_proxy`` 摆成任意组合来验
        「代理到底有没有被用上」。
    """
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield f"{host}:{port}", port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _QuietHandler(http.server.BaseHTTPRequestHandler):
    """回 200 且不打印访问日志的极简 handler。"""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的约定名
        """对任何 GET 都回 200 与一个空 JSON。"""
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """吞掉访问日志:自测输出里不需要它。"""


def make_db(tmp: str) -> sqlite3.Connection:
    """建一个只有巡检会用到的四张表的临时状态库。

    Args:
        tmp: 临时目录。

    Returns:
        可写的 sqlite 连接(路径可再以只读方式打开)。
    """
    path = os.path.join(tmp, "orchestrator.sqlite")
    conn = sqlite3.connect(path)
    conn.execute("create table kv (key text primary key, value text)")
    conn.execute("create table thread (key text primary key, value text)")
    conn.execute("create table trigger_thread (thread text, id text, at text, human int)")
    conn.execute("create table ticket (id text primary key, value text)")
    conn.commit()
    return conn


def ticket_row(number: int, assignments: list, title: str = "示例工单") -> str:
    """造一行 ticket JSON。

    Args:
        number: GitHub issue 编号。
        assignments: assignment 列表(每项至少含 id/state/createdAt)。
        title: 工单标题。

    Returns:
        JSON 字符串。
    """
    return json.dumps(
        {
            "id": "t-%s" % number,
            "title": title,
            "assignments": assignments,
            "mandate": {"basis": {"scope": {"number": number}}},
        }
    )


class EnqueueThreeTests(unittest.TestCase):
    """入队三连:三张表缺任何一张都必须报警。"""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.conn = make_db(self.tmp)

    def test_all_three_tables_present_is_ok(self) -> None:
        self.conn.execute("insert into thread values ('github:285','{}')")
        self.conn.execute("insert into trigger_thread values ('github:285','t1','2026-11-13',1)")
        self.conn.execute("insert into ticket values ('x', ?)", (ticket_row(285, []),))
        self.conn.commit()
        check = healthcheck.check_enqueue(self.conn, 285)
        self.assertEqual(check.state, healthcheck.OK, check.detail)

    def test_missing_ticket_rows_is_bad(self) -> None:
        check = healthcheck.check_enqueue(self.conn, 285)
        self.assertEqual(check.state, healthcheck.BAD)
        self.assertIn("ticket=0", check.detail)

    def test_ticket_but_no_trigger_is_bad(self) -> None:
        self.conn.execute("insert into thread values ('github:285','{}')")
        self.conn.execute("insert into ticket values ('x', ?)", (ticket_row(285, []),))
        self.conn.commit()
        check = healthcheck.check_enqueue(self.conn, 285)
        self.assertEqual(check.state, healthcheck.BAD)
        self.assertIn("trigger=0", check.detail)


class ZombieTests(unittest.TestCase):
    """卡住的 assignment:超过阈值才报,且 running / pending 都要管。"""

    NOW = datetime(2026, 11, 13, 8, 0, tzinfo=timezone.utc)

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.conn = make_db(self.tmp)

    def _insert(self, number: int, state: str, started: datetime, report: str = "") -> None:
        """插一行 ticket,只带一个 assignment。"""
        assignment = {
            "id": "a-%s-%s" % (number, state),
            "state": state,
            "createdAt": started.isoformat().replace("+00:00", "Z"),
            "startedAt": started.isoformat().replace("+00:00", "Z"),
            "report": {"summary": report} if report else {},
        }
        self.conn.execute(
            "insert into ticket values (?, ?)", ("t-%s" % number, ticket_row(number, [assignment]))
        )
        self.conn.commit()

    def test_long_running_assignment_is_zombie(self) -> None:
        self._insert(285, "running", self.NOW - timedelta(hours=6), "stream idle timeout")
        checks = healthcheck.zombie_assignments(self.conn, self.NOW, 45)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].state, healthcheck.BAD)
        self.assertIn("6.0h", checks[0].detail)

    def test_short_running_assignment_is_not_reported(self) -> None:
        self._insert(285, "running", self.NOW - timedelta(minutes=10))
        self.assertEqual(healthcheck.zombie_assignments(self.conn, self.NOW, 45), [])

    def test_pending_assignment_also_counts(self) -> None:
        self._insert(285, "pending", self.NOW - timedelta(hours=2))
        self.assertEqual(len(healthcheck.zombie_assignments(self.conn, self.NOW, 45)), 1)

    def test_ended_assignment_is_ignored(self) -> None:
        self._insert(285, "ended", self.NOW - timedelta(hours=9))
        self.assertEqual(healthcheck.zombie_assignments(self.conn, self.NOW, 45), [])


class ExitCodeAndRenderTests(unittest.TestCase):
    """退出码契约与摘要渲染:2 必须优先于 1(判不出来不能当成有异常)。"""

    def test_clean_report_is_zero(self) -> None:
        report = healthcheck.Report()
        report.add(healthcheck.Check("a", healthcheck.OK, "fine"))
        self.assertEqual(report.exit_code(), 0)

    def test_anomaly_is_one(self) -> None:
        report = healthcheck.Report()
        report.add(healthcheck.Check("a", healthcheck.BAD, "boom"))
        self.assertEqual(report.exit_code(), 1)
        self.assertEqual(report.anomalies, ["a"])

    def test_unknown_wins_over_anomaly(self) -> None:
        report = healthcheck.Report()
        report.add(healthcheck.Check("a", healthcheck.BAD, "boom"))
        report.unknown.append("库打不开")
        self.assertEqual(report.exit_code(), 2)

    def test_render_marks_and_conclusion(self) -> None:
        report = healthcheck.Report()
        report.add(healthcheck.Check("出网", healthcheck.BAD, "HTTP 000"))
        text = healthcheck.render_text(report)
        self.assertIn("❌", text)
        self.assertIn("结论:异常", text)

    def test_json_roundtrip(self) -> None:
        report = healthcheck.Report()
        report.add(healthcheck.Check("出网", healthcheck.OK, "HTTP 200"))
        payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual(payload["checks"][0]["name"], "出网")


class EgressTests(unittest.TestCase):
    """出网探测:代理连不上必须是 `bad`,不能抛异常(否则 timer 直接崩)。"""

    def test_dead_proxy_reports_bad_without_raising(self) -> None:
        check = healthcheck.check_egress("http://127.0.0.1:9", None, timeout=3)
        self.assertEqual(check.state, healthcheck.BAD)

    def test_reports_selector_when_config_missing(self) -> None:
        check = healthcheck.check_proxy_selector("/nonexistent/config.yaml")
        self.assertEqual(check.state, healthcheck.OK)

    def test_explicit_proxy_wins_over_no_proxy(self) -> None:
        """``no_proxy`` 含探针主机时,经代理那一支**仍必须真的走代理**。

        这是本文件最容易骗人的地方:worker 的 ``no_proxy`` 故意含 ``api.github.com``,
        而 urllib 的 ``ProxyHandler`` 会照着 ``no_proxy`` 把请求改成直连 —— 于是「经代理探」
        其实一直在探直连(对着死端口 9 也判绿)。这里用本机监听套接字当靶子、把
        ``no_proxy`` 设成它的主机,再让代理指向死端口:判 ``bad`` 才说明代理真的被用上了。
        """
        with _local_server() as (host_header, port):
            with unittest.mock.patch.dict(
                os.environ, {"no_proxy": "127.0.0.1", "NO_PROXY": "127.0.0.1"}
            ):
                check = healthcheck.check_egress(
                    "http://127.0.0.1:9", None, timeout=3, url=f"http://127.0.0.1:{port}/"
                )
        self.assertEqual(check.state, healthcheck.BAD)
        self.assertTrue(host_header)


class DirectEgressTests(unittest.TestCase):
    """直连那条腿的探针函数(2026-11-28 起只供人工排障,不进巡检报告)。

    备注信息:
        走 proxy 那一支靠 ``_proxy_bypass_disabled`` 保证量的是代理;这一支必须显式无视
        环境代理(``ProxyHandler({})``),否则「量的是什么」取决于调用方的环境变量 ——
        巡检最不能犯的错就是量错对象。
    """

    def test_direct_probe_ignores_env_proxy(self) -> None:
        """环境里 ``http_proxy`` 指向死端口时,直连那一支照旧成功。

        原巡检只有「经代理」一支,而它被 ``no_proxy`` 悄悄改成了直连;拆成两支之后,
        直连必须显式无视环境代理 —— 这是「不量错对象」的底线。
        """
        with _local_server() as (_host, port):
            with unittest.mock.patch.dict(
                os.environ, {"http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"}
            ):
                check = healthcheck.check_egress_direct(
                    None, timeout=3, url=f"http://127.0.0.1:{port}/"
                )
        self.assertEqual(check.state, healthcheck.OK)

    def test_direct_probe_reports_bad_on_dead_port(self) -> None:
        check = healthcheck.check_egress_direct(
            None, timeout=3, url="http://127.0.0.1:9/"
        )
        self.assertEqual(check.state, healthcheck.BAD)


class WorkerGhEnvTests(unittest.TestCase):
    """`gh` 调用的出口口径必须与 worker 一致,且不继承调用方的 `no_proxy`。"""

    def test_no_proxy_keeps_model_gateway_and_drops_github(self) -> None:
        """``no_proxy`` 里该有的有、该没的没(2026-11-28 口径:GitHub 也走 mihomo)。

        备注信息:
            两个方向都钉:``wb.shiliu153.me``(模型网关在国内,送进机场等于绕出国再绕回来)
            与回环地址必须在;那五个 GitHub 域**必须不在** —— 它们一旦被划成直连,worker 的
            轮询与 ``git`` 就会绕开代理去撞一条已不通的路(2026-11-28 实测直连 443 超时)。
        """
        hosts = healthcheck.WORKER_NO_PROXY.split(",")
        for host in ("wb.shiliu153.me", "127.0.0.1", "localhost"):
            self.assertIn(host, hosts)
        for host in ("api.github.com", "github.com", "codeload.github.com",
                     "raw.githubusercontent.com", "objects.githubusercontent.com"):
            self.assertNotIn(host, hosts)

    def test_env_overrides_inherited_no_proxy(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"no_proxy": "example.com", "NO_PROXY": "example.com"}):
            env = healthcheck.worker_gh_env("http://127.0.0.1:7890")
        self.assertEqual(env["no_proxy"], healthcheck.WORKER_NO_PROXY)
        self.assertEqual(env["NO_PROXY"], healthcheck.WORKER_NO_PROXY)
        self.assertEqual(env["https_proxy"], "http://127.0.0.1:7890")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:7890")


class ProxyInheritTests(unittest.TestCase):
    """第六项:WSL 继承到的 http(s)_proxy 指向死端口(2026-11-17 并入)。

    这一项最容易犯的两个错都要钉住:**漏报**(继承值指向死端口却判绿 —— 命令会静默挂住,
    谁也不知道为什么)与**误报**(worker 自己 export 的 7890 被当成继承值 —— 一切正常时天天
    报红,人会去关告警)。三种判定口径各一条用例,另外补「大写变量 / 畸形值 / 多变量混合」。

    探针只用本机监听套接字与死端口(127.0.0.1:1),**不联网**。
    """

    OWN = healthcheck.DEFAULT_PROXY

    def _listening_port(self) -> socket.socket:
        """建一个只在本机回环监听的空套接字,用它的端口冒充「活着的代理端口」。

        Returns:
            已 `listen()` 的套接字;调用方负责 `close()`。
        """
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        return server

    def test_empty_env_is_ok(self) -> None:
        check = healthcheck.check_proxy_inherit({}, self.OWN)
        self.assertEqual(check.state, healthcheck.OK)
        self.assertIn("未继承", check.detail)

    def test_own_export_is_not_inheritance(self) -> None:
        """worker 自 export 的那个值必须排除,否则正常状态下天天报红。"""
        env = {
            "https_proxy": self.OWN,
            "HTTPS_PROXY": self.OWN + "/",
            "http_proxy": self.OWN,
            "HTTP_PROXY": self.OWN,
        }
        check = healthcheck.check_proxy_inherit(env, self.OWN)
        self.assertEqual(check.state, healthcheck.OK)
        self.assertIn("自 export", check.detail)

    def test_dead_inherited_port_is_bad(self) -> None:
        """核心用例:继承值指向死端口 → 红,且文案指向 .wslconfig 的 autoProxy。"""
        check = healthcheck.check_proxy_inherit(
            {"https_proxy": "http://127.0.0.1:1"}, self.OWN, timeout=0.5
        )
        self.assertEqual(check.state, healthcheck.BAD)
        self.assertIn("autoProxy=false", check.detail)
        self.assertIn("静默挂住", check.detail)
        self.assertIn("127.0.0.1:1", check.detail)

    def test_alive_inherited_port_is_ok_but_flagged_latent(self) -> None:
        """活着判绿(此刻 Clash 开着),但必须写明「潜伏态」——沉默才是这单要修的毛病。"""
        server = self._listening_port()
        try:
            port = server.getsockname()[1]
            check = healthcheck.check_proxy_inherit(
                {"https_proxy": f"http://127.0.0.1:{port}"}, self.OWN
            )
        finally:
            server.close()
        self.assertEqual(check.state, healthcheck.OK)
        self.assertIn("潜伏态", check.detail)

    def test_uppercase_variable_is_checked_too(self) -> None:
        """Windows 侧导进来的可能是大写变量,只看小写就会漏。"""
        check = healthcheck.check_proxy_inherit(
            {"HTTPS_PROXY": "http://127.0.0.1:1"}, self.OWN, timeout=0.5
        )
        self.assertEqual(check.state, healthcheck.BAD)
        self.assertIn("HTTPS_PROXY", check.detail)

    def test_bare_host_port_form_is_parsed(self) -> None:
        """`127.0.0.1:7897` 这种没写 scheme 的写法 curl 认,探针也得认。"""
        self.assertEqual(healthcheck.parse_proxy_target("127.0.0.1:7897"), ("127.0.0.1", 7897))
        self.assertEqual(healthcheck.parse_proxy_target("http://127.0.0.1"), ("127.0.0.1", 80))

    def test_malformed_value_is_bad_not_silent(self) -> None:
        """畸形值对 curl/git 一样是错的,不能因为「解析不出来」就跳过。"""
        for value in ("http://127.0.0.1:db", "http://"):
            check = healthcheck.check_proxy_inherit({"https_proxy": value}, self.OWN)
            self.assertEqual(check.state, healthcheck.BAD, value)
            self.assertIn("不是可解析", check.detail)

    def test_timeout_from_probe_is_bad(self) -> None:
        """黑洞端口(连上但没人应答 / 被丢包)走的是「注入探针返回不通」这条路。"""
        calls = []

        def dead_probe(host: str, port: int, timeout: float):
            calls.append((host, port, timeout))
            return False, "TimeoutError"

        check = healthcheck.check_proxy_inherit(
            {"https_proxy": "http://10.255.255.1:7897"}, self.OWN, timeout=0.5, probe=dead_probe
        )
        self.assertEqual(check.state, healthcheck.BAD)
        self.assertIn("TimeoutError", check.detail)
        self.assertEqual(calls, [("10.255.255.1", 7897, 0.5)])

    def test_default_probe_timeout_is_three_seconds(self) -> None:
        """默认 3 秒是票据里写死的口径;开关默认关(这一项对 timer 是常开检查)。"""
        args = healthcheck.build_parser().parse_args([])
        self.assertEqual(args.proxy_inherit_timeout, 3.0)
        self.assertFalse(args.skip_proxy_inherit)

    def test_loopback_is_labelled_in_detail(self) -> None:
        """回环 / 非回环的标签只影响文案,但文案要能让人一眼看出「继承的是哪种地址」。"""
        check = healthcheck.check_proxy_inherit(
            {"http_proxy": "http://127.0.0.1:1"}, self.OWN, timeout=0.5
        )
        self.assertIn("回环地址", check.detail)
        self.assertEqual(healthcheck._is_loopback_host("127.0.0.1"), True)
        self.assertEqual(healthcheck._is_loopback_host("::1"), True)
        self.assertEqual(healthcheck._is_loopback_host("192.168.101.1"), False)


class ProxyInheritReportTests(unittest.TestCase):
    """第六项在整轮巡检里的接线:默认跑、两个开关都能单独关掉它。

    `check_egress` / `check_proxy_selector` 用 `patch.object` 顶掉 —— 本类只验接线,
    不验那两项自己的判据(它们有自己的用例,且一个会真的联网)。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        conn = make_db(self.tmp)
        conn.close()
        self.db = os.path.join(self.tmp, "orchestrator.sqlite")
        self.ok_egress = unittest.mock.patch.object(
            healthcheck, "check_egress", lambda *a, **k: healthcheck.Check("出网", healthcheck.OK, "假")
        )
        self.ok_selector = unittest.mock.patch.object(
            healthcheck,
            "check_proxy_selector",
            lambda *a, **k: healthcheck.Check("出口节点", healthcheck.OK, "假"),
        )
        self.ok_egress.start()
        self.ok_selector.start()
        env_patcher = unittest.mock.patch.dict(
            os.environ, {"https_proxy": "http://127.0.0.1:1"}, clear=True
        )
        env_patcher.start()
        self.addCleanup(self.ok_egress.stop)
        self.addCleanup(self.ok_selector.stop)
        self.addCleanup(env_patcher.stop)

    def _report(self, extra: list):
        """跑一轮(跳过状态库里那几项),返回检查名列表。

        Args:
            extra: 追加的命令行参数。

        Returns:
            `报告里每条检查的名字` 列表。
        """
        args = healthcheck.build_parser().parse_args(
            ["--db", self.db, "--skip-enqueue", "--skip-cursor"] + extra
        )
        return [check.name for check in healthcheck.build_report(args).checks]

    def test_runs_by_default(self) -> None:
        self.assertIn(healthcheck.PROXY_INHERIT_CHECK, self._report([]))

    def test_own_switch_skips_only_this_one(self) -> None:
        names = self._report(["--skip-proxy-inherit"])
        self.assertNotIn(healthcheck.PROXY_INHERIT_CHECK, names)
        self.assertIn("出网", names)

    def test_skip_egress_still_covers_it(self) -> None:
        """离线自测只写 `--skip-egress` 是既有约定,不能因此多跑一项本地探针。"""
        self.assertNotIn(healthcheck.PROXY_INHERIT_CHECK, self._report(["--skip-egress"]))


class AcknowledgeTests(unittest.TestCase):
    """人工确认作废的僵尸 assignment:降级成 ok,但信息保留。"""

    def test_ignored_zombie_becomes_ok(self) -> None:
        check = healthcheck.Check("僵尸 assignment ce1d46c9", healthcheck.BAD, "state=running 已 8.4h")
        acknowledged = healthcheck._acknowledge(check, ["ce1d46c9"])
        self.assertEqual(acknowledged.state, healthcheck.OK)
        self.assertIn("已人工确认作废", acknowledged.detail)
        self.assertIn("8.4h", acknowledged.detail)

    def test_unlisted_zombie_stays_bad(self) -> None:
        check = healthcheck.Check("僵尸 assignment ce1d46c9", healthcheck.BAD, "state=running")
        for ignore in ([], ["aaaaaaaa"], [""]):
            self.assertEqual(healthcheck._acknowledge(check, ignore).state, healthcheck.BAD)

    def test_report_with_ignore_is_green(self) -> None:
        tmp = tempfile.mkdtemp()
        conn = make_db(tmp)
        started = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)
        conn.execute(
            "insert into ticket values ('x', ?)",
            (
                ticket_row(
                    283,
                    [
                        {
                            "id": "ce1d46c9ffff",
                            "state": "running",
                            "createdAt": started.isoformat().replace("+00:00", "Z"),
                            "startedAt": started.isoformat().replace("+00:00", "Z"),
                        }
                    ],
                ),
            ),
        )
        conn.commit()
        conn.close()
        args = healthcheck.build_parser().parse_args(
            [
                "--db", os.path.join(tmp, "orchestrator.sqlite"),
                "--skip-egress", "--skip-enqueue",
                "--ignore", "ce1d46c9",
            ]
        )
        report = healthcheck.build_report(args)
        self.assertEqual(report.exit_code(), 0, report.anomalies)


class BuildReportTests(unittest.TestCase):
    """整体带参数跑一遍(跳过联网),确认 CLI 拼装出来的东西是自洽的。"""

    def test_skip_egress_still_checks_db(self) -> None:
        tmp = tempfile.mkdtemp()
        conn = make_db(tmp)
        conn.execute("insert into ticket values ('x', ?)", (ticket_row(285, []),))
        conn.commit()
        conn.close()
        args = healthcheck.build_parser().parse_args(
            ["--db", os.path.join(tmp, "orchestrator.sqlite"), "--skip-egress", "--issue", "285"]
        )
        report = healthcheck.build_report(args)
        self.assertIn("入队三连 #285", report.anomalies)
        self.assertEqual(report.exit_code(), 1)

    def test_missing_db_is_unknown_not_ok(self) -> None:
        args = healthcheck.build_parser().parse_args(
            ["--db", "/nonexistent/orchestrator.sqlite", "--skip-egress"]
        )
        report = healthcheck.build_report(args)
        self.assertTrue(report.unknown)
        self.assertEqual(report.exit_code(), 2)


class CursorStallTests(unittest.TestCase):
    """第四项:游标新鲜度。判错的两个方向都要钉住 —— 闲置不许报、真停摆必须报。

    2026-11-16 两次「面板全绿但派工评论没人读」的真事故,就是游标停在几小时前不动,
    而现有三项检查一条都抓不到。
    """

    NOW = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.conn = make_db(self.tmp)

    def _cursor(self, number: int, when: datetime) -> None:
        """写一条 `github-cursor:<number>`(与 orchestrator 同格式:JSON 字符串)。"""
        value = when.isoformat().replace("+00:00", "Z")
        self.conn.execute(
            "insert or replace into kv values (?, ?)",
            ("github-cursor:%s" % number, json.dumps(value)),
        )
        self.conn.commit()

    @staticmethod
    def _notifications(*items: dict):
        """造一个「取未读通知」的函数,并记下被调用的次数。"""
        calls = []

        def loader():
            calls.append(1)
            return list(items), None

        loader.calls = calls  # type: ignore[attr-defined]
        return loader

    def test_stale_cursor_with_newer_unread_is_bad(self) -> None:
        self._cursor(405, self.NOW - timedelta(minutes=52))
        unread = [
            {
                "number": "405",
                "title": "[工单] flow: 巡检加「轮询游标新鲜度」",
                "updated_at": (self.NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            }
        ]
        check, unknown = healthcheck.check_cursor(
            self.conn, self.NOW, 10, self._notifications(*unread)
        )
        self.assertEqual(check.state, healthcheck.BAD, check.detail)
        self.assertIsNone(unknown)
        self.assertIn("2026-11-16T13:08Z", check.detail)  # 游标时间
        self.assertIn("52 分钟", check.detail)  # 落后分钟数
        self.assertIn("1 条", check.detail)  # 未读条数
        self.assertIn("#405", check.detail)  # 前 3 条标题

    def test_stale_cursor_without_newer_unread_is_ok(self) -> None:
        """闲置时段:游标不动,但通知里没有比它更新的东西 —— 必须不报。"""
        self._cursor(405, self.NOW - timedelta(hours=3))
        old = [
            {
                "number": "288",
                "title": "老通知(游标之前就有的)",
                "updated_at": (self.NOW - timedelta(hours=5)).isoformat().replace("+00:00", "Z"),
            }
        ]
        check, unknown = healthcheck.check_cursor(
            self.conn, self.NOW, 10, self._notifications(*old)
        )
        self.assertEqual(check.state, healthcheck.OK, check.detail)
        self.assertIsNone(unknown)
        self.assertIn("闲置", check.detail)

    def test_fresh_cursor_is_ok_and_never_fetches(self) -> None:
        """正常路径完全离线:游标新鲜时连通知都不取(不花限流、不因网络抖动误判)。"""
        self._cursor(405, self.NOW - timedelta(minutes=2))
        loader = self._notifications()
        check, unknown = healthcheck.check_cursor(self.conn, self.NOW, 10, loader)
        self.assertEqual(check.state, healthcheck.OK, check.detail)
        self.assertIsNone(unknown)
        self.assertEqual(loader.calls, [], "游标新鲜时不该去取通知")
        self.assertIn("落后 2 分钟", check.detail)

    def test_missing_cursor_is_skipped(self) -> None:
        check, unknown = healthcheck.check_cursor(self.conn, self.NOW, 10, self._notifications())
        self.assertEqual(check.state, healthcheck.OK, check.detail)
        self.assertIsNone(unknown)
        self.assertIn("跳过", check.detail)

    def test_unread_without_timestamp_counts_as_pending(self) -> None:
        """时间解析不出来时按「有活」处理:宁可多报一次,也别把真停摆吞掉。"""
        self._cursor(405, self.NOW - timedelta(hours=1))
        check, _ = healthcheck.check_cursor(
            self.conn,
            self.NOW,
            10,
            self._notifications({"number": "399", "title": "无时间戳", "updated_at": ""}),
        )
        self.assertEqual(check.state, healthcheck.BAD, check.detail)

    def test_notifications_unavailable_is_unknown_not_ok(self) -> None:
        """游标落后且通知取不到 = 判不出来,绝不能当成正常。"""
        self._cursor(405, self.NOW - timedelta(hours=1))
        check, unknown = healthcheck.check_cursor(
            self.conn, self.NOW, 10, lambda: ([], "gh api notifications 退出码 1:EOF")
        )
        self.assertEqual(check.state, healthcheck.BAD, check.detail)
        self.assertIsNotNone(unknown)
        self.assertIn("取不到未读通知", check.detail)

    def test_heartbeat_is_reported_but_does_not_decide(self) -> None:
        """`github-since` 只是旁证:它新鲜也不会把「有未读」的停摆洗成正常。"""
        self._cursor(405, self.NOW - timedelta(hours=1))
        self.conn.execute(
            "insert or replace into kv values ('github-since', ?)",
            (json.dumps(self.NOW.isoformat().replace("+00:00", "Z")),),
        )
        self.conn.commit()
        unread = [
            {
                "number": "405",
                "title": "新评论",
                "updated_at": self.NOW.isoformat().replace("+00:00", "Z"),
            }
        ]
        check, _ = healthcheck.check_cursor(self.conn, self.NOW, 10, self._notifications(*unread))
        self.assertEqual(check.state, healthcheck.BAD, check.detail)
        self.assertIn("轮询心跳", check.detail)


class CiRedTests(unittest.TestCase):
    """第五项:默认分支的 CI 红轨(2026-11-16 从 main-health.yml 的 issue 并进来)。

    钉两件事:①判据与 `l4_intake.red_runs` 完全一致(不许各写一份);②**每条红轨一个
    检查名** —— 否则指纹(检查名+状态)会把「web 红了」与「imserver 红了」压成同一个,
    新红一条会被 6 小时去重吞掉。
    """

    @staticmethod
    def _run(name: str, conclusion, created: str = "2026-11-16T01:00:00Z", sha: str = "abcdef1234567"):
        """造一条 Actions run 记录(只保留判定用得到的字段)。"""
        return {
            "name": name,
            "conclusion": conclusion,
            "created_at": created,
            "head_sha": sha,
            "html_url": f"https://github.com/shiliu153/chatapp/actions/runs/{name}",
        }

    def _loader(self, payload):
        """把一份快照包成 loader(与 `--runs-file` 走同一个形状)。"""
        return lambda: (payload, None)

    def test_all_green_is_ok(self) -> None:
        payload = {"workflow_runs": [self._run("web", "success"), self._run("backend", "success")]}
        checks, unknown = healthcheck.ci_red_checks(self._loader(payload))
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].state, healthcheck.OK, checks[0].detail)
        self.assertIsNone(unknown)
        self.assertIn("2 条 workflow", checks[0].detail)

    def test_one_check_per_red_track(self) -> None:
        payload = {
            "workflow_runs": [
                self._run("web", "failure"),
                self._run("imserver", "timed_out"),
                self._run("backend", "success"),
            ]
        }
        checks, unknown = healthcheck.ci_red_checks(self._loader(payload))
        self.assertIsNone(unknown)
        self.assertEqual(len(checks), 2, "两条红轨必须给两个检查名")
        names = sorted(check.name for check in checks)
        self.assertEqual(names, ["CI 红轨 imserver", "CI 红轨 web"])
        for check in checks:
            self.assertEqual(check.state, healthcheck.BAD)
        detail = next(check.detail for check in checks if check.name.endswith("web"))
        self.assertIn("failure", detail)
        self.assertIn("abcdef1", detail)
        self.assertIn("actions/runs/web", detail)

    def test_not_run_green_conclusions_count_as_red(self) -> None:
        """cancelled / startup_failure 这些「没跑绿」都算红,只认 failure 会静默漏报。"""
        for conclusion in ("cancelled", "timed_out", "startup_failure", "action_required", "stale"):
            payload = {"workflow_runs": [self._run("web", conclusion)]}
            checks, _ = healthcheck.ci_red_checks(self._loader(payload))
            self.assertEqual(checks[0].state, healthcheck.BAD, f"{conclusion} 应当算红")

    def test_running_and_skipped_are_not_red(self) -> None:
        for conclusion in (None, "success", "skipped", "neutral"):
            payload = {"workflow_runs": [self._run("web", conclusion)]}
            checks, _ = healthcheck.ci_red_checks(self._loader(payload))
            self.assertEqual(checks[0].state, healthcheck.OK, f"{conclusion} 不该算红")

    def test_latest_run_per_workflow_wins(self) -> None:
        """老的一条红、新的一条绿 —— 看的是最新那次,不许把已经修好的轨继续报红。"""
        payload = {
            "workflow_runs": [
                self._run("web", "failure", created="2026-11-15T01:00:00Z"),
                self._run("web", "success", created="2026-11-16T01:00:00Z"),
            ]
        }
        checks, _ = healthcheck.ci_red_checks(self._loader(payload))
        self.assertEqual(checks[0].state, healthcheck.OK, checks[0].detail)

    def test_bad_shape_is_unknown_not_ok(self) -> None:
        checks, unknown = healthcheck.ci_red_checks(self._loader({"oops": 1}))
        self.assertEqual(checks[0].state, healthcheck.BAD)
        self.assertIsNotNone(unknown, "形状不对必须报「判不出来」,不能算正常")

    def test_fetch_failure_is_unknown_not_ok(self) -> None:
        checks, unknown = healthcheck.ci_red_checks(lambda: (None, "gh api actions/runs 退出码 1:EOF"))
        self.assertEqual(checks[0].state, healthcheck.BAD)
        self.assertIn("EOF", checks[0].detail)
        self.assertIsNotNone(unknown)

    def test_gate_off_by_default(self) -> None:
        """总闸默认关:不打开时巡检结果与加这一项之前完全一致(连联网都不联)。"""
        tmp = tempfile.mkdtemp()
        make_db(tmp).close()
        args = healthcheck.build_parser().parse_args(
            ["--db", os.path.join(tmp, "orchestrator.sqlite"), "--skip-egress", "--skip-cursor"]
        )
        report = healthcheck.build_report(args)
        self.assertEqual([check for check in report.checks if "CI 红轨" in check.name], [])

    def test_gate_on_with_runs_file(self) -> None:
        """打开总闸 + 本地快照:红轨进报告,退出码 1,且不影响「判不出来」的语义。"""
        tmp = tempfile.mkdtemp()
        make_db(tmp).close()
        runs_path = os.path.join(tmp, "runs.json")
        with open(runs_path, "w", encoding="utf-8") as handle:
            json.dump({"workflow_runs": [self._run("web", "failure")]}, handle)
        args = healthcheck.build_parser().parse_args(
            [
                "--db",
                os.path.join(tmp, "orchestrator.sqlite"),
                "--skip-egress",
                "--skip-cursor",
                "--ci-red",
                "1",
                "--runs-file",
                runs_path,
            ]
        )
        report = healthcheck.build_report(args)
        self.assertIn("CI 红轨 web", report.anomalies)
        self.assertEqual(report.exit_code(), 1)

    def test_skip_flag_wins_over_gate(self) -> None:
        tmp = tempfile.mkdtemp()
        make_db(tmp).close()
        args = healthcheck.build_parser().parse_args(
            [
                "--db",
                os.path.join(tmp, "orchestrator.sqlite"),
                "--skip-egress",
                "--skip-cursor",
                "--ci-red",
                "1",
                "--skip-ci-red",
            ]
        )
        report = healthcheck.build_report(args)
        self.assertEqual([check for check in report.checks if "CI 红轨" in check.name], [])


class NotificationParsingTests(unittest.TestCase):
    """通知响应的解析:只认未读,编号从 subject.url 尾巴取,坏数据不许抛。"""

    def test_filters_read_items_and_extracts_number(self) -> None:
        payload = [
            {
                "unread": True,
                "updated_at": "2026-11-16T14:03:52Z",
                "subject": {"title": "工单 A", "url": "https://api.github.com/repos/o/r/issues/405"},
                "repository": {"full_name": "o/r"},
            },
            {
                "unread": False,
                "updated_at": "2026-11-16T13:00:00Z",
                "subject": {"title": "已读的", "url": "https://api.github.com/repos/o/r/pulls/404"},
            },
            "垃圾行",
        ]
        items = healthcheck.parse_notifications(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["number"], "405")
        self.assertEqual(items[0]["repo"], "o/r")

    def test_non_list_payload_is_empty(self) -> None:
        for payload in ({"message": "Bad credentials"}, None, "x"):
            self.assertEqual(healthcheck.parse_notifications(payload), [])

    def test_notifications_file_is_offline_injection(self) -> None:
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "notifications.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                [
                    {
                        "unread": True,
                        "updated_at": "2026-11-16T14:03:52Z",
                        "subject": {"title": "注入的", "url": "https://api.github.com/repos/o/r/issues/399"},
                    }
                ],
                handle,
            )
        items, error = healthcheck.load_notifications_file(path)
        self.assertIsNone(error)
        self.assertEqual(items[0]["number"], "399")

    def test_missing_notifications_file_reports_error(self) -> None:
        items, error = healthcheck.load_notifications_file("/nonexistent/notifications.json")
        self.assertEqual(items, [])
        self.assertIsNotNone(error)


class CursorReportTests(unittest.TestCase):
    """整轮拼装:反证(陈旧游标 + 注入未读)必须让 CLI 退出码变成 1。"""

    NOW = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)

    def _setup(self, cursor_minutes_ago: int, unread_minutes_ago: Optional[int] = None):
        """造临时库 + 注入用的通知文件,返回 `(db 路径, 通知文件路径)`。"""
        tmp = tempfile.mkdtemp()
        conn = make_db(tmp)
        when = (self.NOW - timedelta(minutes=cursor_minutes_ago)).isoformat().replace("+00:00", "Z")
        conn.execute("insert into kv values ('github-cursor:405', ?)", (json.dumps(when),))
        conn.commit()
        conn.close()
        path = os.path.join(tmp, "notifications.json")
        items = []
        if unread_minutes_ago is not None:
            items.append(
                {
                    "unread": True,
                    "updated_at": (self.NOW - timedelta(minutes=unread_minutes_ago))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "subject": {"title": "派工评论", "url": "https://api.github.com/repos/o/r/issues/405"},
                }
            )
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(items, handle)
        return os.path.join(tmp, "orchestrator.sqlite"), path

    def _report(self, db: str, notes: str):
        """用注入文件跑一整轮(离线),返回报告。"""
        args = healthcheck.build_parser().parse_args(
            [
                "--db", db, "--skip-egress", "--skip-enqueue",
                "--notifications-file", notes, "--workdir", "/nonexistent",
            ]
        )
        return healthcheck.build_report(args, now=self.NOW)

    def test_stale_plus_unread_exits_one(self) -> None:
        report = self._report(*self._setup(cursor_minutes_ago=52, unread_minutes_ago=3))
        self.assertIn(healthcheck.CURSOR_CHECK, report.anomalies)
        self.assertEqual(report.exit_code(), 1)

    def test_stale_without_unread_stays_green(self) -> None:
        report = self._report(*self._setup(cursor_minutes_ago=52))
        self.assertEqual(report.exit_code(), 0, report.anomalies)

    def test_fresh_cursor_stays_green(self) -> None:
        report = self._report(*self._setup(cursor_minutes_ago=3, unread_minutes_ago=1))
        self.assertEqual(report.exit_code(), 0, report.anomalies)


class AutohealTests(unittest.TestCase):
    """安全自愈:四道闸全过才重启,任何一条不过都只告警。

    这是全脚本唯一会**动进程**的地方(重启会杀掉正在跑的会话),所以每条闸都单独钉一遍:
    判错的方向是「本该不重启却重启了」—— 那会把别人的活连同会话一起弄丢。
    自测**绝不**调真的 `start-superagent.sh`:重启回调是注入的假货,只记调用次数。
    """

    NOW = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.conn = make_db(self.tmp)
        self.db = os.path.join(self.tmp, "orchestrator.sqlite")
        self.state_dir = os.path.join(self.tmp, "health-state")
        self.workdir = os.path.join(self.tmp, "work")
        os.makedirs(self.workdir)
        self.notes = os.path.join(self.tmp, "notifications.json")
        with open(self.notes, "w", encoding="utf-8") as handle:
            json.dump(
                [
                    {
                        "unread": True,
                        "updated_at": (self.NOW - timedelta(minutes=2))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "subject": {"title": "派工评论", "url": "https://api.github.com/repos/o/r/issues/409"},
                    }
                ],
                handle,
            )

    def tearDown(self) -> None:
        self.conn.close()

    # ── 造场景 ────────────────────────────────────────────────────────────

    def _stall(self, cursor_minutes_ago: int = 52) -> None:
        """把游标写旧,模拟「有未读但游标不动」。"""
        when = (self.NOW - timedelta(minutes=cursor_minutes_ago)).isoformat().replace("+00:00", "Z")
        self.conn.execute("insert or replace into kv values ('github-cursor:409', ?)", (json.dumps(when),))
        self.conn.commit()

    def _running_assignment(self, state: str = "running") -> None:
        """塞一个还在跑的 assignment(重启会杀掉它)。"""
        assignment = {
            "id": "a-live-1",
            "state": state,
            "createdAt": self.NOW.isoformat().replace("+00:00", "Z"),
            "startedAt": self.NOW.isoformat().replace("+00:00", "Z"),
        }
        self.conn.execute(
            "insert or replace into ticket values ('t-1', ?)", (ticket_row(409, [assignment]),)
        )
        self.conn.commit()

    def _worktree(self, name: str = "wt-a", dirty: bool = False) -> str:
        """在 work/ 下建一个真的 git 仓库(worktree 的替身),可选留一个未提交文件。"""
        path = os.path.join(self.workdir, name)
        os.makedirs(path, exist_ok=True)
        subprocess.run(["git", "init", "-q", path], check=True, capture_output=True)
        if dirty:
            with open(os.path.join(path, "wip.txt"), "w", encoding="utf-8") as handle:
                handle.write("半截的活\n")
        return path

    def _report(self, *extra: str, autoreheal: str = "1", restart=None):
        """跑一整轮(离线),返回 `(报告, 假回调)`。"""
        args = healthcheck.build_parser().parse_args(
            [
                "--db", self.db, "--skip-egress", "--skip-enqueue",
                "--notifications-file", self.notes, "--workdir", self.workdir,
                "--autoreheal", autoreheal,
                "--autoreheal-state-dir", self.state_dir,
                *extra,
            ]
        )
        recorder = restart if restart is not None else _RestartRecorder()
        return healthcheck.build_report(args, now=self.NOW, restart=recorder), recorder

    @staticmethod
    def _autoreheal_check(report):
        """取报告里那条「安全自愈」检查(没有则返回 None)。"""
        for check in report.checks:
            if check.name == healthcheck.AUTOREHEAL_CHECK:
                return check
        return None

    # ── 四条闸 ───────────────────────────────────────────────────────────

    def test_stall_with_nothing_running_restarts_once(self) -> None:
        """停摆 + 无 running assignment + worktree 干净 → 调一次重启,告警写明已自动重启。"""
        self._stall()
        self._worktree("wt-clean")
        report, recorder = self._report()

        self.assertEqual(len(recorder.calls), 1, "该重启却没重启(或重启了多次)")
        check = self._autoreheal_check(report)
        self.assertIsNotNone(check)
        self.assertEqual(check.state, healthcheck.OK, check.detail)
        self.assertIn("已自动重启", check.detail)
        text = healthcheck.render_text(report)
        self.assertIn("已自动重启", text)
        # 停摆本身仍是异常:自愈成功不等于这一轮没有异常。
        self.assertEqual(report.exit_code(), 1)
        # 审计痕迹必须落盘:时间 / 原因 / 前后游标 / 退出码。
        with open(os.path.join(self.state_dir, "autoreheal.log"), encoding="utf-8") as handle:
            line = handle.read().strip()
        self.assertIn("result=ok", line)
        self.assertIn("rc=0", line)
        self.assertIn("cursor_before=", line)
        self.assertIn("cursor_after=", line)
        self.assertIn("trigger=游标新鲜度", line)
        self.assertTrue(os.path.exists(os.path.join(self.state_dir, "last-autoreheal")))

    def test_stall_with_running_assignment_never_restarts(self) -> None:
        """有 running 的会话 → 重启会杀活,一律不重启。"""
        self._stall()
        self._running_assignment("running")
        self._worktree("wt-clean")
        report, recorder = self._report()

        self.assertEqual(recorder.calls, [], "有 running assignment 时不许重启")
        check = self._autoreheal_check(report)
        self.assertIsNotNone(check)
        self.assertIn("不重启", check.detail)
        self.assertIn("running", check.detail)
        self.assertEqual(report.exit_code(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "autoreheal.log")))

    def test_pending_assignment_also_blocks(self) -> None:
        """`pending` 同样是活(已派未跑),一样不许重启。"""
        self._stall()
        self._running_assignment("pending")
        self._worktree("wt-clean")
        _, recorder = self._report()
        self.assertEqual(recorder.calls, [])

    def test_dirty_worktree_blocks(self) -> None:
        """worktree 有未提交改动 → 那是还没落地的活,不许重启。"""
        self._stall()
        self._worktree("wt-dirty", dirty=True)
        report, recorder = self._report()

        self.assertEqual(recorder.calls, [], "worktree 脏时不许重启")
        check = self._autoreheal_check(report)
        self.assertIn("未提交改动", check.detail)
        self.assertIn("wt-dirty", check.detail)

    def test_worktree_git_failure_blocks(self) -> None:
        """确认不了干净(work/ 下不是 git 目录)= 按脏处理,fail-closed。"""
        self._stall()
        os.makedirs(os.path.join(self.workdir, "not-a-repo"))
        _, recorder = self._report()
        self.assertEqual(recorder.calls, [], "确认不了 worktree 干净就不许重启")

    def test_missing_workdir_counts_as_clean(self) -> None:
        """work/ 不存在 = 没有 worktree = 没有活,可以自愈。"""
        self._stall()
        self.workdir = os.path.join(self.tmp, "no-such-work")
        _, recorder = self._report()
        self.assertEqual(len(recorder.calls), 1)

    # ── 总闸 / 判据边界 ──────────────────────────────────────────────────

    def test_fresh_cursor_never_restarts(self) -> None:
        """一切正常 → 重启回调一次都不调。"""
        self._stall(cursor_minutes_ago=2)
        self._worktree("wt-clean")
        report, recorder = self._report()
        self.assertEqual(recorder.calls, [])
        self.assertIsNone(self._autoreheal_check(report), "正常时不该多出一条自愈检查")
        self.assertEqual(report.exit_code(), 0)

    def test_switch_off_never_restarts(self) -> None:
        """`SUPERAGENT_AUTOREHEAL=0`(默认)→ 一律不重启,行为与加自愈之前完全一致。"""
        self._stall()
        self._worktree("wt-clean")
        report, recorder = self._report(autoreheal="0")
        self.assertEqual(recorder.calls, [])
        self.assertIsNone(self._autoreheal_check(report))
        self.assertEqual(report.anomalies, [healthcheck.CURSOR_CHECK])
        self.assertEqual(report.exit_code(), 1)

    def test_switch_defaults_to_off(self) -> None:
        """一个字都没配(env 也没有)时,总闸默认是关。"""
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SUPERAGENT_AUTOREHEAL", None)
            args = healthcheck.build_parser().parse_args([])
            self.assertFalse(healthcheck._autoreheal_enabled(args))
        for value, expected in (
            ("1", True), ("on", True), ("true", True), ("YES", True),
            ("0", False), ("off", False), ("false", False), ("", False), (None, False),
        ):
            self.assertIs(healthcheck._truthy(value), expected, value)

    def test_debounce_blocks_second_restart(self) -> None:
        """距上次自愈不足 20 分钟 → 不重复重启。"""
        self._stall()
        self._worktree("wt-clean")
        first, recorder = self._report()
        self.assertEqual(len(recorder.calls), 1)
        second, recorder2 = self._report()
        self.assertEqual(recorder2.calls, [], "20 分钟内不许重启第二次")
        check = self._autoreheal_check(second)
        self.assertIn("距上次自愈", check.detail)
        self.assertIn("20 分钟", check.detail)
        self.assertEqual(self._autoreheal_check(first).state, healthcheck.OK)

    def test_debounce_expires_after_threshold(self) -> None:
        """过了 20 分钟以上,可以再自愈一次。"""
        self._stall()
        self._worktree("wt-clean")
        self._report()
        later = self.NOW + timedelta(minutes=21)
        args = healthcheck.build_parser().parse_args(
            [
                "--db", self.db, "--skip-egress", "--skip-enqueue",
                "--notifications-file", self.notes, "--workdir", self.workdir,
                "--autoreheal", "1", "--autoreheal-state-dir", self.state_dir,
            ]
        )
        recorder = _RestartRecorder()
        healthcheck.build_report(args, now=later, restart=recorder)
        self.assertEqual(len(recorder.calls), 1)

    def test_restart_failure_is_reported_and_still_exits_one(self) -> None:
        """重启命令非零退出 → 告警里带失败原因,按「未自愈」处理(退出码仍是 1)。"""
        self._stall()
        self._worktree("wt-clean")
        report, _ = self._report(restart=_RestartRecorder(rc=3, output="端口被占"))
        check = self._autoreheal_check(report)
        self.assertEqual(check.state, healthcheck.BAD, check.detail)
        self.assertIn("失败", check.detail)
        self.assertIn("端口被占", check.detail)
        self.assertEqual(report.exit_code(), 1)
        with open(os.path.join(self.state_dir, "autoreheal.log"), encoding="utf-8") as handle:
            self.assertIn("result=failed", handle.read())

    def test_unknown_notifications_never_restart(self) -> None:
        """游标落后但取不到未读通知 = 判不出来,连「是不是真停摆」都不知道 ⇒ 不许重启。"""
        self._stall()
        self._worktree("wt-clean")
        os.remove(self.notes)
        report, recorder = self._report()
        self.assertEqual(recorder.calls, [])
        self.assertTrue(report.unknown)
        self.assertEqual(report.exit_code(), 2)


RUN_SH = Path(__file__).resolve().parent / "superagent-health" / "run.sh"


class RunFingerprintTests(unittest.TestCase):
    """`run.sh` 的告警指纹口径:同一故障多轮数字在变 ⇒ 指纹不变;不同检查名 ⇒ 指纹不同。

    为什么单独测这一层:判定逻辑再对,指纹里只要混进一个动态数字,`6 小时去重`就静默失效 ——
    故障持续期间每 15 分钟一封(2026-11-16 实测),既吵,又会把真正的告警挤出邮件日额度
    (阿里云推送有 `per_day` 上限)。反过来,指纹口径**收得太狠**(只留「有异常」)会把两类
    故障合成一条,真告警被去重吞掉。所以这里钉两个方向,都跑真的 `run.sh`,只把巡检器
    (`SUPERAGENT_HEALTH_CHECKER`)和告警通道(`SUPERAGENT_NOTIFY_CMD`)换成假的。
    """

    #: 告警主题的前缀(2026-11-16 起的规范:类别 / 对象 / 结论三段,见 docs/ops/mail.md)。
    SUBJECT_PREFIX = "[chatapp·巡检] worker — "

    def setUp(self) -> None:
        """建临时状态目录,并写一个「输出由用例给定」的假巡检器(不联网、不碰真库)。"""
        self.tmp = tempfile.mkdtemp()
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.state)
        self.notify_log = os.path.join(self.tmp, "notify.log")
        self.text_path = os.path.join(self.tmp, "checker-out.txt")
        self.checker = os.path.join(self.tmp, "fake_checker.py")
        with open(self.checker, "w", encoding="utf-8") as handle:
            handle.write(
                "import os, sys\n"
                "with open(os.environ['FAKE_OUT'], encoding='utf-8') as handle:\n"
                "    sys.stdout.write(handle.read())\n"
                "sys.exit(int(os.environ['FAKE_RC']))\n"
            )

    def _round(self, text: str, rc: int = 1) -> str:
        """跑一轮真的 `run.sh`,巡检输出用 `text` 顶替。

        Args:
            text: 假巡检器打印的整份输出(必须和 `superagent_health.py` 的渲染格式一致)。
            rc: 假巡检器的退出码(1 = 有异常,2 = 判不出来)。

        Returns:
            `run.sh` 的 stdout + stderr。

        env 是**从零搭的**:真环境里的 `SUPERAGENT_HEALTH_*` 会把用例带偏;
        `SUPERAGENT_HEALTH_ENV` 指到不存在的文件,免得 source 到本机真实告警配置。
        """
        with open(self.text_path, "w", encoding="utf-8") as handle:
            handle.write(text)
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": self.tmp,
            "SUPERAGENT_HEALTH_ENV": os.path.join(self.tmp, "absent.env"),
            "SUPERAGENT_HEALTH_STATE": self.state,
            "SUPERAGENT_HEALTH_CHECKER": self.checker,
            "SUPERAGENT_NOTIFY_CMD": "cat >> " + self.notify_log,
            "FAKE_OUT": self.text_path,
            "FAKE_RC": str(rc),
        }
        done = subprocess.run(
            ["bash", str(RUN_SH)], capture_output=True, text=True, env=env, timeout=120
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done.stdout + done.stderr

    def _sent(self) -> int:
        """返回真正发出去的告警条数(假通道每被调用一次就追加一段)。"""
        try:
            with open(self.notify_log, encoding="utf-8") as handle:
                return sum(1 for line in handle if line.startswith(self.SUBJECT_PREFIX))
        except FileNotFoundError:
            return 0

    def _fingerprint(self) -> str:
        """返回 `run.sh` 记下的最近一次指纹。"""
        with open(os.path.join(self.state, "last-fingerprint"), encoding="utf-8") as handle:
            return handle.read().strip()

    def _last_alert(self) -> str:
        """返回 `last-alert.md` 原文(通道落盘的那一份)。"""
        with open(os.path.join(self.state, "last-alert.md"), encoding="utf-8") as handle:
            return handle.read()

    def test_same_fault_with_new_numbers_reuses_fingerprint(self) -> None:
        """同一处停摆,落后 12 分钟 vs 18 分钟、未读 3 条 vs 7 条、耗时 0.9s vs 2.7s ⇒ 只发一封。"""
        self._round(
            "✅ 出网(api.github.com): HTTP 200 · 0.9s\n"
            "✅ worktrees: 2 个目录: a, b\n"
            "❌ 游标新鲜度: 游标停在 2026-11-16T22:20Z(落后 12 分钟,阈值 1;最新一条是 "
            "github-cursor:412) · 有未读且比游标新 3 条: #412 工单 等 3 条\n"
            "结论:异常 1 项 → 游标新鲜度\n"
        )
        first = self._fingerprint()
        self.assertEqual(self._sent(), 1)
        self.assertIn("落后 12 分钟", self._last_alert())

        out = self._round(
            "✅ 出网(api.github.com): HTTP 200 · 2.7s\n"
            "✅ worktrees: 9 个目录: a, b, c, d, e, f, g, h, i\n"
            "❌ 游标新鲜度: 游标停在 2026-11-16T22:20Z(落后 18 分钟,阈值 1;最新一条是 "
            "github-cursor:412) · 有未读且比游标新 7 条: #412 工单 等 7 条\n"
            "结论:异常 1 项 → 游标新鲜度\n"
        )
        self.assertEqual(self._fingerprint(), first)
        self.assertIn("不重复发", out)
        self.assertEqual(self._sent(), 1, "第二轮被去重时不该再发一封")
        self.assertIn("落后 12 分钟", self._last_alert(), "去重的那轮不该覆盖 last-alert")
        self.assertNotIn("落后 18 分钟", self._last_alert())

    def test_different_check_names_get_different_fingerprints(self) -> None:
        """游标停摆 vs 僵尸 assignment 是两类故障 ⇒ 指纹必须不同(否则僵尸那条被吞)。"""
        self._round("❌ 游标新鲜度: 游标停在 2026-11-16T22:20Z(落后 12 分钟)\n")
        cursor = self._fingerprint()
        out = self._round(
            "❌ 僵尸 assignment ce1d46c9: state=running 已 1.7h · '示例工单' · 最后 report: (无)\n"
        )
        self.assertNotEqual(self._fingerprint(), cursor)
        self.assertNotIn("不重复发", out)
        self.assertEqual(self._sent(), 2)

    def test_zombie_age_and_report_do_not_change_fingerprint(self) -> None:
        """同一个僵尸 assignment:已 1.7h → 2.4h、report 从「(无)」变成有字 ⇒ 指纹不变。"""
        self._round(
            "❌ 僵尸 assignment ce1d46c9: state=running 已 1.7h · '示例工单' · 最后 report: (无)\n"
        )
        first = self._fingerprint()
        out = self._round(
            "❌ 僵尸 assignment ce1d46c9: state=running 已 2.4h · '示例工单' · 最后 report: 半成品\n"
        )
        self.assertEqual(self._fingerprint(), first)
        self.assertIn("不重复发", out)
        self.assertEqual(self._sent(), 1)

    def test_second_zombie_is_a_new_fingerprint(self) -> None:
        """多出一个僵尸 assignment 是「新的一个故障」—— 不能被并进上一条的 6 小时去重里。"""
        self._round(
            "❌ 僵尸 assignment ce1d46c9: state=running 已 1.7h · '示例工单' · 最后 report: (无)\n"
        )
        out = self._round(
            "❌ 僵尸 assignment ce1d46c9: state=running 已 1.7h · '示例工单' · 最后 report: (无)\n"
            "❌ 僵尸 assignment 9f8e7d6c: state=pending 已 3.0h · '另一单' · 最后 report: (无)\n"
        )
        self.assertNotIn("不重复发", out)
        self.assertEqual(self._sent(), 2)

    def test_unknown_causes_are_not_merged(self) -> None:
        """「判不出来」的原因不同(打不开库 vs 取不到通知)⇒ 两条告警;原因里的动态细节不算新故障。"""
        self._round(
            "❓ 判不出来: 打不开 orchestrator 状态库(/root/.dsh/state/o.sqlite):unable to open\n"
            "结论:判不出来(按异常处理)\n",
            rc=2,
        )
        db_down = self._fingerprint()
        self._round(
            "❓ 判不出来: 游标新鲜度:取不到未读通知(gh api notifications 退出码 1:EOF)\n"
            "结论:判不出来(按异常处理)\n",
            rc=2,
        )
        self.assertNotEqual(self._fingerprint(), db_down)
        gh_down = self._fingerprint()
        out = self._round(
            "❓ 判不出来: 游标新鲜度:取不到未读通知(gh api notifications 退出码 1:timeout)\n"
            "结论:判不出来(按异常处理)\n",
            rc=2,
        )
        self.assertEqual(self._fingerprint(), gh_down, "同一原因的 stderr 细节不同不该算新故障")
        self.assertIn("不重复发", out)
        self.assertEqual(self._sent(), 2)

    def test_subject_is_mail_spec(self) -> None:
        """主题必须是 `[chatapp·巡检] worker — <结论>`,结论取第一个异常项名(多项写「等 N 项」)。"""
        self._round(
            "❌ 游标新鲜度: 游标停在 2026-11-16T22:20Z(落后 12 分钟)\n"
            "❌ 僵尸 assignment ce1d46c9: state=running 已 1.7h\n"
        )
        head = self._last_alert().splitlines()[0]
        self.assertEqual(head, "[chatapp·巡检] worker — 游标新鲜度 等 2 项")

    def test_subject_unknown_verdict(self) -> None:
        """判不出来时结论写「判不出来」—— 主题里不许出现 rc 之类的数字(会破坏去重)。"""
        self._round("❓ 判不出来: 打不开 orchestrator 状态库:x:unable to open\n", rc=2)
        head = self._last_alert().splitlines()[0]
        self.assertEqual(head, "[chatapp·巡检] worker — 判不出来")


class _RestartRecorder:
    """假的重启回调:只记录被调用、返回预设的退出码与输出(绝不碰真进程)。"""

    def __init__(self, rc: int = 0, output: str = "restarted") -> None:
        """记下要返回的结果。

        Args:
            rc: 假回调的退出码。
            output: 假回调的输出尾部。
        """
        self.rc = rc
        self.output = output
        self.calls = []

    def __call__(self):
        """被 `maybe_autoreheal` 调用一次,记一笔并返回预设结果。"""
        self.calls.append(1)
        return self.rc, self.output


class InstalledLayoutTests(unittest.TestCase):
    """安装布局(自包含目录)必须能跑起来 —— 这是 2026-11-17 真实踩到的坑。

    `install.sh` 把巡检器拷到 `/root/.dsh/healthcheck/` 由 systemd 直接执行,那时**仓库不在
    `sys.path` 里**。CI 红轨那一项最初写成 `from scripts import l4_intake`,装上去之后每轮
    都 `ModuleNotFoundError`,整轮巡检崩掉、只剩一条空告警发出去(正文是空的,却看不出为什么)。

    所以这里把「巡检器 + 它依赖的判据」拷进一个临时目录,在**没有仓库**的环境里真跑一次:
    能 import、能判红、退出码是 1。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        source = Path(__file__).resolve().parent
        shutil.copy(source / "superagent_health.py", os.path.join(self.tmp, "superagent_health.py"))
        shutil.copy(source / "lib" / "ci_red.py", os.path.join(self.tmp, "ci_red.py"))
        self.db = os.path.join(self.tmp, "orchestrator.sqlite")
        make_db(self.tmp).close()
        self.runs = os.path.join(self.tmp, "runs.json")
        with open(self.runs, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "workflow_runs": [
                        {
                            "name": "web",
                            "conclusion": "failure",
                            "created_at": "2026-11-16T01:00:00Z",
                            "head_sha": "abcdef1234567",
                            "html_url": "https://example.invalid/run",
                        }
                    ]
                },
                handle,
            )

    def test_runs_without_repo_on_path(self) -> None:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        done = subprocess.run(
            [
                sys.executable,
                "superagent_health.py",
                "--db",
                self.db,
                "--skip-egress",
                "--skip-cursor",
                "--skip-enqueue",
                "--ci-red",
                "1",
                "--runs-file",
                self.runs,
            ],
            cwd=self.tmp,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        self.assertNotIn("ModuleNotFoundError", done.stderr, done.stderr)
        self.assertNotIn("ImportError", done.stderr, done.stderr)
        self.assertIn("CI 红轨 web", done.stdout)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)

    def test_ci_red_module_is_the_shared_one(self) -> None:
        """仓库布局下必须拿到 `scripts.lib.ci_red` 本体,而不是另一份同名拷贝。"""
        from scripts.lib import ci_red

        self.assertIs(healthcheck.ci_red, ci_red)


if __name__ == "__main__":
    unittest.main()
