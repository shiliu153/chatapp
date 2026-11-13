"""``scripts/superagent-health/healthcheck.py`` 的离线自测。

巡检器坏掉的后果是**两种静默**:要么把「正常」报成异常(人被噪音训练成不看告警),
要么把「异常」报成正常(比没有巡检更糟 —— 会给主人一个虚假的安全感)。所以判定逻辑
全部用构造快照钉住,不联网、不碰真实 orchestrator 状态库。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
