"""运营审核台的测试:鉴权、举报处理、照片审核、用户管理与广场治理。

覆盖场景:
    - 鉴权:匿名跳登录、非运营 403、运营可进,登录表单拒绝非运营账号;
    - 举报列表与详情:默认只看待处理、状态过滤、详情展示双方;
    - 举报处理:标记已处理、重复处理保留首次结果、快捷封禁(必须填原因)、
      处理与封禁都只通知举报者一次;
    - 照片审核:默认只看待审核、通过记录审核人、驳回已过审照片会掉回未完善、
      页面陈旧的照片 id 记入跳过数;
    - 用户搜索与详情:手机号精确匹配、昵称模糊匹配、部分手机号不匹配;
    - 用户封禁:轻封禁只发通知、重封禁发通知并踢 IM、必须填原因、
      解封重算状态并清空原因;
    - 封禁日志:展示历史、按动作过滤;
    - 广场治理:动态列表与删除、非运营 403;
    - 动态举报队列:看待处理、忽略并通知、删动态并关闭全部待处理、重复处理不重复通知;
    - 局部刷新结构:反馈表格、动态举报表格与动态表格三处片段的 ``hx-target``
      都指向片段根 ``<article id=…>``(不是片段内部的 ``<table>``),替换后不会套娃;
    - 聊天图片抽审:列表可见、删除置 deleted 并删文件、举报详情带最近图片、非运营 403;
    - 私聊媒体审计:每次浏览落一条 ``MediaAccessLog``(含「仅被举报」筛选),审计失败不影响页面;
    - 准入名单(B-1c):列表带注册状态、加号/停用立刻生效、格式错误不落库、停用后可重新启用;
    - 准入名单操作流水(R4-B2):加号写 ``add``、停用/启用写 ``disable``/``enable``、
      只改备注不写,页面底部「最近操作」表号码脱敏;
    - 运营看板(V-2):鉴权、四个数字卡与近 30 天趋势表、可空字段渲染 ``—`` 而不是 ``0``
      (采到了 0 还是要显示 0)、只统计近 7 日窗口、「30 行一条 SQL」与「页面只读」两条门禁。
"""

import json
import os
import re
import shutil
import tempfile
import time
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts import services
from accounts import totp
from accounts.exceptions import PhoneNotAllowed
from accounts.models import (PhoneAllowlist, PhoneAllowlistAction,
                             PhoneAllowlistEvent, User)
from feed.models import Post, PostLike, PostReport
from feedback.models import Feedback, FeedbackStatus, FeedbackType
from im.models import ChatImage, ChatImageStatus, ChatVoice, ChatVoiceStatus
from moderation.models import (BanAction, BanLog, Report, ReportStatus,
                               ReportType)
from ops.models import MediaAccessLog
from ops.otp import _safe_redirect
from stats.models import DailyMetric
from users.models import Photo, PhotoStatus, Profile, ProfileStatus


def make_staff(phone="13700137000", password="ops-pass-123"):
    """运营账号 = is_staff 用户(create_user 默认不设密码,必须显式 set_password)。

    Args:
        phone: 运营账号手机号。
        password: 登录密码。

    Returns:
        建好的运营账号。
    """
    user = User.objects.create_user(phone=phone, is_staff=True)
    user.set_password(password)
    user.save(update_fields=["password"])
    return user


def make_metric(day, **fields):
    """造一行每日指标快照(未显式给的字段用一组非零默认值)。

    Args:
        day: 快照日期(``Asia/Shanghai`` 自然日)。
        **fields: 要覆盖的字段;显式传 ``None`` 表示「当天没采到」。

    Returns:
        建好的 ``DailyMetric`` 行。
    """
    defaults = {
        "dau": 10, "new_users": 3, "profiles_completed": 1,
        "swipes_like": 4, "swipes_pass": 5, "matches": 2,
        "messages": 100, "active_hours": [0] * 24,
        "retention_d1": 1, "retention_d7": 1,
    }
    defaults.update(fields)
    return DailyMetric.objects.create(date=day, **defaults)


