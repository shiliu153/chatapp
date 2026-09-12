from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from moderation.models import ReportStatus, ReportType

from .models import Post, PostComment, PostLike, PostReport

User = get_user_model()


class FeedModelTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_post_defaults_and_ordering(self):
        post = Post.objects.create(author=self.a, text="你好")
        self.assertEqual(post.images.count(), 0)
        self.assertEqual(list(Post.objects.all()), [post])

    def test_post_like_unique_per_user(self):
        post = Post.objects.create(author=self.a, text="你好")
        PostLike.objects.create(post=post, user=self.b)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PostLike.objects.create(post=post, user=self.b)

    def test_comment_ordering_oldest_first(self):
        post = Post.objects.create(author=self.a, text="你好")
        first = PostComment.objects.create(post=post, author=self.a, text="一")
        second = PostComment.objects.create(post=post, author=self.b, text="二")
        self.assertEqual(list(post.comments.all()), [first, second])

    def test_post_report_defaults_to_pending(self):
        post = Post.objects.create(author=self.a, text="你好")
        report = PostReport.objects.create(reporter=self.b, post=post,
                                           type=ReportType.PORN, detail="色情")
        self.assertEqual(report.status, ReportStatus.PENDING)

    def test_deleting_post_keeps_report_with_null_post(self):
        # 动态删除后举报行留档(SET_NULL),供运营对账
        post = Post.objects.create(author=self.a, text="你好")
        report = PostReport.objects.create(reporter=self.b, post=post,
                                           type=ReportType.OTHER)
        post.delete()
        report.refresh_from_db()
        self.assertIsNone(report.post)
