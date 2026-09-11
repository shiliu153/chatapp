from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from discovery.models import Match
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


class ReportApiTests(APITestCase):
    URL = "/api/v1/reports"

    def setUp(self):
        cache.clear()               # 限流计数在缓存里,用例之间必须清
        self.addCleanup(cache.clear)
        self.me = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def report(self, target_id=None, type_="harassment", detail=""):
        return self.client.post(self.URL, {
            "target_user_id": self.target.id if target_id is None else target_id,
            "type": type_,
            "detail": detail,
        }, format="json")

    def test_creates_pending_report(self):
        resp = self.report(detail="一直发骚扰消息")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["status"], "pending")
        report = Report.objects.get()
        self.assertEqual((report.reporter, report.target), (self.me, self.target))
        self.assertEqual(report.detail, "一直发骚扰消息")

    def test_duplicate_pending_report_is_idempotent(self):
        first = self.report()
        second = self.report(type_="fraud")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(Report.objects.count(), 1)

    def test_new_report_after_previous_handled(self):
        Report.objects.create(reporter=self.me, target=self.target, type="harassment",
                              status=ReportStatus.HANDLED)
        self.assertEqual(self.report().status_code, 201)
        self.assertEqual(Report.objects.count(), 2)

    def test_cannot_report_self(self):
        self.assertEqual(self.report(target_id=self.me.id).status_code, 400)

    def test_unknown_target_returns_404(self):
        self.assertEqual(self.report(target_id=999999).status_code, 404)

    def test_invalid_type_rejected(self):
        self.assertEqual(self.report(type_="spam").status_code, 400)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.report().status_code, 401)

    def test_report_throttled(self):
        from .throttles import ReportThrottle

        other = User.objects.create_user(phone="13900139001")
        with patch.object(ReportThrottle, "rate", "2/day", create=True):
            self.assertEqual(self.report(target_id=other.id).status_code, 201)
            self.assertEqual(self.report().status_code, 201)
            self.assertEqual(self.report(type_="fraud").status_code, 429)


class BlockApiTests(APITestCase):
    URL = "/api/v1/blocks"

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.target, nickname="小红", gender="female",
                               birthday="2000-01-01", city="上海", bio="你好",
                               status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.target, file="photos/x.png", status=PhotoStatus.APPROVED)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def test_block_creates_row_and_syncs_im(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(self.URL, {"target_user_id": self.target.id}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Block.objects.filter(blocker=self.me, blocked=self.target).exists())
        dispatch.assert_called_once_with(im_client.black_list_add,
                                         self.me.im_user_id, self.target.im_user_id)

    def test_duplicate_block_idempotent_without_resync(self):
        Block.objects.create(blocker=self.me, blocked=self.target)
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(self.URL, {"target_user_id": self.target.id}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Block.objects.count(), 1)
        dispatch.assert_not_called()

    def test_cannot_block_self(self):
        resp = self.client.post(self.URL, {"target_user_id": self.me.id}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_unknown_target_returns_404(self):
        resp = self.client.post(self.URL, {"target_user_id": 999999}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_list_shows_nickname_and_avatar(self):
        Block.objects.create(blocker=self.me, blocked=self.target)
        data = self.client.get(self.URL).json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["user_id"], self.target.id)
        self.assertEqual(data[0]["nickname"], "小红")
        self.assertTrue(data[0]["avatar_url"].startswith("http://testserver/media/"))

    def test_list_avatar_null_without_approved_photo(self):
        Photo.objects.update(status=PhotoStatus.PENDING)
        Block.objects.create(blocker=self.me, blocked=self.target)
        self.assertIsNone(self.client.get(self.URL).json()[0]["avatar_url"])

    def test_unblock_removes_and_syncs_im(self):
        Block.objects.create(blocker=self.me, blocked=self.target)
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.delete(f"{self.URL}/{self.target.id}")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Block.objects.exists())
        dispatch.assert_called_once_with(im_client.black_list_delete,
                                         self.me.im_user_id, self.target.im_user_id)

    def test_unblock_missing_is_idempotent(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.delete(f"{self.URL}/{self.target.id}")
        self.assertEqual(resp.status_code, 204)
        dispatch.assert_not_called()

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)


class BlockVisibilityTests(APITestCase):
    """拉黑双向不可见:候选/配对统一过滤;已有 Match 记录不删(解除后恢复)。"""

    def setUp(self):
        self.me = self._make_user("13800138000")
        self.other = self._make_user("13900139000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone):
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=phone, gender="female", birthday="2000-01-01",
                               city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def test_candidates_exclude_blocked_by_me(self):
        Block.objects.create(blocker=self.me, blocked=self.other)
        self.assertEqual(self.client.get("/api/v1/discovery/candidates").json(), [])

    def test_candidates_exclude_people_who_blocked_me(self):
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get("/api/v1/discovery/candidates").json(), [])

    def test_matches_exclude_blocked_pair(self):
        Match.objects.create(**Match.pair_kwargs(self.me, self.other))
        self.assertEqual(len(self.client.get("/api/v1/matches").json()), 1)
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get("/api/v1/matches").json(), [])

    def test_removing_block_restores_visibility(self):
        Block.objects.create(blocker=self.me, blocked=self.other).delete()
        self.assertEqual(len(self.client.get("/api/v1/discovery/candidates").json()), 1)