class OpsMetricsTests(TestCase):
    """运营看板:鉴权、数字卡与趋势表、空值渲染 ``—``、空表提示、只读与查询门禁。"""

    def setUp(self):
        self.client.force_login(make_staff())
        self.today = timezone.localdate()
        self.yesterday = self.today - timedelta(days=1)

    def _body(self):
        """取一次看板页的响应正文(多数断言只需要正文里有什么)。

        Returns:
            ``str``:解码后的 HTML。
        """
        resp = self.client.get("/ops/metrics/")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get("/ops/metrics/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/ops/login/"))

    def test_non_staff_forbidden(self):
        plain = User.objects.create_user(phone="13800138007")
        self.client.force_login(plain)
        self.assertEqual(self.client.get("/ops/metrics/").status_code, 403)

    def test_staff_sees_cards_and_trend_row(self):
        make_metric(self.yesterday, dau=12, new_users=4, messages=137,
                    swipes_like=10, matches=4)
        resp = self.client.get("/ops/metrics/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '<div class="ops-stat-value" id="stat-dau">12</div>')
        self.assertContains(resp, '<div class="ops-stat-value" id="stat-new-users">4</div>')
        self.assertContains(resp, '<div class="ops-stat-value" id="stat-match-rate">40.0%</div>')
        self.assertContains(resp, '<div class="ops-stat-value" id="stat-messages">137</div>')
        self.assertContains(resp, f"<td>{self.yesterday}</td>")
        self.assertContains(resp, "<td>137</td>")

    def test_nav_has_board_entry_before_logs(self):
        body = self._body()
        self.assertIn('href="/ops/metrics/"', body)
        self.assertLess(body.index("运营看板"), body.index("日志"))

    def test_empty_table_shows_hint_without_error(self):
        body = self._body()
        self.assertIn("还没有数据", body)
        self.assertIn("metrics_daily --backfill 30", body)
        # 一行都没有时,数字卡也不能凭空变出 0
        self.assertIn('<div class="ops-stat-value" id="stat-dau">—</div>', body)
        self.assertIn('<div class="ops-stat-value" id="stat-match-rate">—</div>', body)
        self.assertIn("暂无活跃时段数据", body)

    def test_null_values_render_as_dash_not_zero(self):
        make_metric(self.yesterday, dau=None, messages=None, active_hours=None,
                    retention_d1=None, retention_d7=None)
        body = self._body()
        # 五个可空字段全部是「—」:DAU 卡片一个 + 趋势表里 DAU / 消息 / 两类留存四个
        self.assertNotIn(">0<", body)
        self.assertGreaterEqual(body.count(">—<"), 5)
        self.assertIn("当日未采集到", body)

    def test_collected_zero_still_renders_zero(self):
        make_metric(self.yesterday, dau=0, messages=0, swipes_like=0, matches=0,
                    retention_d1=0, retention_d7=0, active_hours=None)
        body = self._body()
        # 采到了 0 就是 0:只有「没采到」才渲染「—」
        self.assertIn('<div class="ops-stat-value" id="stat-dau">0</div>', body)
        self.assertIn('<div class="ops-stat-value" id="stat-messages">0</div>', body)
        self.assertGreaterEqual(body.count("<td>0</td>"), 4)

    def test_yesterday_cards_are_dash_when_yesterday_row_is_missing(self):
        # 04:30 那次没跑成:表里只有前天的行 —— 卡片不能拿前天的数字冒充「昨日」
        make_metric(self.today - timedelta(days=2), dau=77, new_users=9)
        body = self._body()
        self.assertIn('<div class="ops-stat-value" id="stat-dau">—</div>', body)
        self.assertIn('<div class="ops-stat-value" id="stat-new-users">—</div>', body)
        self.assertIn("<td>77</td>", body)

    def test_summary_covers_last_seven_days_only(self):
        for offset in range(1, 8):
            make_metric(self.today - timedelta(days=offset),
                        dau=10, swipes_like=2, matches=1, new_users=1, messages=10)
        # 窗口外(第 8 天前)的行不能进「近 7 日」汇总
        make_metric(self.today - timedelta(days=8),
                    dau=999, swipes_like=1000, matches=1000, new_users=1000, messages=999)
        body = self._body()
        self.assertIn('<div class="ops-stat-value" id="stat-match-rate">50.0%</div>', body)
        self.assertIn('<div class="ops-stat-value" id="stat-messages">70</div>', body)
        self.assertIn("近 7 日汇总(7 天)", body)

    def test_average_dau_skips_days_without_collection(self):
        make_metric(self.yesterday, dau=20)
        make_metric(self.today - timedelta(days=2), dau=None)
        self.assertIn("日均 DAU 20.0", self._body())

    def test_average_dau_is_dash_when_never_collected(self):
        make_metric(self.yesterday, dau=None)
        self.assertIn("日均 DAU —", self._body())

    def test_trend_shows_at_most_thirty_rows(self):
        for offset in range(1, 36):
            make_metric(self.today - timedelta(days=offset))
        body = self._body()
        self.assertIn(f"<td>{self.today - timedelta(days=30)}</td>", body)
        self.assertNotIn(f"<td>{self.today - timedelta(days=31)}</td>", body)

    def test_activity_bars_are_relative_to_daily_peak(self):
        hours = [0] * 24
        hours[10] = 5
        hours[11] = 10
        make_metric(self.yesterday, active_hours=hours)
        body = self._body()
        self.assertIn('style="width: 100.0%"', body)
        self.assertIn('style="width: 50.0%"', body)
        self.assertIn("10:00", body)
        self.assertIn('class="ops-hour-count">10<', body)

    def test_activity_falls_back_to_latest_row_with_hours(self):
        make_metric(self.yesterday, dau=None, active_hours=None)
        older = self.today - timedelta(days=2)
        hours = [0] * 24
        hours[3] = 7
        make_metric(older, active_hours=hours)
        body = self._body()
        self.assertIn(f"活跃时段 <small>{older}</small>", body)
        self.assertIn('class="ops-hour-count">7<', body)

    def test_malformed_active_hours_does_not_break_page(self):
        make_metric(self.yesterday, active_hours={"00": 1})
        body = self._body()
        self.assertIn("暂无活跃时段数据", body)

    def test_thirty_rows_come_from_a_single_query(self):
        for offset in range(1, 31):
            make_metric(self.today - timedelta(days=offset))
        with CaptureQueriesContext(connection) as captured:
            resp = self.client.get("/ops/metrics/")
        self.assertEqual(resp.status_code, 200)
        snapshot_sql = [q["sql"] for q in captured.captured_queries
                        if "stats_dailymetric" in q["sql"]]
        self.assertEqual(len(snapshot_sql), 1)

    def test_query_budget_is_fixed(self):
        for offset in range(1, 31):
            make_metric(self.today - timedelta(days=offset))
        # 固定预算:会话 1 + 当前用户 1 + 导航角标 4 + 快照行 1 = 7 条,与行数无关。
        # 30 行要是一条 SQL,不是循环里一条条查 —— 这条门禁红了就是退化成 N+1 了。
        with self.assertNumQueries(7):
            resp = self.client.get("/ops/metrics/")
        self.assertEqual(resp.status_code, 200)

    def test_query_count_does_not_grow_with_rows(self):
        make_metric(self.today - timedelta(days=1))
        with CaptureQueriesContext(connection) as one_row:
            self.client.get("/ops/metrics/")
        for offset in range(2, 31):
            make_metric(self.today - timedelta(days=offset))
        with CaptureQueriesContext(connection) as many_rows:
            self.client.get("/ops/metrics/")
        self.assertEqual(len(one_row.captured_queries), len(many_rows.captured_queries))

    def test_page_is_read_only(self):
        for offset in range(1, 31):
            make_metric(self.today - timedelta(days=offset))
        with CaptureQueriesContext(connection) as captured:
            self.client.get("/ops/metrics/")
        non_select = [q["sql"] for q in captured.captured_queries
                      if not q["sql"].lstrip().upper().startswith("SELECT")]
        self.assertEqual(non_select, [])


class OpsAuthTests(TestCase):
    """审核台鉴权:匿名跳登录、非运营 403、运营可进,登录表单拒绝非运营。"""

    def setUp(self):
        self.staff = make_staff()
        self.plain = User.objects.create_user(phone="13800138001")
        self.plain.set_password("pw-123456")
        self.plain.save(update_fields=["password"])

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get("/ops/reports/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/ops/login/"))

    def test_non_staff_forbidden(self):
        self.client.force_login(self.plain)
        resp = self.client.get("/ops/reports/")
        self.assertEqual(resp.status_code, 403)

    def test_staff_can_open_reports(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/ops/reports/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "举报队列")

    def test_login_rejects_non_staff(self):
        resp = self.client.post("/ops/login/",
                                {"username": "13800138001", "password": "pw-123456"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "该账号无运营权限")

    def test_login_accepts_staff(self):
        resp = self.client.post("/ops/login/",
                                {"username": "13700137000", "password": "ops-pass-123"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/ops/reports/")


class ReportListTests(TestCase):
    """举报列表页:默认只看待处理,支持按状态过滤。"""

    def setUp(self):
        self.client.force_login(make_staff())
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        # 用昵称区分两行(类型标签在筛选 tab 里也会出现,不能拿来断言行内容)
        Profile.objects.create(user=self.a, nickname="被举报甲")
        Profile.objects.create(user=self.b, nickname="被举报乙")
        Report.objects.create(reporter=self.a, target=self.b,
                              type=ReportType.HARASSMENT, detail="骚扰")   # pending → 乙
        Report.objects.create(reporter=self.b, target=self.a,
                              type=ReportType.OTHER, status=ReportStatus.HANDLED)  # → 甲

    def test_default_shows_pending_only(self):
        resp = self.client.get("/ops/reports/")
        self.assertContains(resp, "被举报乙")
        self.assertNotContains(resp, "被举报甲")

    def test_handled_filter(self):
        resp = self.client.get("/ops/reports/", {"status": "handled"})
        self.assertContains(resp, "被举报甲")
        self.assertNotContains(resp, "被举报乙")


class ReportDetailTests(TestCase):
    """举报详情页:同时展示举报人与被举报人的信息。"""

    def setUp(self):
        self.client.force_login(make_staff())
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        self.report = Report.objects.create(reporter=self.a, target=self.b,
                                            type=ReportType.HARASSMENT, detail="骚扰我")

    def test_detail_shows_both_parties(self):
        resp = self.client.get(f"/ops/reports/{self.report.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "13800138000")   # 举报人
        self.assertContains(resp, "13900139000")   # 被举报人
        self.assertContains(resp, "骚扰我")


class ReportActionTests(TestCase):
    """举报处理动作:标记已处理、重复处理保留首次、快捷封禁与通知次数。"""

    def setUp(self):
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.reporter = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.target, status=ProfileStatus.COMPLETE)
        self.report = Report.objects.create(reporter=self.reporter, target=self.target,
                                            type=ReportType.PORN, detail="色情")

    def test_handle_marks_report(self):
        resp = self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "已警告"})
        self.assertEqual(resp.status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.HANDLED)
        self.assertEqual(self.report.handled_note, "已警告")
        self.assertEqual(self.report.handled_by, self.staff)
        self.assertIsNotNone(self.report.handled_at)
        self.assertContains(resp, "已处理")

    def test_handle_twice_keeps_first(self):
        self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "第一次"})
        self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "第二次"})
        self.report.refresh_from_db()
        self.assertEqual(self.report.handled_note, "第一次")

    def test_quick_ban_heavy_bans_and_handles(self):
        with patch("im.tasks.ban_notice.delay") as delay, \
                patch("im.tasks.report_handled.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/reports/{self.report.id}/ban",
                                        {"level": "ban_heavy", "reason": "色情图片"})
        self.assertContains(resp, "已处理")
        profile = Profile.objects.get(user=self.target)
        self.assertEqual(profile.status, ProfileStatus.BANNED_HEAVY)
        self.assertEqual(profile.ban_reason, "色情图片")
        self.assertTrue(BanLog.objects.filter(user=self.target, action=BanAction.BAN_HEAVY,
                                              operator=self.staff).exists())
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.HANDLED)
        self.assertEqual(self.report.handled_note, "封禁处理")
        delay.assert_called_once_with(self.target.id, "heavy", "色情图片")

    def test_quick_ban_requires_reason(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/reports/{self.report.id}/ban",
                                        {"level": "ban_light", "reason": ""})
        self.assertContains(resp, "必须填写原因")
        profile = Profile.objects.get(user=self.target)
        self.assertEqual(profile.status, ProfileStatus.COMPLETE)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.PENDING)
        delay.assert_not_called()

    def test_handle_notifies_reporter(self):
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "已警告"})
        delay.assert_called_once_with(self.reporter.id)

    def test_handle_twice_notifies_once(self):
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "一"})
                self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "二"})
        self.assertEqual(delay.call_count, 1)

    def test_quick_ban_notifies_reporter(self):
        with patch("im.tasks.ban_notice.delay") as ban_delay, \
                patch("im.tasks.report_handled.delay") as report_delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/reports/{self.report.id}/ban",
                                 {"level": "ban_heavy", "reason": "色情图片"})
        ban_delay.assert_called_once_with(self.target.id, "heavy", "色情图片")
        report_delay.assert_called_once_with(self.reporter.id)


