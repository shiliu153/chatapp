import base64
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from moderation.models import Block, ReportStatus, ReportType
from users.models import Profile, ProfileStatus

from .models import Post, PostComment, PostImage, PostLike, PostReport

User = get_user_model()

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FeedApiMixin:
    """接口用例公共设施:JWT 登录、临时 MEDIA_ROOT、造图、限流缓存清理。"""

    def clear_throttle_cache(self):
        cache.clear()   # 限流计数在 Redis,跨用例残留会误报 429
        self.addCleanup(cache.clear)

    def login(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def use_temp_media(self):
        media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=media_dir)   # 别把测试图片写进真 media/
        override.enable()
        self.addCleanup(override.disable)

    def image(self, name="a.png"):
        return SimpleUploadedFile(name, PNG_1PX, content_type="image/png")


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


class PostCreateTests(FeedApiMixin, APITestCase):
    URL = "/api/v1/posts"

    def setUp(self):
        self.clear_throttle_cache()
        self.use_temp_media()
        self.me = User.objects.create_user(phone="13800138000")
        self.login(self.me)

    def test_create_text_post(self):
        resp = self.client.post(self.URL, {"text": "今天天气真好"}, format="multipart")
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["text"], "今天天气真好")
        self.assertEqual(data["images"], [])
        self.assertEqual(data["like_count"], 0)
        self.assertFalse(data["liked_by_me"])
        self.assertEqual(data["author"]["user_id"], self.me.id)
        post = Post.objects.get()
        self.assertEqual(post.author, self.me)

    def test_create_with_images_keeps_order(self):
        resp = self.client.post(
            self.URL, {"text": "看图", "images": [self.image("a.png"), self.image("b.png")]},
            format="multipart")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.json()["images"]), 2)
        self.assertEqual(PostImage.objects.count(), 2)
        self.assertEqual(list(PostImage.objects.values_list("order", flat=True)), [0, 1])

    def test_empty_post_rejected(self):
        resp = self.client.post(self.URL, {"text": ""}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "写点文字或选张图片吧")

    def test_blocked_word_rejected(self):
        resp = self.client.post(self.URL, {"text": "专业代开发票"}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "内容包含违规内容,请修改")

    def test_too_many_images_rejected(self):
        images = [self.image(f"{i}.png") for i in range(10)]
        resp = self.client.post(self.URL, {"text": "x", "images": images}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "最多 9 张图片")

    def test_oversized_image_rejected(self):
        big = SimpleUploadedFile("big.png", b"x" * (5 * 1024 * 1024 + 1),
                                 content_type="image/png")
        resp = self.client.post(self.URL, {"text": "x", "images": [big]}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "单张图片不能超过 5MB")

    def test_requires_auth(self):
        self.client.credentials()
        resp = self.client.post(self.URL, {"text": "x"}, format="multipart")
        self.assertEqual(resp.status_code, 401)

    def test_throttled(self):
        from .throttles import PostCreateThrottle

        with patch.object(PostCreateThrottle, "rate", "2/day", create=True):
            self.assertEqual(self.client.post(self.URL, {"text": "1"},
                                              format="multipart").status_code, 201)
            self.assertEqual(self.client.post(self.URL, {"text": "2"},
                                              format="multipart").status_code, 201)
            self.assertEqual(self.client.post(self.URL, {"text": "3"},
                                              format="multipart").status_code, 429)


class FeedFlowTests(FeedApiMixin, APITestCase):
    def setUp(self):
        self.use_temp_media()
        self.me = self._make_user("13800138000", "我")
        self.other = self._make_user("13900139000", "小红")
        self.login(self.me)

    def _make_user(self, phone, nickname):
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=nickname, status=ProfileStatus.COMPLETE)
        return user

    def test_flow_orders_newest_first(self):
        old = Post.objects.create(author=self.other, text="旧")
        new = Post.objects.create(author=self.other, text="新")
        data = self.client.get("/api/v1/posts").json()
        self.assertEqual([item["id"] for item in data["results"]], [new.id, old.id])
        self.assertEqual(data["results"][0]["author"]["nickname"], "小红")

    def test_flow_paginates(self):
        for i in range(25):
            Post.objects.create(author=self.other, text=f"p{i}")
        data = self.client.get("/api/v1/posts").json()
        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 20)
        self.assertIsNotNone(data["next"])

    def test_flow_excludes_blocked_both_ways(self):
        Block.objects.create(blocker=self.me, blocked=self.other)
        Post.objects.create(author=self.other, text="看不到")
        self.assertEqual(self.client.get("/api/v1/posts").json()["results"], [])
        Block.objects.all().delete()
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get("/api/v1/posts").json()["results"], [])

    def test_flow_hides_heavy_banned_author(self):
        Post.objects.create(author=self.other, text="封号内容")
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self.client.get("/api/v1/posts").json()["results"], [])

    def test_light_banned_still_visible(self):
        Post.objects.create(author=self.other, text="轻封可见")
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_LIGHT)
        self.assertEqual(len(self.client.get("/api/v1/posts").json()["results"]), 1)

    def test_like_and_comment_counts_and_liked_by_me(self):
        post = Post.objects.create(author=self.other, text="计数")
        PostLike.objects.create(post=post, user=self.me)
        PostComment.objects.create(post=post, author=self.other, text="评论")
        item = self.client.get("/api/v1/posts").json()["results"][0]
        self.assertEqual(item["like_count"], 1)
        self.assertEqual(item["comment_count"], 1)
        self.assertTrue(item["liked_by_me"])

    def test_detail_visible_returns_post(self):
        post = Post.objects.create(author=self.other, text="看详情")
        resp = self.client.get(f"/api/v1/posts/{post.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["text"], "看详情")

    def test_detail_invisible_returns_404(self):
        post = Post.objects.create(author=self.other, text="拉黑后不可见")
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get(f"/api/v1/posts/{post.id}").status_code, 404)

    def test_detail_heavy_banned_author_returns_404(self):
        post = Post.objects.create(author=self.other, text="重封")
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self.client.get(f"/api/v1/posts/{post.id}").status_code, 404)

    def test_mine_only_shows_own(self):
        mine = Post.objects.create(author=self.me, text="我的")
        Post.objects.create(author=self.other, text="别人的")
        data = self.client.get("/api/v1/posts/mine").json()
        self.assertEqual([item["id"] for item in data["results"]], [mine.id])
