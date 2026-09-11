from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from users.models import Profile

from .models import BanAction, BanLog, Block, Report, ReportStatus, ReportType
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
