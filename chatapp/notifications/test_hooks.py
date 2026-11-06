"""站内通知的事件接入(H-3)测试:四处 hook 只追加、不改既有调用。

覆盖场景:
    - 动态被赞:首次点赞写一条通知,自己赞自己不写,取消赞不写,重复点赞只留一条;
    - 顶级评论 / 回复评论:通知对象正确,IM 灰条调用次数不变,自己回复自己不写;
    - 配对成功:双方各一条,``actor`` / ``target`` 都指向对方;
    - 举报处理:一条 ``report_handled``,灰条仍发;
    - 偏好关闭后四类事件都不落库。
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from discovery.models import Match, Swipe, SwipeAction
from feed.models import Post, PostComment
from feed.services import notify_comment_created
from moderation.models import Report, ReportType
from moderation.services import notify_report_handled
from notifications.models import (InAppNotification, NotificationKind, NotificationPreference,
                                  NotificationTarget)
from users.models import Profile, ProfileStatus

User = get_user_model()


def make_user(phone: str, nickname: str, *, complete: bool = False) -> User:
    """造一个带资料的用户。

    Args:
        phone: 手机号(唯一)。
        nickname: 昵称。
        complete: 是否把资料标成「完善」(滑卡要求对方资料完善)。

    Returns:
        新建用户。
    """
    user = User.objects.create_user(phone=phone)
    Profile.objects.create(user=user, nickname=nickname,
                           status=ProfileStatus.COMPLETE if complete
                           else ProfileStatus.INCOMPLETE)
    return user


class PostLikeNotificationTests(APITestCase):
    """动态被赞。"""

    def setUp(self):
        self.author = make_user("13800138000", "作者")
        self.other = make_user("13900139000", "小明")
        self.post = Post.objects.create(author=self.author, text="今天天气不错")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.other).access_token}")

    def _like(self):
        """点赞(执行提交回调)。

        Returns:
            DRF 响应对象。
        """
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/api/v1/posts/{self.post.id}/like")

    def test_first_like_notifies_author(self):
        self._like()
        notification = InAppNotification.objects.get()
        self.assertEqual(notification.user_id, self.author.id)
        self.assertEqual(notification.kind, NotificationKind.POST_LIKE)
        self.assertEqual(notification.actor_id, self.other.id)
        self.assertEqual(notification.target_kind, NotificationTarget.POST)
        self.assertEqual(notification.target_id, self.post.id)
        self.assertEqual(notification.text, "小明 赞了你的动态")
        self.assertEqual(notification.dedupe_key, f"like:{self.post.id}:{self.other.id}")

    def test_repeat_like_does_not_duplicate(self):
        self._like()
        self.client.delete(f"/api/v1/posts/{self.post.id}/like")
        self._like()
        self.assertEqual(InAppNotification.objects.count(), 1)

    def test_unlike_creates_no_notification(self):
        self.client.post(f"/api/v1/posts/{self.post.id}/like")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f"/api/v1/posts/{self.post.id}/like")
        self.assertFalse(InAppNotification.objects.exists())

    def test_self_like_is_silent(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.author).access_token}")
        self._like()
        self.assertFalse(InAppNotification.objects.exists())

    def test_social_switch_off_blocks_notification(self):
        NotificationPreference.objects.create(user=self.author, social=False)
        self._like()
        self.assertFalse(InAppNotification.objects.exists())


class CommentNotificationTests(APITestCase):
    """顶级评论与回复评论(同时确认 IM 灰条次数不变)。"""

    def setUp(self):
        self.author = make_user("13800138000", "作者")
        self.commenter = make_user("13900139000", "小明")
        self.replier = make_user("13700137000", "小红")
        self.post = Post.objects.create(author=self.author, text="今天天气不错")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.commenter).access_token}")

    def _comment(self, text, parent_id=None):
        """发表评论或回复(执行提交回调)。

        Args:
            text: 正文。
            parent_id: 被回复的评论 id;``None`` 表示顶级评论。

        Returns:
            新评论的 id。
        """
        body = {"text": text}
        if parent_id is not None:
            body["parent_id"] = parent_id
        with patch("im.tasks.post_commented.delay") as commented, \
                patch("im.tasks.post_replied.delay") as replied:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/api/v1/posts/{self.post.id}/comments", body,
                                        format="json")
        self.assertEqual(resp.status_code, 201, resp.content[:200])
        self.commented = commented
        self.replied = replied
        return resp.data["id"]

    def test_top_comment_notifies_post_author(self):
        comment_id = self._comment("写得好")
        notification = InAppNotification.objects.get()
        self.assertEqual(notification.user_id, self.author.id)
        self.assertEqual(notification.kind, NotificationKind.POST_COMMENT)
        self.assertEqual(notification.actor_id, self.commenter.id)
        self.assertEqual(notification.target_kind, NotificationTarget.POST)
        self.assertEqual(notification.target_id, self.post.id)
        self.assertIn("小明 评论了你的动态", notification.text)
        self.assertEqual(notification.dedupe_key, f"comment:{comment_id}")
        self.commented.assert_called_once_with(comment_id)

    def test_self_comment_is_silent(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.author).access_token}")
        self._comment("自己夸自己")
        self.assertFalse(InAppNotification.objects.exists())
        self.commented.assert_not_called()

    def test_reply_notifies_replied_user(self):
        top_id = self._comment("写得好")
        InAppNotification.objects.all().delete()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.replier).access_token}")
        reply_id = self._comment("我也觉得", parent_id=top_id)
        notification = InAppNotification.objects.get()
        self.assertEqual(notification.user_id, self.commenter.id)
        self.assertEqual(notification.kind, NotificationKind.COMMENT_REPLY)
        self.assertEqual(notification.actor_id, self.replier.id)
        self.assertEqual(notification.target_id, self.post.id)
        self.assertEqual(notification.dedupe_key, f"reply:{reply_id}")
        self.replied.assert_called_once_with(reply_id)

    def test_reply_to_self_is_silent(self):
        top_id = self._comment("写得好")
        InAppNotification.objects.all().delete()
        self._comment("补一句", parent_id=top_id)
        self.assertFalse(InAppNotification.objects.exists())
        self.replied.assert_not_called()

    def test_social_switch_off_blocks_comment_notification(self):
        NotificationPreference.objects.create(user=self.author, social=False)
        self._comment("写得好")
        self.assertFalse(InAppNotification.objects.exists())
        self.commented.assert_called_once()


class MatchNotificationTests(APITestCase):
    """配对成功:双方各一条,actor / target 都指向对方。"""

    def setUp(self):
        self.me = make_user("13800138000", "我", complete=True)
        self.peer = make_user("13900139000", "对方", complete=True)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _mutual_like(self):
        """造「对方先喜欢我」,再由我点赞形成配对。"""
        Swipe.objects.create(swiper=self.peer, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay") as notice:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post("/api/v1/discovery/swipe",
                                        {"target_user_id": self.peer.id, "action": "like"},
                                        format="json")
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        self.assertEqual(resp.data["matched"], True)
        notice.assert_called_once_with(self.me.id, self.peer.id)

    def test_both_sides_get_one_notification(self):
        self._mutual_like()
        match = Match.objects.get()
        notifications = {item.user_id: item for item in InAppNotification.objects.all()}
        self.assertEqual(set(notifications), {self.me.id, self.peer.id})
        mine = notifications[self.me.id]
        self.assertEqual(mine.kind, NotificationKind.MATCH)
        self.assertEqual(mine.actor_id, self.peer.id)
        self.assertEqual(mine.target_kind, NotificationTarget.USER)
        self.assertEqual(mine.target_id, self.peer.id)
        self.assertEqual(mine.dedupe_key, f"match:{match.pk}:{self.me.id}")
        theirs = notifications[self.peer.id]
        self.assertEqual(theirs.actor_id, self.me.id)
        self.assertEqual(theirs.target_id, self.me.id)

    def test_match_switch_off_blocks_notification(self):
        NotificationPreference.objects.create(user=self.me, matches=False)
        self._mutual_like()
        self.assertEqual(list(InAppNotification.objects.values_list("user_id", flat=True)),
                         [self.peer.id])


class ReportHandledNotificationTests(TestCase):
    """举报处理:站内通知 + 灰条各一条;``system`` 关闭后不落库。"""

    def setUp(self):
        self.reporter = make_user("13800138000", "举报者")
        self.target = make_user("13900139000", "被举报者")
        self.report = Report.objects.create(reporter=self.reporter, target=self.target,
                                            type=ReportType.OTHER, detail="测试")

    def _handle(self):
        """调用一次「举报已处理」通知。"""
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                notify_report_handled(self.report)
        self.delay = delay

    def test_creates_notification_and_keeps_grey_bar(self):
        self._handle()
        notification = InAppNotification.objects.get()
        self.assertEqual(notification.user_id, self.reporter.id)
        self.assertEqual(notification.kind, NotificationKind.REPORT_HANDLED)
        self.assertEqual(notification.target_kind, NotificationTarget.NONE)
        self.assertIsNone(notification.target_id)
        self.assertEqual(notification.dedupe_key, f"report:{self.report.pk}")
        self.delay.assert_called_once_with(self.reporter.id)

    def test_repeated_call_keeps_one_notification(self):
        self._handle()
        self._handle()
        self.assertEqual(InAppNotification.objects.count(), 1)

    def test_system_switch_off_blocks_notification(self):
        NotificationPreference.objects.create(user=self.reporter, system=False)
        self._handle()
        self.assertFalse(InAppNotification.objects.exists())
        self.delay.assert_called_once()


class CommentNotificationWithoutProfileTests(TestCase):
    """没有资料的用户评论时,文案回落为 ``u{id}`` 而不是空字符串。"""

    def test_nickname_falls_back_to_account_id(self):
        author = User.objects.create_user(phone="13800138000")
        commenter = User.objects.create_user(phone="13900139000")
        post = Post.objects.create(author=author, text="无资料也能评论")
        comment = PostComment.objects.create(post=post, author=commenter, text="你好")
        with self.captureOnCommitCallbacks(execute=True):
            notify_comment_created(comment)
        notification = InAppNotification.objects.get()
        self.assertEqual(notification.text, f"u{commenter.id} 评论了你的动态:你好")
