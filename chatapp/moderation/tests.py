"""合规应用的测试:违规词、模型约束、封禁权限、审计、admin 钩子与举报/拉黑接口。

覆盖场景:
    - 违规词:去空格后仍能命中,正常文本与空文本放行;
    - 模型约束:拉黑对唯一、不能拉黑自己、举报默认待处理、审计记录动作;
    - 重封禁权限:业务接口全域 403,白名单只放行读自己的资料与标签池,
      轻封禁只挡滑卡;
    - 封禁审计:重封禁发通知并踢下线、轻封禁只发通知、解封发解封通知、
      非封禁状态变化不写审计;
    - admin 钩子:保存资料时记录审计、举报首次处理补处理人与时间且不重复通知、
      黑名单与审计页只读;
    - 举报接口:建待处理、重复幂等、处理后可再报、不能举报自己、非法类型、限流;
    - 拉黑接口:建行并同步 IM、重复拉黑不重复同步、列表带昵称头像、解除拉黑同步 IM;
    - 拉黑可见性:候选与配对双向剔除,解除后恢复。

文件信息:
    文件名称          moderation/tests.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from discovery.models import Match
from users.models import Photo, PhotoStatus, Profile, ProfileStatus

from .models import BanAction, BanLog, Block, Report, ReportStatus, ReportType
from .services import log_ban_change
from .text_check import find_blocked_word

User = get_user_model()


class TextCheckTests(SimpleTestCase):
    """违规词匹配:去空白后仍能命中,正常与空文本放行。"""

    def test_detects_blocked_word_even_with_spaces(self):
        """违禁词中间插空格同样命中,返回词库原词。"""
        self.assertEqual(find_blocked_word("专业代 开发票"), "代开发票")

    def test_normal_text_passes(self):
        """正常自我介绍不命中任何违规词。"""
        self.assertIsNone(find_blocked_word("喜欢音乐和旅行的设计师"))

    def test_empty_text_passes(self):
        """空文本直接放行,不误判。"""
        self.assertIsNone(find_blocked_word(""))


class ModerationModelTests(TestCase):
    """合规模型约束:拉黑唯一且不能拉黑自己,举报默认待处理,审计记录动作。"""

    def setUp(self):
        """每个用例前建好两个账号。

        备注信息:
            两个账号分别充当「发起方」与「被拉黑/被举报方」。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_block_pair_is_unique(self):
        """同一对 (blocker, blocked) 重复插入撞唯一约束。"""
        Block.objects.create(blocker=self.a, blocked=self.b)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Block.objects.create(blocker=self.a, blocked=self.b)

    def test_block_self_rejected_by_check_constraint(self):
        """block_not_self 检查约束在库层挡住「拉黑自己」。"""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Block.objects.create(blocker=self.a, blocked=self.a)

    def test_report_defaults_to_pending(self):
        """新建举报默认待处理,且没有处理时间。"""
        report = Report.objects.create(reporter=self.a, target=self.b, type=ReportType.HARASSMENT)
        self.assertEqual(report.status, ReportStatus.PENDING)
        self.assertIsNone(report.handled_at)

    def test_ban_log_records_action(self):
        """审计行记下动作、原因与操作人,且同一用户只落一条。"""
        log = BanLog.objects.create(user=self.b, action=BanAction.BAN_HEAVY,
                                    reason="骚扰他人", operator=self.a)
        self.assertEqual(log.action, "ban_heavy")
        self.assertEqual(BanLog.objects.filter(user=self.b).count(), 1)

    def test_profile_has_ban_reason_field(self):
        """封禁原因落在 Profile.ban_reason 上,可读回。"""
        profile = Profile.objects.create(user=self.b, ban_reason="违规")
        profile.refresh_from_db()
        self.assertEqual(profile.ban_reason, "违规")