class OpsPhotoReviewTests(TestCase):
    """照片审核:默认只看待审核、通过记录审核人、驳回会掉回未完善、陈旧 id 计跳过。"""

    def setUp(self):
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13900139000")
        self.profile = Profile.objects.create(
            user=self.user, nickname="小红", gender="female", birthday="2000-01-01",
            city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        self.approved = Photo.objects.create(user=self.user, file="photos/a.png",
                                             status=PhotoStatus.APPROVED)
        self.pending = Photo.objects.create(user=self.user, file="photos/b.png")

    def test_grid_shows_pending_by_default(self):
        resp = self.client.get("/ops/photos/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'value="{self.pending.id}"')
        self.assertNotContains(resp, f'value="{self.approved.id}"')

    def test_single_approve_records_reviewer(self):
        resp = self.client.post("/ops/photos/review",
                                {"ids": str(self.pending.id), "action": "approve",
                                 "status": "pending"})
        self.assertEqual(resp.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PhotoStatus.APPROVED)
        self.assertEqual(self.pending.reviewed_by_id, self.staff.id)
        self.assertIsNotNone(self.pending.reviewed_at)

    def test_reject_only_approved_photo_makes_profile_incomplete(self):
        resp = self.client.post("/ops/photos/review",
                                {"ids": str(self.approved.id), "action": "reject",
                                 "status": "approved"})
        self.assertEqual(resp.status_code, 200)
        self.approved.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.approved.status, PhotoStatus.REJECTED)
        self.assertEqual(self.profile.status, ProfileStatus.INCOMPLETE)

    def test_missing_photo_id_is_skipped_with_notice(self):
        # 页面陈旧(照片已被用户删除)时,不存在的 id 只提示跳过,不报错
        resp = self.client.post("/ops/photos/review",
                                {"ids": "99999999", "action": "approve",
                                 "status": "pending"})
        self.assertContains(resp, "已跳过")


class OpsUserSearchTests(TestCase):
    """用户搜索:手机号精确匹配、昵称模糊匹配,部分手机号不匹配。"""

    def setUp(self):
        self.client.force_login(make_staff())
        self.alice = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.alice, nickname="小红")

    def test_search_by_phone_exact(self):
        resp = self.client.get("/ops/users/", {"q": "13800138000"})
        self.assertContains(resp, "小红")

    def test_search_by_nickname_substring(self):
        resp = self.client.get("/ops/users/", {"q": "小"})
        self.assertContains(resp, "13800138000")

    def test_partial_phone_does_not_match(self):
        resp = self.client.get("/ops/users/", {"q": "13800138"})
        self.assertNotContains(resp, "小红")


