"""广场应用的测试:模型约束、发布、可见性、删除、点赞、评论与举报。

覆盖场景:
    - 模型:动态默认值与排序、点赞唯一、评论按时间正序、举报默认待处理、
      动态删除后举报行保留(``post`` 置空);
    - 发布:纯文字、配图保序、空内容拒绝、违禁词、图片数量与大小上限、鉴权、限流;
    - 可见性:最新在前、分页、双向拉黑都不可见、重封禁作者隐藏而轻封禁仍可见、
      赞/评数与「我是否已赞」、详情 404 分支、``mine`` 只列自己;
    - 删除:作者可删(含图片文件与子行)、非作者 404、删除时关闭待处理举报并通知;
    - 点赞与取消点赞都幂等、不可见动态 404;
    - 评论:通知作者、自己评自己不通知、违禁词、正序分页、隐藏被拉黑评论者、限流;
    - 举报动态:建待处理、重复幂等、不能举报自己、不可见 404、非法类型、限流。
"""

import base64
import os
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
        """清空限流计数(计数在 Redis,跨用例残留会误报 429)。"""
        cache.clear()   # 限流计数在 Redis,跨用例残留会误报 429
        self.addCleanup(cache.clear)

    def login(self, user):
        """给测试客户端装上指定用户的令牌。

        Args:
            user: 目标用户。
        """
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def use_temp_media(self):
        """把 ``MEDIA_ROOT`` 临时指向新建目录,避免测试图片落进真实 media/。"""
        media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=media_dir)   # 测试图片必须写入临时目录,不能落到真实 media/
        override.enable()
        self.addCleanup(override.disable)

    def image(self, name="a.png"):
        """造一个 1x1 的 PNG 上传对象。

        Args:
            name: 文件名。

        Returns:
            可直接塞进 multipart 的上传文件。
        """
        return SimpleUploadedFile(name, PNG_1PX, content_type="image/png")


class FeedModelTests(TestCase):
    """广场模型:默认值、排序与各类唯一约束。"""

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

    def test_top_level_comment_has_no_parent(self):
        post = Post.objects.create(author=self.a, text="你好")
        comment = PostComment.objects.create(post=post, author=self.a, text="一")
        self.assertIsNone(comment.parent)
        self.assertIsNone(comment.reply_to)
        self.assertEqual(comment.replies.count(), 0)

    def test_reply_defaults(self):
        post = Post.objects.create(author=self.a, text="你好")
        root = PostComment.objects.create(post=post, author=self.a, text="楼")
        reply = PostComment.objects.create(post=post, author=self.b, text="回",
                                           parent=root, reply_to=self.a)
        self.assertEqual(reply.parent, root)
        self.assertEqual(reply.reply_to, self.a)
        self.assertEqual(list(root.replies.all()), [reply])

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
    """发布动态:纯文字、配图保序、空内容与各类越界输入、鉴权与限流。"""

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
    """广场列表与详情:排序、分页、可见性规则与互动计数。"""

    def setUp(self):
        self.use_temp_media()
        self.me = self._make_user("13800138000", "我")
        self.other = self._make_user("13900139000", "小红")
        self.login(self.me)

    def _make_user(self, phone, nickname):
        """造一个资料完善的用户。

        Args:
            phone: 手机号。
            nickname: 昵称。

        Returns:
            新建的用户实例。
        """
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


class PostDeleteTests(FeedApiMixin, APITestCase):
    """删除动态:作者可删(连带图片文件与子行)、非作者 404、同时关闭待处理举报。"""

    def setUp(self):
        self.use_temp_media()
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13900139000")
        self.login(self.me)

    def test_author_can_delete_with_files_and_children(self):
        post = Post.objects.create(author=self.me, text="删除我")
        PostImage.objects.create(post=post, file=self.image())
        PostLike.objects.create(post=post, user=self.other)
        PostComment.objects.create(post=post, author=self.other, text="评论")
        path = post.images.get().file.path
        resp = self.client.delete(f"/api/v1/posts/{post.id}")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Post.objects.filter(pk=post.id).exists())
        self.assertEqual(PostLike.objects.count(), 0)
        self.assertEqual(PostComment.objects.count(), 0)
        self.assertFalse(os.path.exists(path))   # 磁盘文件也删了

    def test_non_author_gets_404(self):
        post = Post.objects.create(author=self.other, text="别人的")
        self.assertEqual(self.client.delete(f"/api/v1/posts/{post.id}").status_code, 404)
        self.assertTrue(Post.objects.filter(pk=post.id).exists())

    def test_delete_closes_pending_reports_and_notifies(self):
        post = Post.objects.create(author=self.me, text="被举报")
        report = PostReport.objects.create(reporter=self.other, post=post,
                                           type=ReportType.PORN)
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.delete(f"/api/v1/posts/{post.id}")
        self.assertEqual(resp.status_code, 204)
        report.refresh_from_db()
        self.assertEqual(report.status, ReportStatus.HANDLED)
        self.assertEqual(report.handled_note, "动态已删除")
        self.assertIsNotNone(report.handled_at)
        delay.assert_called_once_with(self.other.id)


