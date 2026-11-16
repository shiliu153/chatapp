"""``scripts/lib/mail.py`` 的离线自测(不联网、不读真实凭据)。

为什么这些用例非有不可
----------------------
发信内核坏掉的三种方式都**不会自己喊**:

1. 主题格式漂了 —— 收件箱里又变成「每封信长得一样」,没有任何测试会红;
2. 去重坏了 —— 要么每 15 分钟一封(人会把告警关掉),要么把真故障吞掉;
3. 失败被吞了 —— 巡检以为发过了,`systemd` 全绿,告警一封都没到。

所以这里把主题、去重、配额、失败语义逐条钉住,并额外把
``docs/ops/mail.md`` 的主题表和代码里的封闭枚举做**双向比对**:文档与实现
只允许同时改,单独改一边就红。
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib import mail

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIL_DOC = REPO_ROOT / "docs" / "ops" / "mail.md"


class FakeClock:
    """可推进的时钟,用来验证去重窗口与配额窗口。"""

    def __init__(self) -> None:
        """从固定时刻起步,让用例与真实时间无关。"""
        self.moment = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        """返回当前(假)时间。"""
        return self.moment

    def advance(self, **kwargs) -> None:
        """把时钟往前推。"""
        self.moment = self.moment + timedelta(**kwargs)


class Recorder:
    """假投递实现:只记下被投递的信,不发出去。"""

    def __init__(self, fail_times: int = 0) -> None:
        """可配置「前 N 次投递失败」,用来验证重试与失败语义。"""
        self.calls = []
        self.fail_times = fail_times

    def __call__(self, config, subject: str, body: str, level: str) -> None:
        """记录一次投递;按 ``fail_times`` 决定这次是否抛错。"""
        self.calls.append({"subject": subject, "body": body, "level": level})
        if self.fail_times > 0:
            self.fail_times -= 1
            raise OSError("连接被重置")


def make_config(tmp: str, **overrides) -> mail.MailConfig:
    """造一份指向临时目录的配置(状态库与日志都不污染真实环境)。

    Args:
        tmp: 临时目录。
        **overrides: 需要覆盖的字段。

    Returns:
        配置对象。
    """
    base = mail.MailConfig(
        smtp_url="smtps://smtpdm.aliyun.com:465",
        mail_from="bot@example.com",
        mail_to="owner@example.com",
        state_db=os.path.join(tmp, "state.db"),
        log_path=os.path.join(tmp, "mail.jsonl"),
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class SubjectTests(unittest.TestCase):
    """主题格式:三段固定、类别封闭、换行拒收。"""

    def test_all_categories_render(self):
        for category in mail.CATEGORIES:
            line = mail.render_subject(category, "worker", "游标停摆")
            self.assertEqual(line, f"[chatapp·{category}] worker — 游标停摆")

    def test_unknown_category_rejected(self):
        with self.assertRaises(mail.MailError) as caught:
            mail.render_subject("通知", "worker", "游标停摆")
        self.assertIn("封闭枚举", str(caught.exception))

    def test_newline_in_subject_rejected(self):
        with self.assertRaises(mail.MailError):
            mail.render_subject("巡检", "worker\nBcc: evil@example.com", "游标停摆")

    def test_newline_in_verdict_rejected(self):
        with self.assertRaises(mail.MailError):
            mail.render_subject("巡检", "worker", "游标停摆\r\nX-Injected: 1")

    def test_blank_fields_rejected(self):
        with self.assertRaises(mail.MailError):
            mail.render_subject("巡检", "   ", "游标停摆")
        with self.assertRaises(mail.MailError):
            mail.render_subject("巡检", "worker", "")

    def test_whitespace_collapsed(self):
        line = mail.render_subject("巡检", "  worker  ", "游标   停摆")
        self.assertEqual(line, "[chatapp·巡检] worker — 游标 停摆")

    def test_verdict_truncated(self):
        line = mail.render_subject("巡检", "worker", "停摆" * 100)
        self.assertLessEqual(len(line), len("[chatapp·巡检] worker — ") + mail.VERDICT_MAX)
        self.assertTrue(line.endswith("…"))

    def test_level_validated(self):
        with self.assertRaises(mail.MailError):
            mail.MailMessage("巡检", "worker", "停摆", level="fatal").subject_line()


class DocsTableTests(unittest.TestCase):
    """`docs/ops/mail.md` 的主题表与代码里的封闭枚举必须同时改。"""

    #: 文档里除真实示例外还有一条「格式模板」(`<类别>` 这类占位符)。占位符不是示例:
    #: 它既不参与「类别是否合法」的判定,也不参与「能否原样复现」的判定。
    TEMPLATE_MARKERS = ("<", "…")

    def is_template(self, *parts: str) -> bool:
        """判断这几个字段是不是模板占位符。

        Args:
            *parts: 待判定的字段(类别 / 对象 / 结论)。

        Returns:
            命中任一占位符标记即为 True。
        """
        return any(marker in part for part in parts for marker in self.TEMPLATE_MARKERS)

    def read_doc(self) -> str:
        self.assertTrue(MAIL_DOC.is_file(), f"缺少主题规范文档:{MAIL_DOC}")
        return MAIL_DOC.read_text(encoding="utf-8")

    def test_every_category_documented(self):
        text = self.read_doc()
        for category in mail.CATEGORIES:
            self.assertIn(f"·{category}]", text, f"文档里没有类别「{category}」的示例主题")

    def test_no_undocumented_category(self):
        text = self.read_doc()
        used = {name for name in re.findall(r"\[chatapp·([^\]`]+)\]", text) if not self.is_template(name)}
        self.assertTrue(used, "文档里一条示例主题都没有")
        self.assertEqual(used - set(mail.CATEGORIES), set(), "文档里出现了枚举外的类别")

    def test_examples_are_reproducible(self):
        """文档里给出的每条示例,都必须能被 render_subject 原样复现。"""
        text = self.read_doc()
        examples = re.findall(
            r"`(\[chatapp·([^\]`]+)\] ([^`]+?) — ([^`]+))`", text
        )
        real = [
            item for item in examples if not self.is_template(item[1], item[2], item[3])
        ]
        self.assertGreaterEqual(len(real), 6, "主题表的示例太少,可能解析失败")
        for whole, category, subject, verdict in real:
            self.assertEqual(mail.render_subject(category, subject, verdict), whole)


class DeliveryTests(unittest.TestCase):
    """去重、配额、失败语义:三者错一个,告警就不可信。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.clock = FakeClock()

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, recorder, **overrides):
        config = make_config(self.tmp, **overrides)
        return mail.Mailer(
            config,
            transport=recorder,
            now=self.clock.now,
            sleep=lambda _seconds: None,
        )

    def message(self, **kwargs) -> mail.MailMessage:
        payload = {
            "category": "巡检",
            "subject": "worker",
            "verdict": "游标停摆",
            "body": "详情",
            "level": "error",
        }
        payload.update(kwargs)
        return mail.MailMessage(**payload)

    def test_sent_once_without_key(self):
        recorder = Recorder()
        mailer = self.build(recorder)
        first = mailer.send(self.message())
        second = mailer.send(self.message())
        self.assertEqual(first.outcome, mail.SENT)
        self.assertEqual(second.outcome, mail.SENT)
        self.assertEqual(len(recorder.calls), 2, "没有去重键时不该抑制重复")

    def test_dedup_within_window(self):
        recorder = Recorder()
        mailer = self.build(recorder)
        mailer.send(self.message(dedup_key="fp-1"))
        self.clock.advance(minutes=5)
        again = mailer.send(self.message(dedup_key="fp-1"))
        self.assertEqual(again.outcome, mail.DEDUPED)
        self.assertFalse(again.delivered())
        self.assertEqual(len(recorder.calls), 1)

    def test_dedup_expires_after_window(self):
        recorder = Recorder()
        mailer = self.build(recorder)
        mailer.send(self.message(dedup_key="fp-1", dedup_window_minutes=60))
        self.clock.advance(minutes=61)
        again = mailer.send(self.message(dedup_key="fp-1", dedup_window_minutes=60))
        self.assertEqual(again.outcome, mail.SENT)
        self.assertEqual(len(recorder.calls), 2)

    def test_per_minute_quota(self):
        recorder = Recorder()
        mailer = self.build(recorder, per_minute=1)
        mailer.send(self.message())
        with self.assertRaises(mail.MailError) as caught:
            mailer.send(self.message())
        self.assertIn("每分钟配额", str(caught.exception))

    def test_per_day_quota(self):
        recorder = Recorder()
        mailer = self.build(recorder, per_minute=10, per_day=1)
        mailer.send(self.message())
        self.clock.advance(minutes=5)
        with self.assertRaises(mail.MailError) as caught:
            mailer.send(self.message())
        self.assertIn("每日配额", str(caught.exception))

    def test_transport_failure_raises_and_keeps_no_state(self):
        recorder = Recorder(fail_times=mail.RETRY_ATTEMPTS)
        mailer = self.build(recorder)
        with self.assertRaises(mail.MailError):
            mailer.send(self.message(dedup_key="fp-1"))
        # 失败不能记去重键,也不能占配额:下一轮必须还能重发。
        self.assertEqual(len(recorder.calls), mail.RETRY_ATTEMPTS, "应当按契约重试")
        self.clock.advance(minutes=1)
        retry = self.build(Recorder()).send(self.message(dedup_key="fp-1"))
        self.assertEqual(retry.outcome, mail.SENT)

    def test_retry_recovers(self):
        recorder = Recorder(fail_times=1)
        mailer = self.build(recorder)
        result = mailer.send(self.message())
        self.assertEqual(result.outcome, mail.SENT)
        self.assertEqual(len(recorder.calls), 2)

    def test_dry_run_sends_nothing(self):
        recorder = Recorder()
        mailer = self.build(recorder, dry_run=True)
        result = mailer.send(self.message(dedup_key="fp-1"))
        self.assertEqual(result.outcome, mail.DRY_RUN)
        self.assertEqual(recorder.calls, [])
        # dry-run 不占配额、不记去重:紧接着真发一封必须还能发出去。
        self.clock.advance(minutes=1)
        real = self.build(Recorder()).send(self.message(dedup_key="fp-1"))
        self.assertEqual(real.outcome, mail.SENT)

    def test_body_carries_level_and_body(self):
        recorder = Recorder()
        self.build(recorder).send(self.message(body="落后 12 分钟"))
        body = recorder.calls[0]["body"]
        self.assertIn("级别: error", body)
        self.assertIn("类别: 巡检", body)
        self.assertIn("落后 12 分钟", body)

    def test_log_written(self):
        recorder = Recorder()
        config = make_config(self.tmp)
        self.build(recorder).send(self.message())
        lines = Path(config.log_path).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn('"outcome": "sent"', lines[0])


