from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from im import client as im_client
from moderation.models import (BanAction, BanLog, Report, ReportStatus,
                               ReportType)
from users.models import Photo, PhotoStatus, Profile, ProfileStatus


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


class OpsPhotoReviewTests(TestCase):
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
    def setUp(self):
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13900139000")
        self.profile = Profile.objects.create(
            user=self.user, nickname="小红", gender="female", birthday="2000-01-01",
            city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.user, file="photos/a.png", status=PhotoStatus.APPROVED)

    def test_ban_light_records_log_without_kick(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                    {"action": "ban_light", "reason": "骚扰他人"})
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self.profile.ban_reason, "骚扰他人")
        self.assertTrue(BanLog.objects.filter(user=self.user, action=BanAction.BAN_LIGHT,
                                              operator=self.staff).exists())
        dispatch.assert_not_called()

    def test_ban_heavy_kicks_im(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            self.client.post(f"/ops/users/{self.user.id}/ban",
                             {"action": "ban_heavy", "reason": "严重违规"})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.BANNED_HEAVY)
        dispatch.assert_called_once_with(im_client.kick_user, self.user.im_user_id)

    def test_ban_requires_reason(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                    {"action": "ban_heavy", "reason": "  "})
        self.assertContains(resp, "必须填写原因")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)
        dispatch.assert_not_called()

    def test_unban_recomputes_status_and_clears_reason(self):
        with patch("moderation.services._dispatch_async"):
            self.client.post(f"/ops/users/{self.user.id}/ban",
                             {"action": "ban_light", "reason": "先封"})
        resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                {"action": "unban", "reason": ""})
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)   # 资料齐全+有照片 → 重算回已完善
        self.assertEqual(self.profile.ban_reason, "")
        self.assertTrue(BanLog.objects.filter(user=self.user, action=BanAction.UNBAN).exists())