class PostLikeTests(FeedApiMixin, APITestCase):
    """点赞:点赞与取消点赞都幂等,不可见动态一律 404。"""

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13900139000")
        self.post = Post.objects.create(author=self.other, text="点赞我")
        self.login(self.me)

    def test_like_is_idempotent(self):
        first = self.client.post(f"/api/v1/posts/{self.post.id}/like")
        second = self.client.post(f"/api/v1/posts/{self.post.id}/like")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PostLike.objects.count(), 1)

    def test_unlike_is_idempotent(self):
        PostLike.objects.create(post=self.post, user=self.me)
        self.assertEqual(self.client.delete(f"/api/v1/posts/{self.post.id}/like").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/v1/posts/{self.post.id}/like").status_code, 204)
        self.assertEqual(PostLike.objects.count(), 0)

    def test_like_invisible_post_404(self):
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.post(f"/api/v1/posts/{self.post.id}/like").status_code, 404)


class PostCommentTests(FeedApiMixin, APITestCase):
    """评论:通知作者、自己评自己不通知、违禁词、正序分页、隐藏被拉黑评论者、限流。"""

    def setUp(self):
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我")
        self.author = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.author, nickname="小红")
        self.post = Post.objects.create(author=self.author, text="评论我")
        self.login(self.me)

    def test_create_comment_notifies_author(self):
        with patch("im.tasks.post_commented.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/api/v1/posts/{self.post.id}/comments",
                                        {"text": "好漂亮"}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["text"], "好漂亮")
        self.assertEqual(resp.json()["author"]["nickname"], "我")
        comment = PostComment.objects.get()
        delay.assert_called_once_with(comment.id)

    def test_blocked_word_rejected(self):
        resp = self.client.post(f"/api/v1/posts/{self.post.id}/comments",
                                {"text": "代开发票"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "评论包含违规内容,请修改")

    def test_self_comment_does_not_notify(self):
        self.login(self.author)
        with patch("im.tasks.post_commented.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/api/v1/posts/{self.post.id}/comments",
                                        {"text": "自评"}, format="json")
        self.assertEqual(resp.status_code, 201)
        delay.assert_not_called()

    def test_list_is_oldest_first_and_paginated(self):
        for i in range(3):
            PostComment.objects.create(post=self.post, author=self.me, text=f"c{i}")
        data = self.client.get(f"/api/v1/posts/{self.post.id}/comments").json()
        self.assertEqual([c["text"] for c in data["results"]], ["c0", "c1", "c2"])
        self.assertEqual(data["count"], 3)

    def test_list_hides_blocked_commenters(self):
        PostComment.objects.create(post=self.post, author=self.me, text="可见")
        blocked = User.objects.create_user(phone="13700137000")
        Profile.objects.create(user=blocked, nickname="拉黑")
        PostComment.objects.create(post=self.post, author=blocked, text="不可见")
        Block.objects.create(blocker=self.me, blocked=blocked)
        data = self.client.get(f"/api/v1/posts/{self.post.id}/comments").json()
        self.assertEqual([c["text"] for c in data["results"]], ["可见"])

    def test_comment_throttled(self):
        from .throttles import PostCommentThrottle

        with patch.object(PostCommentThrottle, "rate", "2/day", create=True):
            self.assertEqual(self.client.post(f"/api/v1/posts/{self.post.id}/comments",
                                              {"text": "1"}, format="json").status_code, 201)
            self.assertEqual(self.client.post(f"/api/v1/posts/{self.post.id}/comments",
                                              {"text": "2"}, format="json").status_code, 201)
            self.assertEqual(self.client.post(f"/api/v1/posts/{self.post.id}/comments",
                                              {"text": "3"}, format="json").status_code, 429)


class PostReportTests(FeedApiMixin, APITestCase):
    """举报动态:建待处理、重复幂等、不能举报自己、不可见 404、非法类型与限流。"""

    def setUp(self):
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        self.author = User.objects.create_user(phone="13900139000")
        self.post = Post.objects.create(author=self.author, text="被举报的动态")
        self.login(self.me)
        self.url = f"/api/v1/posts/{self.post.id}/report"

    def test_creates_pending_report(self):
        resp = self.client.post(self.url, {"type": "porn", "detail": "色情图"}, format="json")
        self.assertEqual(resp.status_code, 201)
        report = PostReport.objects.get()
        self.assertEqual((report.reporter, report.post, report.type),
                         (self.me, self.post, "porn"))
        self.assertEqual(report.status, ReportStatus.PENDING)

    def test_duplicate_pending_is_idempotent(self):
        first = self.client.post(self.url, {"type": "porn"}, format="json")
        second = self.client.post(self.url, {"type": "fraud"}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(PostReport.objects.count(), 1)

    def test_cannot_report_own_post(self):
        self.login(self.author)
        self.assertEqual(
            self.client.post(self.url, {"type": "other"}, format="json").status_code, 400)

    def test_invisible_post_404(self):
        Block.objects.create(blocker=self.author, blocked=self.me)
        self.assertEqual(
            self.client.post(self.url, {"type": "other"}, format="json").status_code, 404)

    def test_invalid_type_rejected(self):
        self.assertEqual(
            self.client.post(self.url, {"type": "spam"}, format="json").status_code, 400)

    def test_throttled(self):
        from .throttles import PostReportThrottle

        other = Post.objects.create(author=self.author, text="第二条")
        with patch.object(PostReportThrottle, "rate", "1/day", create=True):
            self.assertEqual(self.client.post(self.url, {"type": "other"},
                                              format="json").status_code, 201)
            self.assertEqual(self.client.post(f"/api/v1/posts/{other.id}/report",
                                              {"type": "other"}, format="json").status_code, 429)


class PostCommentThreadTests(FeedApiMixin, APITestCase):
    """楼中楼:归一化、内嵌回复、展开接口、删除与提醒分流。"""

    def setUp(self):
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我")
        self.author = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.author, nickname="楼主")
        self.third = User.objects.create_user(phone="13700137000")
        Profile.objects.create(user=self.third, nickname="路人")
        self.post = Post.objects.create(author=self.author, text="楼中楼")
        self.login(self.me)
        self.url = f"/api/v1/posts/{self.post.id}/comments"

    def _comment(self, text, author=None, parent=None):
        """直接落一条评论/回复,跳过接口(构造场景用)。

        Args:
            text: 正文。
            author: 作者,默认 ``self.me``。
            parent: 父评论,``None`` 表示顶级评论。

        Returns:
            新建的评论实例。
        """
        return PostComment.objects.create(
            post=self.post, author=author or self.me, text=text, parent=parent,
            reply_to=parent.author if parent is not None else None)

    def test_reply_to_top_level_sets_parent_and_reply_to(self):
        root = self._comment("一楼", author=self.author)
        resp = self.client.post(self.url, {"text": "回复一楼", "parent_id": root.id},
                                format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["parent_id"], root.id)
        created = PostComment.objects.get(id=resp.json()["id"])
        self.assertEqual(created.parent_id, root.id)
        self.assertEqual(created.reply_to_id, self.author.id)

    def test_reply_to_reply_is_normalized_to_root(self):
        root = self._comment("一楼", author=self.author)
        reply = self._comment("二楼", author=self.third, parent=root)
        resp = self.client.post(self.url, {"text": "回复二楼", "parent_id": reply.id},
                                format="json")
        self.assertEqual(resp.status_code, 201)
        created = PostComment.objects.get(id=resp.json()["id"])
        self.assertEqual(created.parent_id, root.id)          # 归一到顶级评论
        self.assertEqual(created.reply_to_id, self.third.id)  # 提醒被回复者
        self.assertEqual(root.replies.count(), 2)

    def test_parent_from_another_post_404(self):
        other_post = Post.objects.create(author=self.author, text="别的")
        foreign = PostComment.objects.create(post=other_post, author=self.author, text="外")
        resp = self.client.post(self.url, {"text": "x", "parent_id": foreign.id},
                                format="json")
        self.assertEqual(resp.status_code, 404)

    def test_missing_parent_404(self):
        resp = self.client.post(self.url, {"text": "x", "parent_id": 999999}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_list_only_top_level_with_two_embedded_replies(self):
        root = self._comment("一楼", author=self.author)
        for i in range(3):
            self._comment(f"回复{i}", author=self.third, parent=root)
        data = self.client.get(self.url).json()
        self.assertEqual(data["count"], 1)                 # 只分页顶级评论
        item = data["results"][0]
        self.assertEqual(item["id"], root.id)
        self.assertEqual(item["reply_count"], 3)
        self.assertEqual([r["text"] for r in item["replies"]], ["回复0", "回复1"])
        self.assertEqual(item["replies"][0]["reply_to"]["nickname"], "楼主")
        self.assertEqual(item["replies"][0]["parent_id"], root.id)

    def test_reply_count_skips_hidden_replies(self):
        root = self._comment("一楼", author=self.author)
        self._comment("可见", author=self.third, parent=root)
        Block.objects.create(blocker=self.me, blocked=self.third)
        self._comment("被拉黑", author=self.third, parent=root)
        item = self.client.get(self.url).json()["results"][0]
        self.assertEqual(item["reply_count"], 0)
        self.assertEqual(item["replies"], [])

    def test_comment_count_includes_replies(self):
        root = self._comment("一楼", author=self.author)
        self._comment("回复", author=self.third, parent=root)
        post = self.client.get(f"/api/v1/posts/{self.post.id}").json()
        self.assertEqual(post["comment_count"], 2)

    def test_create_response_includes_reply_meta(self):
        root = self._comment("一楼", author=self.author)
        resp = self.client.post(self.url, {"text": "回复", "parent_id": root.id},
                                format="json")
        data = resp.json()
        self.assertEqual(data["reply_to"]["user_id"], self.author.id)
        self.assertEqual(data["reply_to"]["nickname"], "楼主")
        self.assertEqual(data["reply_count"], 0)
        self.assertEqual(data["replies"], [])
