"""``scripts/superagent-health/healthcheck.py`` 的离线自测。

巡检器坏掉的后果是**两种静默**:要么把「正常」报成异常(人被噪音训练成不看告警),
要么把「异常」报成正常(比没有巡检更糟 —— 会给主人一个虚假的安全感)。所以判定逻辑
全部用构造快照钉住,不联网、不碰真实 orchestrator 状态库。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import superagent_health as healthcheck  # noqa: E402


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
                return sum(1 for line in handle if line.startswith("[superagent]"))
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


if __name__ == "__main__":
    unittest.main()
