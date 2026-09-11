from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from im import client as im_client
from moderation.models import (BanAction, BanLog, Report, ReportStatus,
                               ReportType)
from users.models import Profile, ProfileStatus


def make_staff(phone="13700137000", password="ops-pass-123"):
    """运营账号 = is_staff 用户(create_user 默认不设密码,必须显式 set_password)。"""
    user = User.objects.create_user(phone=phone, is_staff=True)
    user.set_password(password)
    user.save(update_fields=["password"])
    return user


class OpsAuthTests(TestCase):
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
        with patch("moderation.services._dispatch_async") as dispatch:
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
        dispatch.assert_called_once_with(im_client.kick_user, self.target.im_user_id)

    def test_quick_ban_requires_reason(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(f"/ops/reports/{self.report.id}/ban",
                                    {"level": "ban_light", "reason": ""})
        self.assertContains(resp, "必须填写原因")
        profile = Profile.objects.get(user=self.target)
        self.assertEqual(profile.status, ProfileStatus.COMPLETE)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.PENDING)
        dispatch.assert_not_called()
