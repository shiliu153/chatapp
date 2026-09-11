from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from im import client as im_client
from users.models import Photo, PhotoStatus, Profile, ProfileStatus

from .models import BanAction, BanLog, Block, Report, ReportStatus, ReportType
from .services import log_ban_change
from .text_check import find_blocked_word

User = get_user_model()


class TextCheckTests(SimpleTestCase):
    def test_detects_blocked_word_even_with_spaces(self):
        self.assertEqual(find_blocked_word("专业代 开发票"), "代开发票")

    def test_normal_text_passes(self):
        self.assertIsNone(find_blocked_word("喜欢音乐和旅行的设计师"))

    def test_empty_text_passes(self):
        self.assertIsNone(find_blocked_word(""))


class ModerationModelTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_block_pair_is_unique(self):
        Block.objects.create(blocker=self.a, blocked=self.b)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Block.objects.create(blocker=self.a, blocked=self.b)

    def test_block_self_rejected_by_check_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Block.objects.create(blocker=self.a, blocked=self.a)

    def test_report_defaults_to_pending(self):
        report = Report.objects.create(reporter=self.a, target=self.b, type=ReportType.HARASSMENT)
        self.assertEqual(report.status, ReportStatus.PENDING)
        self.assertIsNone(report.handled_at)

    def test_ban_log_records_action(self):
        log = BanLog.objects.create(user=self.b, action=BanAction.BAN_HEAVY,
                                    reason="骚扰他人", operator=self.a)
        self.assertEqual(log.action, "ban_heavy")
        self.assertEqual(BanLog.objects.filter(user=self.b).count(), 1)

    def test_profile_has_ban_reason_field(self):
        profile = Profile.objects.create(user=self.b, ban_reason="违规")
        profile.refresh_from_db()
        self.assertEqual(profile.ban_reason, "违规")


