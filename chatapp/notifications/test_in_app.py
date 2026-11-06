"""站内通知(H-1)的测试:模型、服务层、偏好过滤、幂等与过期清理。

覆盖场景:
    - ``notify`` 落库的字段形状与正文截断;
    - 三类偏好开关(``social`` / ``match`` / ``system``)关闭后不落库;
    - ``dedupe_key`` 幂等(同一事件重复触发只留一条);
    - ``notify_on_commit`` 在事务提交后才写库,接收者已注销时安静跳过;
    - ``notifications_prune`` 命令:默认 dry-run 不删、``--apply`` 只删过期;
    - 通知随接收者级联删除,触发者注销后通知仍在(``SET_NULL``)。
"""

from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from notifications.models import (InAppNotification, NotificationKind, NotificationPreference,
                                  NotificationTarget)
from notifications.services import notify, notify_on_commit

User = get_user_model()


class InAppNotificationModelTests(TestCase):
    """模型:排序、级联与触发者置空。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        self.actor = User.objects.create_user(phone="13900139000")

    def _create(self, **overrides):
        """造一条通知(默认参数可被覆盖)。

        Args:
            **overrides: 覆盖 ``InAppNotification.objects.create`` 的字段。

        Returns:
            新建的通知。
        """
        fields = {
            "user": self.user,
            "kind": NotificationKind.POST_LIKE,
            "actor": self.actor,
            "target_kind": NotificationTarget.POST,
            "target_id": 7,
            "text": "有人赞了你的动态",
        }
        fields.update(overrides)
        return InAppNotification.objects.create(**fields)

    def test_ordering_is_created_at_then_id_desc(self):
        first = self._create(text="第一条")
        second = self._create(text="第二条")
        self.assertEqual(list(InAppNotification.objects.all()), [second, first])

    def test_deleted_with_receiver(self):
        self._create()
        self.user.delete()
        self.assertFalse(InAppNotification.objects.exists())

    def test_actor_deletion_keeps_notification(self):
        self._create()
        self.actor.delete()
        notification = InAppNotification.objects.get()
        self.assertIsNone(notification.actor_id)


class NotifyServiceTests(TestCase):
    """服务层:字段落库、偏好过滤、幂等与提交时机。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        self.actor = User.objects.create_user(phone="13900139000")

    def test_notify_writes_expected_fields(self):
        notification = notify(self.user, NotificationKind.POST_LIKE, actor=self.actor,
                              target_kind=NotificationTarget.POST, target_id=9,
                              text="小明 赞了你的动态")
        self.assertIsNotNone(notification)
        self.assertEqual(notification.user_id, self.user.id)
        self.assertEqual(notification.kind, NotificationKind.POST_LIKE)
        self.assertEqual(notification.actor_id, self.actor.id)
        self.assertEqual(notification.target_kind, NotificationTarget.POST)
        self.assertEqual(notification.target_id, 9)
        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.dedupe_key)

    def test_text_is_truncated_to_200(self):
        notification = notify(self.user, NotificationKind.SYSTEM, text="很" * 300)
        self.assertEqual(len(notification.text), 200)

    def test_unknown_kind_is_not_written(self):
        self.assertIsNone(notify(self.user, "promo", text="广告"))
        self.assertFalse(InAppNotification.objects.exists())

    def test_social_switch_off_blocks_post_events(self):
        NotificationPreference.objects.create(user=self.user, social=False)
        for kind in (NotificationKind.POST_LIKE, NotificationKind.POST_COMMENT,
                     NotificationKind.COMMENT_REPLY):
            self.assertIsNone(notify(self.user, kind, actor=self.actor, text="x"))
        self.assertFalse(InAppNotification.objects.exists())

    def test_match_switch_off_blocks_match_event(self):
        NotificationPreference.objects.create(user=self.user, matches=False)
        self.assertIsNone(notify(self.user, NotificationKind.MATCH, actor=self.actor, text="x"))
        self.assertFalse(InAppNotification.objects.exists())

    def test_system_switch_off_blocks_report_event(self):
        NotificationPreference.objects.create(user=self.user, system=False)
        self.assertIsNone(notify(self.user, NotificationKind.REPORT_HANDLED, text="x"))
        self.assertFalse(InAppNotification.objects.exists())

    def test_social_switch_does_not_block_match(self):
        NotificationPreference.objects.create(user=self.user, social=False)
        self.assertIsNotNone(notify(self.user, NotificationKind.MATCH, actor=self.actor,
                                    text="配对成功"))

    def test_dedupe_key_keeps_one_row(self):
        first = notify(self.user, NotificationKind.POST_LIKE, actor=self.actor,
                       dedupe_key="like:9:2", text="小明 赞了你的动态")
        second = notify(self.user, NotificationKind.POST_LIKE, actor=self.actor,
                        dedupe_key="like:9:2", text="小明 赞了你的动态")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(InAppNotification.objects.count(), 1)

    def test_different_dedupe_keys_create_two_rows(self):
        notify(self.user, NotificationKind.POST_COMMENT, dedupe_key="comment:1", text="a")
        notify(self.user, NotificationKind.POST_COMMENT, dedupe_key="comment:2", text="b")
        self.assertEqual(InAppNotification.objects.count(), 2)

    def test_null_dedupe_keys_do_not_collide(self):
        notify(self.user, NotificationKind.SYSTEM, text="a")
        notify(self.user, NotificationKind.SYSTEM, text="b")
        self.assertEqual(InAppNotification.objects.count(), 2)

    def test_notify_on_commit_waits_for_commit(self):
        """TestCase 把用例包在事务里,提交回调不执行 —— 正好验证「提交后才写」。"""
        notify_on_commit(self.user.id, NotificationKind.POST_LIKE, actor_id=self.actor.id,
                         target_kind=NotificationTarget.POST, target_id=3, text="x")
        self.assertFalse(InAppNotification.objects.exists())

    def test_notify_on_commit_writes_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_on_commit(self.user.id, NotificationKind.MATCH, actor_id=self.actor.id,
                             target_kind=NotificationTarget.USER, target_id=self.actor.id,
                             text="你们互相喜欢了", dedupe_key="match:1:1")
        notification = InAppNotification.objects.get()
        self.assertEqual(notification.kind, NotificationKind.MATCH)
        self.assertEqual(notification.actor_id, self.actor.id)

    def test_notify_on_commit_skips_unknown_receiver(self):
        """接收者在提交前被注销:回调安静跳过,不抛异常。"""
        with self.captureOnCommitCallbacks(execute=True):
            notify_on_commit(999999, NotificationKind.SYSTEM, text="x")
        self.assertFalse(InAppNotification.objects.exists())


class NotificationsPruneCommandTests(TestCase):
    """清理命令:默认 dry-run;``--apply`` 只删超过保留期的行。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        self.old = InAppNotification.objects.create(
            user=self.user, kind=NotificationKind.SYSTEM, text="旧通知")
        self.fresh = InAppNotification.objects.create(
            user=self.user, kind=NotificationKind.SYSTEM, text="新通知")
        InAppNotification.objects.filter(pk=self.old.pk).update(
            created_at=timezone.now() - timedelta(days=91))

    def test_dry_run_keeps_everything(self):
        output = StringIO()
        call_command("notifications_prune", stdout=output)
        self.assertIn("dry-run", output.getvalue())
        self.assertEqual(InAppNotification.objects.count(), 2)

    def test_apply_deletes_only_expired(self):
        call_command("notifications_prune", "--apply")
        self.assertEqual(list(InAppNotification.objects.values_list("pk", flat=True)),
                         [self.fresh.pk])

    def test_custom_retention_days(self):
        call_command("notifications_prune", "--apply", "--days", "1000")
        self.assertEqual(InAppNotification.objects.count(), 2)