class IsNotHeavyBannedTests(APITestCase):
    """重封禁 = 全业务 403;白名单(看自己资料/标签池)放行;轻封禁不受影响。"""

    def setUp(self):
        """每个用例前建好资料完善、带已过审照片的本人账号,并带上 access token。

        备注信息:
            资料必须 ``COMPLETE`` 且有已过审照片,否则白名单里的
            ``GET /users/me`` 会因资料不全返回别的状态码,盖掉要验的 403 判定。
        """
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我", gender="male", birthday="2000-01-01",
                               city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.me, file="photos/x.png", status=PhotoStatus.APPROVED)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _ban(self, status):
        """把当前用户资料直接改成指定状态,模拟已被封禁。

        备注信息:
            走 ``QuerySet.update`` 而不是 ``save()``,因此不会触发 Profile 的
            封禁通知与审计逻辑 —— 本用例只验权限类,要的是「库里已是封禁态」这个前提。
        """
        Profile.objects.filter(user=self.me).update(status=status)

    def test_heavy_banned_blocked_across_business_endpoints(self):
        """重封禁后五个业务接口全部 403,且文案统一。"""
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
        """重封禁仍在白名单内:读自己资料与标签池都是 200。"""
        self._ban(ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/users/tags").status_code, 200)

    def test_heavy_banned_cannot_patch_own_profile(self):
        """白名单只放行 GET:重封禁用户改自己资料仍是 403。"""
        self._ban(ProfileStatus.BANNED_HEAVY)
        resp = self.client.patch("/api/v1/users/me", {"city": "北京"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_light_banned_only_swipe_blocked(self):
        """轻封禁只看滑卡 403,候选列表照常 200。"""
        self._ban(ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self.client.get("/api/v1/discovery/candidates").status_code, 200)
        # swipe 里先过序列化器再查封禁,所以要带合法 body
        resp = self.client.post("/api/v1/discovery/swipe",
                                {"target_user_id": 999999, "action": "like"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_me_exposes_ban_reason(self):
        """``GET /users/me`` 会把封禁状态与原因一起返回,供前端展示。"""
        Profile.objects.filter(user=self.me).update(
            status=ProfileStatus.BANNED_HEAVY, ban_reason="骚扰他人")
        data = self.client.get("/api/v1/users/me").json()
        self.assertEqual(data["status"], "banned_heavy")
        self.assertEqual(data["ban_reason"], "骚扰他人")


class BanAuditServiceTests(TestCase):
    """封禁审计服务:跨封禁边界才写审计并入队对应通知。"""

    def setUp(self):
        """每个用例前建好运营账号与被操作的目标账号。

        备注信息:
            运营账号用 ``create_superuser`` 造,以便断言审计行的 ``operator``;
            调用 ``log_ban_change`` 时直接传它,不经过 admin 请求。
        """
        self.operator = User.objects.create_superuser(phone="13700137000", password="pw")
        self.target = User.objects.create_user(phone="13900139000")

    def test_heavy_ban_enqueues_notice(self):
        """重封禁写一条 ban_heavy 审计,并入队 heavy 通知(含原因)。"""
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                log_ban_change(self.target, ProfileStatus.COMPLETE, ProfileStatus.BANNED_HEAVY,
                               "骚扰他人", self.operator)
        log = BanLog.objects.get(user=self.target)
        self.assertEqual(log.action, BanAction.BAN_HEAVY)
        self.assertEqual(log.reason, "骚扰他人")
        self.assertEqual(log.operator, self.operator)
        delay.assert_called_once_with(self.target.id, "heavy", "骚扰他人")

    def test_light_ban_enqueues_notice_without_kick(self):
        """轻封禁写 ban_light 审计,入队 light 通知(踢下线由任务按级别决定)。"""
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                log_ban_change(self.target, ProfileStatus.COMPLETE, ProfileStatus.BANNED_LIGHT,
                               "轻度违规", self.operator)
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.BAN_LIGHT)
        delay.assert_called_once_with(self.target.id, "light", "轻度违规")

    def test_unban_enqueues_lifted_notice(self):
        """从封禁态回到正常:写 unban 审计并入队解封通知(只带 user id)。"""
        with patch("im.tasks.ban_lifted.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                log_ban_change(self.target, ProfileStatus.BANNED_HEAVY, ProfileStatus.COMPLETE,
                               "申诉通过", self.operator)
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.UNBAN)
        delay.assert_called_once_with(self.target.id)

    def test_non_ban_transition_writes_nothing(self):
        """非封禁边界的状态变化(资料未完善 → 完善)不写审计、不发通知。"""
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                log_ban_change(self.target, ProfileStatus.INCOMPLETE, ProfileStatus.COMPLETE,
                               "", self.operator)
        self.assertFalse(BanLog.objects.exists())
        delay.assert_not_called()


class ProfileAdminHookTests(TestCase):
    """admin 保存 Profile 的钩子:运营只填 状态+原因,审计自动落。"""

    def setUp(self):
        """每个用例前建好运营账号、目标账号与目标账号的资料行。

        备注信息:
            资料行用 ``get_or_create`` 建:``create_user`` 不一定自动建 Profile,
            而下面的 ``_save`` 要求目标已有资料行才能取到 ``obj``。
        """
        self.operator = User.objects.create_superuser(phone="13700137000", password="pw")
        self.target = User.objects.create_user(phone="13900139000")
        Profile.objects.get_or_create(user=self.target)

    def _save(self, status, reason):
        """模拟在 admin 里保存一次资料(封禁状态由参数指定)。

        备注信息:
            直接构造 ``ProfileAdmin`` 并调 ``save_model``,绕开 admin 表单与权限校验,
            只验「状态变化 → 写审计」这条钩子;通知任务一并 patch 掉,
            用例只断言审计行,不断言入队。
        """
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from users.admin import ProfileAdmin

        request = RequestFactory().post("/admin/")
        request.user = self.operator
        model_admin = ProfileAdmin(Profile, django_admin.site)
        obj = Profile.objects.get(user=self.target)
        obj.status = status
        obj.ban_reason = reason
        with patch("im.tasks.ban_notice.delay"), patch("im.tasks.ban_lifted.delay"):
            model_admin.save_model(request, obj, form=None, change=True)

    def test_heavy_ban_via_admin_writes_audit(self):
        """后台把状态改成重封禁,自动落一条 ban_heavy 审计并记下操作人。"""
        self._save(ProfileStatus.BANNED_HEAVY, "骚扰他人")
        log = BanLog.objects.get(user=self.target)
        self.assertEqual(log.action, BanAction.BAN_HEAVY)
        self.assertEqual(log.operator, self.operator)

    def test_unban_via_admin_writes_audit(self):
        """后台把重封禁改回正常,自动落一条 unban 审计。"""
        Profile.objects.filter(user=self.target).update(
            status=ProfileStatus.BANNED_HEAVY, ban_reason="骚扰他人")
        self._save(ProfileStatus.COMPLETE, "")
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.UNBAN)


class ReportAdminTests(TestCase):
    """举报 admin 钩子:首次处理补处理人与时间且只通知一次;只读页确实只读。"""

    def setUp(self):
        """每个用例前建好运营、举报人与被举报人,并落一条待处理举报。

        备注信息:
            举报用 ``type=HARASSMENT`` + 带 ``detail``,便于断言处理备注不被覆盖。
        """
        self.staff = User.objects.create_superuser(phone="13700137000", password="pw")
        self.reporter = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        self.report = Report.objects.create(reporter=self.reporter, target=self.target,
                                            type=ReportType.HARASSMENT, detail="发骚扰消息")

    def test_handling_report_fills_handler_and_time(self):
        """首次标记已处理:补 handled_by/handled_at,保留处理备注,并通知举报人一次。"""
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from .admin import ReportAdmin

        request = RequestFactory().post("/admin/")
        request.user = self.staff
        model_admin = ReportAdmin(Report, django_admin.site)
        obj = Report.objects.get(pk=self.report.pk)
        obj.status = ReportStatus.HANDLED
        obj.handled_note = "已警告"
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                model_admin.save_model(request, obj, form=None, change=True)
        obj.refresh_from_db()
        self.assertEqual(obj.handled_by, self.staff)
        self.assertIsNotNone(obj.handled_at)
        self.assertEqual(obj.handled_note, "已警告")
        delay.assert_called_once_with(self.reporter.id)

    def test_resaving_handled_report_does_not_notify_again(self):
        """已处理过的举报再保存一次,不会重复通知举报人。"""
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from .admin import ReportAdmin

        request = RequestFactory().post("/admin/")
        request.user = self.staff
        model_admin = ReportAdmin(Report, django_admin.site)
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                first = Report.objects.get(pk=self.report.pk)
                first.status = ReportStatus.HANDLED
                model_admin.save_model(request, first, form=None, change=True)
                second = Report.objects.get(pk=self.report.pk)
                model_admin.save_model(request, second, form=None, change=True)
        self.assertEqual(delay.call_count, 1)

    def test_block_and_banlog_admins_are_readonly(self):
        """黑名单页与审计页的增/改/删权限全部为 False。"""
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
    """举报接口:建待处理、重复幂等、处理后可再报、拒绝自举报、非法类型与限流。"""

    URL = "/api/v1/reports"

    def setUp(self):
        """每个用例前清掉限流计数,建好本人与被举报人,并带上 access token。

        备注信息:
            举报额度是 ``20/day`` 且计数落在缓存里,不清缓存会跨用例累计;
            ``addCleanup(cache.clear)`` 保证用例结束后也清一次。
        """
        cache.clear()               # 限流计数在缓存里,用例之间必须清
        self.addCleanup(cache.clear)
        self.me = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def report(self, target_id=None, type_="harassment", detail=""):
        """提交一次举报。

        参数说明:
            target_id: 被举报人账号 id;``None`` 表示用 ``self.target``。
            type_: 举报类型。
            detail: 补充说明。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.report(target_id=self.me.id)``

        备注信息:
            固定 POST 到 ``self.URL``(``/api/v1/reports``),``format="json"``;
            返回原始响应,由各用例断言状态码与 body。
        """
        return self.client.post(self.URL, {
            "target_user_id": self.target.id if target_id is None else target_id,
            "type": type_,
            "detail": detail,
        }, format="json")

    def test_creates_pending_report(self):
        """首次举报返回 201 + pending,举报人/被举报人/补充说明都落对。"""
        resp = self.report(detail="一直发骚扰消息")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["status"], "pending")
        report = Report.objects.get()
        self.assertEqual((report.reporter, report.target), (self.me, self.target))
        self.assertEqual(report.detail, "一直发骚扰消息")

    def test_duplicate_pending_report_is_idempotent(self):
        """已有待处理举报时再次提交回 200 + 原记录,不新增行。"""
        first = self.report()
        second = self.report(type_="fraud")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(Report.objects.count(), 1)

    def test_new_report_after_previous_handled(self):
        """上一条举报处理完后可以再次举报同一人(去重键已清空)。"""
        Report.objects.create(reporter=self.me, target=self.target, type="harassment",
                              status=ReportStatus.HANDLED)
        self.assertEqual(self.report().status_code, 201)
        self.assertEqual(Report.objects.count(), 2)

    def test_dedupe_key_blocks_duplicate_pending(self):
        """并发/重复提交同一对用户的待处理举报,唯一约束只放行一条(M12)。"""
        Report.objects.create(reporter=self.me, target=self.target, type="harassment")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Report.objects.create(reporter=self.me, target=self.target, type="fraud")

    def test_dedupe_key_is_cleared_when_handled(self):
        """处理完成后清空去重键,允许之后再次举报同一人。"""
        report = Report.objects.create(reporter=self.me, target=self.target, type="harassment")
        self.assertIsNotNone(report.dedupe_key)
        report.status = ReportStatus.HANDLED
        report.save(update_fields=["status"])
        report.refresh_from_db()
        self.assertIsNone(report.dedupe_key)

    def test_cannot_report_self(self):
        """举报自己返回 400。"""
        self.assertEqual(self.report(target_id=self.me.id).status_code, 400)

    def test_unknown_target_returns_404(self):
        """被举报人不存在返回 404。"""
        self.assertEqual(self.report(target_id=999999).status_code, 404)

    def test_invalid_type_rejected(self):
        """举报类型不在枚举内返回 400。"""
        self.assertEqual(self.report(type_="spam").status_code, 400)

    def test_requires_auth(self):
        """未登录提交举报返回 401。"""
        self.client.credentials()
        self.assertEqual(self.report().status_code, 401)

    def test_report_throttled(self):
        """额度用尽后第 3 次提交回 429(读列表不受影响)。"""
        from .throttles import ReportThrottle

        other = User.objects.create_user(phone="13900139001")
        with patch.object(ReportThrottle, "rate", "2/day", create=True):
            self.assertEqual(self.report(target_id=other.id).status_code, 201)
            self.assertEqual(self.report().status_code, 201)
            self.assertEqual(self.report(type_="fraud").status_code, 429)


class BlockApiTests(APITestCase):
    """拉黑接口:建行并同步 IM、重复拉黑不重复同步、列表带昵称头像、解除拉黑同步 IM。"""

    URL = "/api/v1/blocks"

    def setUp(self):
        """每个用例前建好本人、目标账号与目标账号的资料/照片,并带上 access token。

        备注信息:
            目标账号必须有 ``COMPLETE`` 资料与已过审照片,列表用例才能断言
            昵称与头像;测「无已过审照片」的用例自己把照片改成待审即可。
        """
        self.me = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.target, nickname="小红", gender="female",
                               birthday="2000-01-01", city="上海", bio="你好",
                               status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.target, file="photos/x.png", status=PhotoStatus.APPROVED)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def test_block_creates_row_and_syncs_im(self):
        """首次拉黑落库并返回 201,同时入队同步 IM 黑名单一次。"""
        with patch("im.tasks.blacklist_add.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(self.URL, {"target_user_id": self.target.id}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Block.objects.filter(blocker=self.me, blocked=self.target).exists())
        delay.assert_called_once_with(self.me.id, self.target.id)

    def test_duplicate_block_idempotent_without_resync(self):
        """重复拉黑回 200、不新增行,也不再入队同步 IM。"""
        Block.objects.create(blocker=self.me, blocked=self.target)
        with patch("im.tasks.blacklist_add.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(self.URL, {"target_user_id": self.target.id}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Block.objects.count(), 1)
        delay.assert_not_called()

    def test_cannot_block_self(self):
        """拉黑自己返回 400。"""
        resp = self.client.post(self.URL, {"target_user_id": self.me.id}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_unknown_target_returns_404(self):
        """拉黑不存在的账号返回 404。"""
        resp = self.client.post(self.URL, {"target_user_id": 999999}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_block_write_throttled(self):
        """拉黑写操作按用户限流,超限 429;读列表不计入(M7)。"""
        from .throttles import BlockThrottle

        cache.clear()
        with patch("im.tasks.blacklist_add.delay"), \
                patch.object(BlockThrottle, "rate", "2/hour", create=True):
            self.assertEqual(self.client.post(
                self.URL, {"target_user_id": self.target.id}, format="json").status_code, 201)
            self.assertEqual(self.client.post(
                self.URL, {"target_user_id": self.target.id}, format="json").status_code, 200)
            self.assertEqual(self.client.post(
                self.URL, {"target_user_id": self.target.id}, format="json").status_code, 429)
            self.assertEqual(self.client.get(self.URL).status_code, 200)

    def test_list_shows_nickname_and_avatar(self):
        """黑名单列表带对方昵称与已过审照片的绝对 URL。"""
        Block.objects.create(blocker=self.me, blocked=self.target)
        data = self.client.get(self.URL).json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["user_id"], self.target.id)
        self.assertEqual(data["results"][0]["nickname"], "小红")
        self.assertTrue(data["results"][0]["avatar_url"].startswith("http://testserver/media/"))

    def test_list_avatar_null_without_approved_photo(self):
        """没有已过审照片时头像字段是 null,不是空串或报错。"""
        Photo.objects.update(status=PhotoStatus.PENDING)
        Block.objects.create(blocker=self.me, blocked=self.target)
        self.assertIsNone(self.client.get(self.URL).json()["results"][0]["avatar_url"])

    def test_unblock_removes_and_syncs_im(self):
        """解除拉黑返回 204,删本地行并入队移除 IM 黑名单。"""
        Block.objects.create(blocker=self.me, blocked=self.target)
        with patch("im.tasks.blacklist_remove.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.delete(f"{self.URL}/{self.target.id}")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Block.objects.exists())
        delay.assert_called_once_with(self.me.id, self.target.id)

    def test_unblock_missing_is_idempotent(self):
        """没有该条拉黑记录时也返回 204,且不触发 IM 同步。"""
        with patch("im.tasks.blacklist_remove.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.delete(f"{self.URL}/{self.target.id}")
        self.assertEqual(resp.status_code, 204)
        delay.assert_not_called()

    def test_requires_auth(self):
        """未登录读黑名单返回 401。"""
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)


class BlockVisibilityTests(APITestCase):
    """拉黑双向不可见:候选/配对统一过滤;已有 Match 记录不删(解除后恢复)。"""

    def setUp(self):
        """每个用例前造好两个资料完善的账号,并给客户端带上本人的 access token。

        备注信息:
            两个账号都有已过审照片,否则候选池会因为资料不全而本来就是空的,
            测不出「拉黑导致的不可见」。
        """
        self.me = self._make_user("13800138000")
        self.other = self._make_user("13900139000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone):
        """造一个资料完善、带已过审照片的用户。

        备注信息:
            昵称直接用手机号,断言候选列表时便于辨认;资料状态固定 ``COMPLETE``,
            照片固定 ``APPROVED``,保证该用户本来可以出现在候选池里。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=phone, gender="female", birthday="2000-01-01",
                               city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def test_candidates_exclude_blocked_by_me(self):
        """我拉黑的人不再出现在候选池。"""
        Block.objects.create(blocker=self.me, blocked=self.other)
        self.assertEqual(self.client.get("/api/v1/discovery/candidates").json(), [])

    def test_candidates_exclude_people_who_blocked_me(self):
        """拉黑我的人同样从我的候选池消失(可见性按双向算)。"""
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get("/api/v1/discovery/candidates").json(), [])

    def test_matches_exclude_blocked_pair(self):
        """配对记录本身不删,但拉黑后不再出现在配对列表里。"""
        Match.objects.create(**Match.pair_kwargs(self.me, self.other))
        self.assertEqual(len(self.client.get("/api/v1/matches").json()["results"]), 1)
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get("/api/v1/matches").json()["results"], [])

    def test_removing_block_restores_visibility(self):
        """拉黑又解除后,对方重新出现在候选池。"""
        Block.objects.create(blocker=self.me, blocked=self.other).delete()
        self.assertEqual(len(self.client.get("/api/v1/discovery/candidates").json()), 1)