class OpsUserDetailTests(TestCase):
    """用户详情页:展示资料、举报与拉黑关系。"""

    def setUp(self):
        self.client.force_login(make_staff())
        self.alice = User.objects.create_user(phone="13800138000")
        self.bob = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.alice, nickname="小红")
        Report.objects.create(reporter=self.bob, target=self.alice,
                              type=ReportType.FRAUD, detail="骗钱")

    def test_detail_shows_profile_reports_and_links(self):
        resp = self.client.get(f"/ops/users/{self.alice.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "小红")
        self.assertContains(resp, "骗钱")
        self.assertContains(resp, "13900139000")   # 举报人


class OpsUserBanTests(TestCase):
    """用户封禁动作:轻封禁只发通知、重封禁发通知并踢 IM、必填原因、解封重算状态。"""

    def setUp(self):
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13900139000")
        self.profile = Profile.objects.create(
            user=self.user, nickname="小红", gender="female", birthday="2000-01-01",
            city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.user, file="photos/a.png", status=PhotoStatus.APPROVED)

    def test_ban_light_dispatches_notice_no_kick(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                        {"action": "ban_light", "reason": "骚扰他人"})
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self.profile.ban_reason, "骚扰他人")
        self.assertTrue(BanLog.objects.filter(user=self.user, action=BanAction.BAN_LIGHT,
                                              operator=self.staff).exists())
        delay.assert_called_once_with(self.user.id, "light", "骚扰他人")

    def test_ban_heavy_kicks_im(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/users/{self.user.id}/ban",
                                 {"action": "ban_heavy", "reason": "严重违规"})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.BANNED_HEAVY)
        delay.assert_called_once_with(self.user.id, "heavy", "严重违规")

    def test_ban_requires_reason(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                        {"action": "ban_heavy", "reason": "  "})
        self.assertContains(resp, "必须填写原因")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)
        delay.assert_not_called()

    def test_unban_recomputes_status_and_clears_reason(self):
        with patch("im.tasks.ban_notice.delay"), patch("im.tasks.ban_lifted.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/users/{self.user.id}/ban",
                                 {"action": "ban_light", "reason": "先封"})
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                        {"action": "unban", "reason": ""})
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)   # 资料齐全+有照片 → 重算回已完善
        self.assertEqual(self.profile.ban_reason, "")
        self.assertTrue(BanLog.objects.filter(user=self.user, action=BanAction.UNBAN).exists())