class ConfigTests(unittest.TestCase):
    """配置解析与 CLI:配错要当场红,而不是「发不出去却没人知道」。"""

    def test_missing_reports_required_names(self):
        config = mail.MailConfig.from_env({})
        self.assertEqual(config.missing(), ["MAIL_SMTP_URL", "MAIL_FROM", "MAIL_TO"])

    def test_complete_config(self):
        config = mail.MailConfig.from_env(
            {
                "MAIL_SMTP_URL": "smtps://smtpdm.aliyun.com:465",
                "MAIL_FROM": "bot@example.com",
                "MAIL_TO": "owner@example.com",
                "MAIL_PER_DAY": "20",
                "MAIL_DRY_RUN": "on",
            }
        )
        self.assertEqual(config.missing(), [])
        self.assertEqual(config.per_day, 20)
        self.assertTrue(config.dry_run)

    def test_bad_number_falls_back(self):
        config = mail.MailConfig.from_env({"MAIL_PER_DAY": "很多"})
        self.assertEqual(config.per_day, mail.PER_DAY_DEFAULT)

    def test_parse_smtp_url(self):
        self.assertEqual(
            mail._parse_smtp_url("smtps://smtpdm.aliyun.com:465"),
            ("smtpdm.aliyun.com", 465, True),
        )
        self.assertEqual(
            mail._parse_smtp_url("smtp://mail.example.com:587"),
            ("mail.example.com", 587, False),
        )
        self.assertEqual(mail._parse_smtp_url("smtps://mail.example.com"), ("mail.example.com", 465, True))

    def test_parse_smtp_url_rejects(self):
        for bad in ("smtpdm.aliyun.com:465", "http://mail.example.com:80", "smtps://:465"):
            with self.assertRaises(mail.MailError):
                mail._parse_smtp_url(bad)

    def test_cli_subject(self):
        self.assertEqual(
            mail.main(["subject", "--category", "告警", "--subject", "MySQL", "--verdict", "已拉起"]),
            0,
        )

    def test_cli_check_fails_when_config_missing(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mail.main(["check"]), 1)

    def test_cli_send_fails_when_config_missing(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                mail.main(
                    [
                        "send",
                        "--category",
                        "巡检",
                        "--subject",
                        "worker",
                        "--verdict",
                        "游标停摆",
                        "--body",
                        "详情",
                    ]
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