class IsNotHeavyBannedTests(APITestCase):
    """重封禁 = 全业务 403;白名单(看自己资料/标签池)放行;轻封禁不受影响。"""

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我", gender="male", birthday="2000-01-01",
                               city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.me, file="photos/x.png", status=PhotoStatus.APPROVED)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _ban(self, status):
        Profile.objects.filter(user=self.me).update(status=status)

    def test_heavy_banned_blocked_across_business_endpoints(self):
        self._ban(ProfileStatus.BANNED_HEAVY)
        for method, url in [
            ("get", "/api/v1/discovery/candidates"),
            ("get", "/api/v1/matches"),
            ("post", "/api/v1/discovery/swipe"),
            ("post", "/api/v1/users/me/photos"),
            ("patch", "/api/v1/users/me/preference"),
        ]:
            resp = getattr(self.client, method)(url)
            self.assertEqual(resp.status_code, 403, msg=f"{method} {url} 应 403")
            self.assertEqual(resp.json()["message"], "账号已被封禁,如有疑问请联系客服")

    def test_heavy_banned_can_still_read_own_profile_and_tags(self):
        self._ban(ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/users/tags").status_code, 200)

    def test_heavy_banned_cannot_patch_own_profile(self):
        self._ban(ProfileStatus.BANNED_HEAVY)
        resp = self.client.patch("/api/v1/users/me", {"city": "北京"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_light_banned_only_swipe_blocked(self):
        self._ban(ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self.client.get("/api/v1/discovery/candidates").status_code, 200)
        # swipe 里先过序列化器再查封禁,所以要带合法 body
        resp = self.client.post("/api/v1/discovery/swipe",
                                {"target_user_id": 999999, "action": "like"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_me_exposes_ban_reason(self):
        Profile.objects.filter(user=self.me).update(
            status=ProfileStatus.BANNED_HEAVY, ban_reason="骚扰他人")
        data = self.client.get("/api/v1/users/me").json()
        self.assertEqual(data["status"], "banned_heavy")
        self.assertEqual(data["ban_reason"], "骚扰他人")


class BanAuditServiceTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_superuser(phone="13700137000", password="pw")
        self.target = User.objects.create_user(phone="13900139000")

    def test_heavy_ban_writes_log_and_kicks_offline(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            log_ban_change(self.target, ProfileStatus.COMPLETE, ProfileStatus.BANNED_HEAVY,
                           "骚扰他人", self.operator)
        log = BanLog.objects.get(user=self.target)
        self.assertEqual(log.action, BanAction.BAN_HEAVY)
        self.assertEqual(log.reason, "骚扰他人")
        self.assertEqual(log.operator, self.operator)
        dispatch.assert_called_once_with(im_client.kick_user, self.target.im_user_id)

    def test_light_ban_writes_log_without_kick(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            log_ban_change(self.target, ProfileStatus.COMPLETE, ProfileStatus.BANNED_LIGHT,
                           "轻度违规", self.operator)
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.BAN_LIGHT)
        dispatch.assert_not_called()

    def test_unban_writes_unban_log(self):
        log_ban_change(self.target, ProfileStatus.BANNED_HEAVY, ProfileStatus.COMPLETE,
                       "申诉通过", self.operator)
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.UNBAN)

    def test_non_ban_transition_writes_nothing(self):
        log_ban_change(self.target, ProfileStatus.INCOMPLETE, ProfileStatus.COMPLETE, "", self.operator)
        self.assertFalse(BanLog.objects.exists())


class ProfileAdminHookTests(TestCase):
    """admin 保存 Profile 的钩子:运营只填 状态+原因,审计自动落。"""

    def setUp(self):
        self.operator = User.objects.create_superuser(phone="13700137000", password="pw")
        self.target = User.objects.create_user(phone="13900139000")
        Profile.objects.get_or_create(user=self.target)

    def _save(self, status, reason):
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from users.admin import ProfileAdmin

        request = RequestFactory().post("/admin/")
        request.user = self.operator
        model_admin = ProfileAdmin(Profile, django_admin.site)
        obj = Profile.objects.get(user=self.target)
        obj.status = status
        obj.ban_reason = reason
        with patch("moderation.services._dispatch_async"):
            model_admin.save_model(request, obj, form=None, change=True)

    def test_heavy_ban_via_admin_writes_audit(self):
        self._save(ProfileStatus.BANNED_HEAVY, "骚扰他人")
        log = BanLog.objects.get(user=self.target)
        self.assertEqual(log.action, BanAction.BAN_HEAVY)
        self.assertEqual(log.operator, self.operator)

    def test_unban_via_admin_writes_audit(self):
        Profile.objects.filter(user=self.target).update(
            status=ProfileStatus.BANNED_HEAVY, ban_reason="骚扰他人")
        self._save(ProfileStatus.COMPLETE, "")
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.UNBAN)


class ReportAdminTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(phone="13700137000", password="pw")
        self.reporter = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        self.report = Report.objects.create(reporter=self.reporter, target=self.target,
                                            type=ReportType.HARASSMENT, detail="发骚扰消息")

    def test_handling_report_fills_handler_and_time(self):
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from .admin import ReportAdmin

        request = RequestFactory().post("/admin/")
        request.user = self.staff
        model_admin = ReportAdmin(Report, django_admin.site)
        obj = Report.objects.get(pk=self.report.pk)
        obj.status = ReportStatus.HANDLED
        obj.handled_note = "已警告"
        model_admin.save_model(request, obj, form=None, change=True)
        obj.refresh_from_db()
        self.assertEqual(obj.handled_by, self.staff)
        self.assertIsNotNone(obj.handled_at)
        self.assertEqual(obj.handled_note, "已警告")

    def test_block_and_banlog_admins_are_readonly(self):
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from .admin import BanLogAdmin, BlockAdmin

        request = RequestFactory().get("/admin/")
        request.user = self.staff
        for model, admin_cls in [(Block, BlockAdmin), (BanLog, BanLogAdmin)]:
            model_admin = admin_cls(model, django_admin.site)
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