class OpsLogsTests(TestCase):
    """封禁日志页:展示历史记录,支持按动作过滤。"""

    def setUp(self):
        self.client.force_login(make_staff())
        self.user = User.objects.create_user(phone="13900139000")
        BanLog.objects.create(user=self.user, action=BanAction.BAN_LIGHT, reason="骚扰")
        BanLog.objects.create(user=self.user, action=BanAction.UNBAN, reason="申诉通过")

    def test_logs_list_shows_history(self):
        resp = self.client.get("/ops/logs/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "骚扰")
        self.assertContains(resp, "申诉通过")

    def test_filter_by_action(self):
        resp = self.client.get("/ops/logs/", {"action": "unban"})
        self.assertContains(resp, "申诉通过")
        self.assertNotContains(resp, "骚扰")   # 轻度封禁行的原因文本被过滤掉(动作名在筛选下拉里恒有,不能拿来断言)


class OpsPostsTests(TestCase):
    """广场治理:动态列表展示与删除,非运营账号 403。"""

    def setUp(self):
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.user, nickname="小红")
        self.post = Post.objects.create(author=self.user, text="违规动态")
        PostLike.objects.create(post=self.post, user=self.staff)

    def test_posts_list_shows_post(self):
        resp = self.client.get("/ops/posts/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "违规动态")
        self.assertContains(resp, "小红")

    def test_delete_removes_post(self):
        resp = self.client.post(f"/ops/posts/{self.post.id}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Post.objects.filter(pk=self.post.id).exists())

    def test_partial_root_is_hx_target(self):
        Post.objects.create(author=self.user, text="另一条动态")
        resp = self.client.post(f"/ops/posts/{self.post.id}/delete")
        html = resp.content.decode()
        targets = set(re.findall(r'hx-target="#([\w-]+)"', html))
        self.assertEqual(targets, {"posts-card"})
        self.assertTrue(html.strip().startswith('<article id="posts-card">'))

    def test_non_staff_forbidden(self):
        plain = User.objects.create_user(phone="13800138001")
        self.client.force_login(plain)
        self.assertEqual(self.client.get("/ops/posts/").status_code, 403)


class OpsPostReportsTests(TestCase):
    """动态举报队列:看待处理、忽略并通知、删动态并关闭全部待处理、重复处理不重复通知。"""

    def setUp(self):
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.reporter = User.objects.create_user(phone="13800138000")
        self.author = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.author, nickname="小红")
        self.post = Post.objects.create(author=self.author, text="被举报的动态")
        self.report = PostReport.objects.create(reporter=self.reporter, post=self.post,
                                                type="porn", detail="色情")

    def test_queue_shows_pending(self):
        resp = self.client.get("/ops/post-reports/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "被举报的动态")
        self.assertContains(resp, "色情")

    def test_ignore_marks_handled_and_notifies(self):
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/post-reports/{self.report.id}/handle",
                                        {"note": "内容没问题"})
        self.assertEqual(resp.status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.HANDLED)
        self.assertEqual(self.report.handled_note, "内容没问题")
        self.assertEqual(self.report.handled_by, self.staff)
        delay.assert_called_once_with(self.reporter.id)
        self.assertTrue(PostReport.objects.filter(pk=self.report.pk).exists())

    def test_delete_post_removes_and_closes_all_pending(self):
        second = PostReport.objects.create(reporter=self.staff, post=self.post, type="other")
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/post-reports/{self.report.id}/delete-post")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Post.objects.filter(pk=self.post.pk).exists())
        self.report.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.HANDLED)
        self.assertEqual(self.report.handled_note, "动态已删除")
        self.assertEqual(second.status, ReportStatus.HANDLED)
        self.assertEqual(delay.call_count, 2)   # 两个举报者各一次

    def test_repeat_handle_does_not_notify_again(self):
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/post-reports/{self.report.id}/handle", {"note": "一"})
                self.client.post(f"/ops/post-reports/{self.report.id}/handle", {"note": "二"})
        self.assertEqual(delay.call_count, 1)

    def test_partial_root_is_hx_target(self):
        other = Post.objects.create(author=self.author, text="另一条动态")
        PostReport.objects.create(reporter=self.staff, post=other, type="other")
        with patch("im.tasks.report_handled.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/post-reports/{self.report.id}/handle",
                                        {"note": "内容没问题"})
        html = resp.content.decode()
        targets = set(re.findall(r'hx-target="#([\w-]+)"', html))
        self.assertEqual(targets, {"post-reports-card"})
        self.assertTrue(html.strip().startswith('<article id="post-reports-card">'))

    def test_non_staff_forbidden(self):
        plain = User.objects.create_user(phone="13800138001")
        self.client.force_login(plain)
        self.assertEqual(self.client.get("/ops/post-reports/").status_code, 403)


class FeedbackOpsTests(TestCase):
    """意见反馈队列:默认待处理、筛选、标记已处理与权限。"""

    def setUp(self):
        self.staff = make_staff("13700137001")
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.user, nickname="反馈用户")
        self.pending = Feedback.objects.create(
            user=self.user, type=FeedbackType.FEATURE, content="希望增加夜间模式开关",
            contact="a@b.com")
        self.handled = Feedback.objects.create(
            user=self.user, type=FeedbackType.BUG, content="消息偶尔重复",
            status=FeedbackStatus.HANDLED)

    def test_lists_pending_by_default(self):
        resp = self.client.get("/ops/feedback/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "希望增加夜间模式开关")
        self.assertNotContains(resp, "消息偶尔重复")

    def test_filters_by_status_and_type(self):
        resp = self.client.get("/ops/feedback/?status=handled")
        self.assertContains(resp, "消息偶尔重复")
        resp = self.client.get("/ops/feedback/?status=all&type=feature")
        self.assertContains(resp, "希望增加夜间模式开关")
        self.assertNotContains(resp, "消息偶尔重复")

    def test_handle_marks_handled(self):
        resp = self.client.post(f"/ops/feedback/{self.pending.id}/handle",
                                {"note": "已记录"})
        self.assertEqual(resp.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, FeedbackStatus.HANDLED)
        self.assertEqual(self.pending.handled_note, "已记录")
        self.assertEqual(self.pending.handled_by, self.staff)
        self.assertIsNotNone(self.pending.handled_at)

    def test_handle_is_idempotent(self):
        self.client.post(f"/ops/feedback/{self.pending.id}/handle", {"note": "第一次"})
        self.client.post(f"/ops/feedback/{self.pending.id}/handle", {"note": "第二次"})
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.handled_note, "第一次")

    def test_partial_root_is_hx_target(self):
        Feedback.objects.create(user=self.user, type=FeedbackType.BUG, content="还有一条待处理")
        resp = self.client.post(f"/ops/feedback/{self.pending.id}/handle", {"note": "已记录"})
        html = resp.content.decode()
        targets = set(re.findall(r'hx-target="#([\w-]+)"', html))
        self.assertEqual(targets, {"feedback-card"})
        self.assertTrue(html.strip().startswith('<article id="feedback-card">'))

    def test_non_staff_forbidden(self):
        self.client.force_login(User.objects.create_user(phone="13900139000"))
        self.assertEqual(self.client.get("/ops/feedback/").status_code, 403)

class ChatImageOpsTests(TestCase):
    """聊天图片抽审:列表可见、删除置 deleted 且删文件、举报详情带最近图片、非运营 403。"""

    PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
               b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
               b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13900139003")
        self.image = ChatImage(owner=self.user, width=1, height=1, bytes=len(self.PNG_1PX))
        self.image.file.save("chat/c.png", ContentFile(self.PNG_1PX), save=False)
        self.image.thumb.save("chat/c_thumb.png", ContentFile(self.PNG_1PX), save=False)
        self.image.save()

    def test_lists_chat_images(self):
        response = self.client.get("/ops/chat-images/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "聊天图片")
        self.assertContains(response, self.image.thumb.url)

    def test_delete_marks_status_and_removes_files(self):
        paths = [self.image.file.path, self.image.thumb.path]
        response = self.client.post(f"/ops/chat-images/{self.image.id}/delete")
        self.assertEqual(response.status_code, 200)
        self.image.refresh_from_db()
        self.assertEqual(self.image.status, ChatImageStatus.DELETED)
        self.assertEqual(self.image.deleted_by_id, self.staff.id)
        self.assertIsNotNone(self.image.deleted_at)
        for path in paths:
            self.assertFalse(os.path.exists(path), path)
        self.assertNotContains(self.client.get("/ops/chat-images/"), self.image.thumb.url)

    def test_report_detail_shows_recent_chat_images(self):
        report = Report.objects.create(reporter=self.staff, target=self.user,
                                       type=ReportType.PORN)
        response = self.client.get(f"/ops/reports/{report.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "最近聊天图片")
        self.assertContains(response, self.image.thumb.url)

    def test_non_staff_forbidden(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/ops/chat-images/").status_code, 403)

    def test_reported_filter_only_keeps_recently_reported_owners(self):
        other = User.objects.create_user(phone="13900139004")
        other_image = ChatImage(owner=other, width=1, height=1, bytes=len(self.PNG_1PX))
        other_image.file.save("chat/o.png", ContentFile(self.PNG_1PX), save=False)
        other_image.thumb.save("chat/o_thumb.png", ContentFile(self.PNG_1PX), save=False)
        other_image.save()
        report = Report.objects.create(reporter=self.staff, target=self.user,
                                       type=ReportType.PORN)

        response = self.client.get("/ops/chat-images/?reported=1")
        self.assertContains(response, self.image.thumb.url)
        self.assertNotContains(response, other_image.thumb.url)

        # 举报超过 7 天就不再命中「仅被举报」
        Report.objects.filter(pk=report.pk).update(
            created_at=timezone.now() - timedelta(days=8))
        response = self.client.get("/ops/chat-images/?reported=1")
        self.assertNotContains(response, self.image.thumb.url)

    def test_list_writes_media_access_audit(self):
        self.client.get("/ops/chat-images/")
        log = MediaAccessLog.objects.get()
        self.assertEqual(log.staff_id, self.staff.id)
        self.assertEqual(log.kind, MediaAccessLog.Kind.IMAGE)
        self.assertEqual(log.filter, "all")
        self.assertEqual(log.count, 1)
        self.assertEqual(log.ip, "127.0.0.1")

    def test_reported_filter_is_recorded_in_audit(self):
        self.client.get("/ops/chat-images/?reported=1")
        self.assertEqual(MediaAccessLog.objects.get().filter, "reported")

    @patch("ops.views.MediaAccessLog.objects.create", side_effect=RuntimeError("db down"))
    def test_audit_failure_does_not_break_page(self, _create):
        self.assertEqual(self.client.get("/ops/chat-images/").status_code, 200)


class ChatVoiceOpsTests(TestCase):
    """聊天语音抽审:列表可试听、删除置 deleted 并删文件、举报详情带最近语音。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir, MEDIA_BASE_URL="http://cdn.test")
        override.enable()
        self.addCleanup(override.disable)
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13900139013")
        self.voice = ChatVoice(owner=self.user, duration_ms=5000, bytes=3)
        self.voice.file.save("v.m4a", ContentFile(b"abc"), save=False)
        self.voice.save()

    def test_lists_chat_voices_with_audio(self):
        response = self.client.get("/ops/chat-voices/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "聊天语音")
        self.assertContains(response, "5 秒")
        self.assertContains(response, "/media/chat/voices/")

    def test_delete_marks_status_and_removes_file(self):
        path = self.voice.file.path
        response = self.client.post(f"/ops/chat-voices/{self.voice.pk}/delete")
        self.assertEqual(response.status_code, 200)
        self.voice.refresh_from_db()
        self.assertEqual(self.voice.status, ChatVoiceStatus.DELETED)
        self.assertEqual(self.voice.deleted_by_id, self.staff.id)
        self.assertIsNotNone(self.voice.deleted_at)
        self.assertFalse(os.path.exists(path))

    def test_report_detail_shows_recent_chat_voices(self):
        report = Report.objects.create(reporter=self.staff, target=self.user,
                                       type=ReportType.PORN)
        response = self.client.get(f"/ops/reports/{report.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "最近聊天语音")

    def test_list_writes_voice_access_audit(self):
        self.client.get("/ops/chat-voices/")
        log = MediaAccessLog.objects.get()
        self.assertEqual(log.kind, MediaAccessLog.Kind.VOICE)
        self.assertEqual(log.count, 1)

    def test_non_staff_forbidden(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/ops/chat-voices/").status_code, 403)


class OpsInvalidParamTests(TestCase):
    """审核台非法参数不能 500:非数字 ``user`` 被忽略,非数字 ``ids`` 被丢弃(M10)。"""

    def setUp(self):
        """登录一个运营账号。"""
        self.staff = make_staff()
        self.client.force_login(self.staff)

    def test_non_numeric_user_filter_is_ignored(self):
        """``?user=abc`` 返回 200,而不是 ValueError 500。"""
        self.assertEqual(self.client.get("/ops/chat-images/?user=abc").status_code, 200)
        self.assertEqual(self.client.get("/ops/chat-voices/?user=abc").status_code, 200)

    def test_non_numeric_ids_are_dropped(self):
        """``ids=abc`` 不会进入 ``pk__in``,页面仍正常返回。"""
        response = self.client.post("/ops/photos/review", {"ids": "abc", "action": "approve"})
        self.assertEqual(response.status_code, 200)

    def test_unicode_digit_ids_are_dropped(self):
        """``ids=²`` 这类「isdigit 为真但 int() 会抛」的值不能 500(M-7)。"""
        response = self.client.post("/ops/photos/review", {"ids": "²", "action": "approve"})
        self.assertEqual(response.status_code, 200)


class OpsSafeRedirectTests(SimpleTestCase):
    """OTP 的 next 跳转:ALLOWED_HOSTS 为空时只允许站内相对路径(L-6)。"""

    @override_settings(ALLOWED_HOSTS=[])
    def test_absolute_url_rejected_when_allowlist_empty(self):
        """``ALLOWED_HOSTS`` 为空时不能跳到任意外部主机。"""
        response = _safe_redirect("https://evil.example.com/steal")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/ops/reports/")

    @override_settings(ALLOWED_HOSTS=[])
    def test_relative_path_allowed_when_allowlist_empty(self):
        """站内相对路径仍然可以跳。"""
        response = _safe_redirect("/ops/users/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/ops/users/")


@override_settings(OPS_OTP_REQUIRED=True)
class StaffOtpTests(TestCase):
    """运营后台强制第二因子:未验证跳转、绑定、验证后放行(H6)。"""

    def setUp(self):
        """登录一个未绑定 TOTP 的运营账号。"""
        self.staff = make_staff()
        self.client.force_login(self.staff)

    def test_staff_without_otp_is_redirected(self):
        """已登录但未过第二因子时,后台页面 302 到 /ops/otp/。"""
        response = self.client.get("/ops/reports/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/ops/otp/"))

    def test_verified_staff_passes(self):
        """session 在有效期内标记为已验证时正常放行。"""
        session = self.client.session
        session["otp_verified_at"] = int(time.time())
        session.save()
        self.assertEqual(self.client.get("/ops/reports/").status_code, 200)

    @override_settings(OPS_OTP_TTL=60)
    def test_expired_verification_is_rejected(self):
        """超过有效期后重新要求第二因子(M-6)。"""
        session = self.client.session
        session["otp_verified_at"] = int(time.time()) - 120
        session.save()
        response = self.client.get("/ops/reports/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/ops/otp/"))

    def test_setup_binds_secret_and_marks_verified(self):
        """首次绑定:提交 App 上的验证码后写入密钥并放行。"""
        self.assertEqual(self.client.get("/ops/otp/").status_code, 200)
        secret = self.client.session["otp_pending_secret"]
        response = self.client.post("/ops/otp/", {"code": totp.code_at(secret)})
        self.assertEqual(response.status_code, 302)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.totp_secret, secret)
        self.assertIn("otp_verified_at", self.client.session)

    def test_wrong_code_does_not_bind(self):
        """错误验证码不写入密钥、不置已验证。"""
        self.client.get("/ops/otp/")
        response = self.client.post("/ops/otp/", {"code": "000000"})
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.totp_secret, "")
        self.assertFalse(self.client.session.get("otp_verified_at", False))


class StaffIpAllowlistTests(TestCase):
    """后台 IP 白名单:非白名单 403,白名单放行(H6)。"""

    def setUp(self):
        """登录运营账号。"""
        self.staff = make_staff()
        self.client.force_login(self.staff)

    @override_settings(OPS_ALLOWED_IPS="10.0.0.9")
    def test_blocked_ip_is_forbidden(self):
        """测试客户端来源 127.0.0.1 不在白名单内。"""
        self.assertEqual(self.client.get("/ops/reports/").status_code, 403)

    @override_settings(OPS_ALLOWED_IPS="127.0.0.1")
    def test_allowed_ip_passes(self):
        """白名单命中时正常进入后台(测试环境默认不强制 OTP)。"""
        self.assertEqual(self.client.get("/ops/reports/").status_code, 200)


class OpsAllowlistTests(TestCase):
    """准入名单的运维入口(B-1c):列表、加号、停用,以及「改完立刻生效」。"""

    ALLOWED = "13900139000"
    NEWCOMER = "13800138000"

    def setUp(self):
        """登录运营账号,并清掉名单快照缓存(否则上一个用例的名单会漏进来)。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.staff = make_staff()
        self.client.force_login(self.staff)

    def test_anonymous_redirected_and_non_staff_forbidden(self):
        """未登录跳登录页;非运营账号 403。"""
        self.client.logout()
        self.assertEqual(self.client.get("/ops/allowlist/").status_code, 302)
        plain = User.objects.create_user(phone="13700137001")
        self.client.force_login(plain)
        self.assertEqual(self.client.get("/ops/allowlist/").status_code, 403)

    def test_lists_entries_with_note_and_registration_state(self):
        """列表展示号码、备注,并区分「已有账号」与「待首次登录」。"""
        PhoneAllowlist.objects.create(phone=self.ALLOWED, note="产品同事")
        User.objects.create_user(phone="13700137002")
        PhoneAllowlist.objects.create(phone="13700137002")
        resp = self.client.get("/ops/allowlist/?status=all")
        self.assertContains(resp, self.ALLOWED)
        self.assertContains(resp, "产品同事")
        self.assertContains(resp, "待首次登录")
        self.assertContains(resp, "已有账号")

    def test_add_creates_entry_with_operator(self):
        """加号:落库、记操作人,并在片段里回显提示。"""
        resp = self.client.post("/ops/allowlist/add",
                                {"phone": self.NEWCOMER, "note": "测试同事"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已加入名单")
        record = PhoneAllowlist.objects.get(phone=self.NEWCOMER)
        self.assertEqual(record.note, "测试同事")
        self.assertEqual(record.created_by, self.staff)
        self.assertTrue(record.is_active)

    def test_add_takes_effect_without_restart(self):
        """加号后该号码**下一次请求**就能发码(写路径清快照,不用重启 web)。"""
        PhoneAllowlist.objects.create(phone=self.ALLOWED)
        # 先把快照写热:此时新号还不存在,应被拦
        with self.assertRaises(PhoneNotAllowed):
            services.ensure_phone_allowed(self.NEWCOMER)
        self.client.post("/ops/allowlist/add", {"phone": self.NEWCOMER})
        services.ensure_phone_allowed(self.NEWCOMER)      # 不再抛
        with patch("notifications.tasks.send_sms_code.delay"):
            resp = self.client.post("/api/v1/auth/sms/send",
                                    json.dumps({"phone": self.NEWCOMER}),
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 200)

    def test_add_invalid_phone_shows_error_and_writes_nothing(self):
        """格式不对的号码只回显错误,不落库(避免「加进去却永远登不上」)。"""
        resp = self.client.post("/ops/allowlist/add", {"phone": "12345"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "手机号格式不正确")
        self.assertFalse(PhoneAllowlist.objects.exists())

    def test_add_existing_disabled_reactivates_it(self):
        """重复提交一个已停用的号码 = 重新启用(运营手上只有这一个入口)。"""
        record = PhoneAllowlist.objects.create(phone=self.ALLOWED, is_active=False)
        resp = self.client.post("/ops/allowlist/add", {"phone": self.ALLOWED, "note": "回来了"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已重新启用")
        record.refresh_from_db()
        self.assertTrue(record.is_active)
        self.assertEqual(record.note, "回来了")

    def test_toggle_disables_and_blocks_immediately(self):
        """停用:立刻 403,不重启、不等缓存过期(写路径清快照)。"""
        record = PhoneAllowlist.objects.create(phone=self.ALLOWED)
        services.ensure_phone_allowed(self.ALLOWED)       # 快照写热(此时启用)
        resp = self.client.post(f"/ops/allowlist/{record.id}/toggle")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已停用")
        record.refresh_from_db()
        self.assertFalse(record.is_active)
        with self.assertRaises(PhoneNotAllowed):
            services.ensure_phone_allowed(self.ALLOWED)
        with patch("notifications.tasks.send_sms_code.delay") as delay:
            resp = self.client.post("/api/v1/auth/sms/send",
                                    json.dumps({"phone": self.ALLOWED}),
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 40301)
        delay.assert_not_called()

    def test_toggle_reenables(self):
        """再次点击变成启用,该号码重新放行。"""
        record = PhoneAllowlist.objects.create(phone=self.ALLOWED, is_active=False)
        resp = self.client.post(f"/ops/allowlist/{record.id}/toggle")
        self.assertContains(resp, "已启用")
        services.ensure_phone_allowed(self.ALLOWED)

    def test_filters_by_status_and_keyword(self):
        """按状态与关键字筛选:启用/停用分栏,号码与备注都能搜。"""
        PhoneAllowlist.objects.create(phone=self.ALLOWED, note="设计")
        PhoneAllowlist.objects.create(phone=self.NEWCOMER, note="运营", is_active=False)
        active_page = self.client.get("/ops/allowlist/?status=active")
        self.assertContains(active_page, self.ALLOWED)
        self.assertNotContains(active_page, self.NEWCOMER)
        search_page = self.client.get("/ops/allowlist/?status=all&q=运营")
        self.assertContains(search_page, self.NEWCOMER)
        self.assertNotContains(search_page, self.ALLOWED)

    # ---- 操作流水(R4-B2):名单是安全边界,加号/启停都要能事后追到人 ----

    def test_add_records_add_event_with_operator(self):
        """新增号码写一条 ``add`` 流水,操作人是当前运营账号。"""
        self.client.post("/ops/allowlist/add",
                         {"phone": self.NEWCOMER, "note": "测试同事"})
        event = PhoneAllowlistEvent.objects.get(phone=self.NEWCOMER)
        self.assertEqual(event.action, PhoneAllowlistAction.ADD)
        self.assertEqual(event.operator, self.staff)
        self.assertEqual(event.note, "测试同事")

    def test_toggle_records_disable_then_enable(self):
        """停用再启用:依次留下 ``disable``、``enable`` 两条流水,操作人都是当前运营。"""
        record = PhoneAllowlist.objects.create(phone=self.ALLOWED)
        self.client.post(f"/ops/allowlist/{record.id}/toggle")
        self.client.post(f"/ops/allowlist/{record.id}/toggle")
        events = list(PhoneAllowlistEvent.objects.filter(phone=self.ALLOWED).order_by("id"))
        self.assertEqual([e.action for e in events],
                         [PhoneAllowlistAction.DISABLE, PhoneAllowlistAction.ENABLE])
        self.assertTrue(all(e.operator == self.staff for e in events))

    def test_add_existing_active_only_updates_note_without_event(self):
        """本来就在启用的号码重复提交(只改备注)**不写**流水,免得噪声埋掉真改动。"""
        record = PhoneAllowlist.objects.create(phone=self.ALLOWED, note="旧备注")
        resp = self.client.post("/ops/allowlist/add",
                                {"phone": self.ALLOWED, "note": "新备注"})
        self.assertContains(resp, "备注已更新")
        record.refresh_from_db()
        self.assertEqual(record.note, "新备注")
        self.assertFalse(PhoneAllowlistEvent.objects.filter(phone=self.ALLOWED).exists())

    def test_add_existing_disabled_records_enable_not_add(self):
        """重复提交已停用的号码 = 重新启用,流水记 ``enable`` 而不是 ``add``。"""
        PhoneAllowlist.objects.create(phone=self.ALLOWED, is_active=False)
        self.client.post("/ops/allowlist/add", {"phone": self.ALLOWED})
        event = PhoneAllowlistEvent.objects.get(phone=self.ALLOWED)
        self.assertEqual(event.action, PhoneAllowlistAction.ENABLE)

    def test_page_shows_recent_events_with_masked_phone(self):
        """页面底部渲染「最近操作」表:出现动作名,号码脱敏(不打全号)。"""
        PhoneAllowlistEvent.objects.create(
            phone=self.ALLOWED, action=PhoneAllowlistAction.ADD, operator=self.staff)
        resp = self.client.get("/ops/allowlist/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "最近操作")
        self.assertContains(resp, "加入名单")
        self.assertContains(resp, "139****9000")
        self.assertNotContains(resp, self.ALLOWED)
