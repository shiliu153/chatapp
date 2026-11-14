"""广场应用的测试:模型约束、发布、可见性、删除、点赞、收藏、评论、举报与关注。

覆盖场景:
    - 模型:动态默认值与排序、点赞唯一、收藏唯一、评论按时间正序、举报默认待处理、
      动态删除后举报行保留(``post`` 置空)、关注关系有向且成对唯一;
    - 发布:纯文字、配图保序、空内容拒绝、违禁词、图片数量与大小上限、鉴权、限流;
    - 可见性:最新在前、分页、双向拉黑都不可见、重封禁作者隐藏而轻封禁仍可见、
      赞/评数与「我是否已赞」「我是否已收藏」、详情 404 分支、``mine`` 只列自己;
    - 删除:作者可删(含图片文件与子行)、非作者 404、删除时关闭待处理举报并通知;
    - 点赞与取消点赞都幂等、不可见动态 404;
    - 点赞列表:按点赞时间倒序、拉黑与重封禁过滤、``count`` 是可见人数、空列表不 404;
    - 收藏:POST/DELETE 都恒 204 且幂等、不发通知、不可见 404、可收藏自己的动态;
    - 我的收藏:按**收藏时间**倒序(与发帖时间相反)、帖子删除/作者拉黑后消失、游标翻页;
    - 评论:通知作者、自己评自己不通知、违禁词、正序分页、隐藏被拉黑评论者、限流;
    - 举报动态:建待处理、重复幂等、不能举报自己、不可见 404、非法类型、限流;
    - 关注:幂等 204、不能关注自己、拉黑/重封禁/不存在一律 404、鉴权与限流;
    - 关注流:只含关注的人、不含自己、拉黑与重封禁作者过滤、游标翻页不重复、限流。

文件信息:
    文件名称          feed/tests.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import base64
import io
import os
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from moderation.models import Block, ReportStatus, ReportType
from notifications.models import InAppNotification
from users.models import Profile, ProfileStatus

from .models import (Follow, Post, PostComment, PostFavorite, PostImage, PostLike,
                     PostReport)
from .throttles import (CommentRepliesThrottle, FavoritesReadThrottle,
                        FollowingReadThrottle, PostFavoriteThrottle,
                        PostLikesReadThrottle)

User = get_user_model()

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FeedApiMixin:
    """接口用例公共设施:JWT 登录、临时 MEDIA_ROOT、造图、限流缓存清理。"""

    def clear_throttle_cache(self):
        """清空限流计数,并把清理动作挂到用例结束。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.clear_throttle_cache()``

        备注信息:
            计数落在 Redis,跨用例残留会让后续请求误报 429;``addCleanup`` 保证用例失败时也再清一次。
        """
        cache.clear()   # 限流计数在 Redis,跨用例残留会误报 429
        self.addCleanup(cache.clear)

    def login(self, user):
        """给测试客户端装上指定用户的 JWT 令牌。

        参数说明:
            user: 目标用户。

        返回参数:
            无返回值。

        使用示例:
            ``self.login(self.me)``

        备注信息:
            令牌用 ``RefreshToken.for_user(user).access_token`` 现签,直接写进 ``HTTP_AUTHORIZATION``。
        """
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def use_temp_media(self):
        """把 ``MEDIA_ROOT`` 临时指向新建目录,避免测试图片落进真实 media/。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.use_temp_media()``

        备注信息:
            目录由 ``tempfile.mkdtemp`` 现建;``addCleanup`` 负责恢复原设置并递归删除临时目录。
        """
        media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=media_dir)   # 测试图片必须写入临时目录,不能落到真实 media/
        override.enable()
        self.addCleanup(override.disable)

    def image(self, name="a.png"):
        """造一个 1x1 的 PNG 上传对象。

        参数说明:
            name: 文件名,默认 ``a.png``。

        返回参数:
            可直接塞进 multipart 的上传文件。

        使用示例:
            ``self.image("b.png")``

        备注信息:
            内容取自模块级 ``PNG_1PX``,不落盘;真实写盘由被测接口完成。
        """
        return SimpleUploadedFile(name, PNG_1PX, content_type="image/png")


class FeedModelTests(TestCase):
    """广场模型:默认值、排序与各类唯一约束。"""

    def setUp(self):
        """为每个用例造两个普通账号。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            只建 ``User`` 不建 ``Profile``;本类只验模型约束,不涉及资料状态过滤。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_post_defaults_and_ordering(self):
        """新建动态没有配图,``Post.objects.all()`` 只返回这一条。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.a, text="你好")
        self.assertEqual(post.images.count(), 0)
        self.assertEqual(list(Post.objects.all()), [post])

    def test_post_like_unique_per_user(self):
        """同一用户重复点赞同一动态,库层抛 ``IntegrityError``。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.a, text="你好")
        PostLike.objects.create(post=post, user=self.b)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PostLike.objects.create(post=post, user=self.b)

    def test_post_favorite_unique_per_user(self):
        """收藏在库层唯一:重复收藏只能落一行(接口的恒 204 幂等靠它兜底)。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.a, text="你好")
        PostFavorite.objects.create(post=post, user=self.b)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PostFavorite.objects.create(post=post, user=self.b)

    def test_deleting_post_deletes_favorites(self):
        """动态删除时收藏行随 CASCADE 消失(「我的收藏」不需要额外清理逻辑)。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.a, text="你好")
        PostFavorite.objects.create(post=post, user=self.b)
        post.delete()
        self.assertEqual(PostFavorite.objects.count(), 0)

    def test_comment_ordering_oldest_first(self):
        """评论列表按创建时间正序,先发的排在前面。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.a, text="你好")
        first = PostComment.objects.create(post=post, author=self.a, text="一")
        second = PostComment.objects.create(post=post, author=self.b, text="二")
        self.assertEqual(list(post.comments.all()), [first, second])

    def test_top_level_comment_has_no_parent(self):
        """顶级评论的 ``parent`` 与 ``reply_to`` 为空,也没有子回复。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.a, text="你好")
        comment = PostComment.objects.create(post=post, author=self.a, text="一")
        self.assertIsNone(comment.parent)
        self.assertIsNone(comment.reply_to)
        self.assertEqual(comment.replies.count(), 0)

    def test_reply_defaults(self):
        """回复行记下父评论与被回复人,父评论的 ``replies`` 反向能取到它。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.a, text="你好")
        root = PostComment.objects.create(post=post, author=self.a, text="楼")
        reply = PostComment.objects.create(post=post, author=self.b, text="回",
                                           parent=root, reply_to=self.a)
        self.assertEqual(reply.parent, root)
        self.assertEqual(reply.reply_to, self.a)
        self.assertEqual(list(root.replies.all()), [reply])

    def test_post_report_defaults_to_pending(self):
        """新建举报默认落在待处理状态。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.a, text="你好")
        report = PostReport.objects.create(reporter=self.b, post=post,
                                           type=ReportType.PORN, detail="色情")
        self.assertEqual(report.status, ReportStatus.PENDING)

    def test_deleting_post_keeps_report_with_null_post(self):
        # 动态删除后举报行留档(SET_NULL),供运营对账
        """动态删除后举报行留档(SET_NULL),``post`` 置空供运营对账。

        参数说明:
            无。
        """
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
        """清限流、切临时 MEDIA_ROOT、造登录用户。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            ``clear_throttle_cache`` 必须在发请求前调用,否则上一用例的计数会让本类直接 429。
        """
        self.clear_throttle_cache()
        self.use_temp_media()
        self.me = User.objects.create_user(phone="13800138000")
        self.login(self.me)

    def test_create_text_post(self):
        """纯文字发布成功:201,回显文字、空配图、零计数,作者是自己。

        参数说明:
            无。
        """
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
        """多图发布成功,``PostImage.order`` 按提交顺序从 0 递增。

        参数说明:
            无。
        """
        resp = self.client.post(
            self.URL, {"text": "看图", "images": [self.image("a.png"), self.image("b.png")]},
            format="multipart")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.json()["images"]), 2)
        self.assertEqual(PostImage.objects.count(), 2)
        self.assertEqual(list(PostImage.objects.values_list("order", flat=True)), [0, 1])

    def test_post_image_records_bytes(self):
        """配图落库时记下重编码字节数,供存储配额统计(M7)。

        参数说明:
            无。
        """
        self.client.post(self.URL, {"text": "看图", "images": [self.image()]},
                         format="multipart")
        image = PostImage.objects.get()
        self.assertEqual(image.bytes, image.file.size)

    def test_quota_exceeded_rejects_post_without_creating_it(self):
        """配额不足时返回 413/41301,动态与配图都不落库(M7)。

        参数说明:
            无。
        """
        with self.settings(USER_STORAGE_QUOTA_BYTES=1):
            resp = self.client.post(
                self.URL, {"text": "看图", "images": [self.image()]}, format="multipart")
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["code"], 41301)
        self.assertEqual(Post.objects.count(), 0)
        self.assertEqual(PostImage.objects.count(), 0)

    def test_text_only_post_unaffected_by_quota(self):
        """纯文字动态不占媒体配额(``USER_STORAGE_QUOTA_BYTES=0`` 时也能发)。

        参数说明:
            无。
        """
        with self.settings(USER_STORAGE_QUOTA_BYTES=0):
            resp = self.client.post(self.URL, {"text": "只发文字"}, format="multipart")
        self.assertEqual(resp.status_code, 201)

    def test_create_rejects_gif(self):
        """广场图同样只接受 jpg/png/webp(L5)。

        参数说明:
            无。
        """
        buffer = io.BytesIO()
        Image.new("RGB", (1, 1), "red").save(buffer, "GIF")
        gif = SimpleUploadedFile("a.gif", buffer.getvalue(), content_type="image/gif")
        resp = self.client.post(self.URL, {"text": "x", "images": [gif]}, format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_create_strips_exif(self):
        """广场图重编码后不保留原始 EXIF(M4)。

        参数说明:
            无。
        """
        exif = Image.Exif()
        exif[0x010F] = "TestCamera"
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(buffer, "JPEG", exif=exif)
        photo = SimpleUploadedFile("a.jpg", buffer.getvalue(), content_type="image/jpeg")
        resp = self.client.post(self.URL, {"text": "x", "images": [photo]}, format="multipart")
        self.assertEqual(resp.status_code, 201, resp.json())
        with Image.open(PostImage.objects.get().file.path) as stored:
            self.assertNotIn(0x010F, stored.getexif())

    def test_empty_post_rejected(self):
        """空文字且无配图给 400 与固定提示语。

        参数说明:
            无。
        """
        resp = self.client.post(self.URL, {"text": ""}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "写点文字或选张图片吧")

    def test_blocked_word_rejected(self):
        """正文命中违禁词给 400 与固定提示语。

        参数说明:
            无。
        """
        resp = self.client.post(self.URL, {"text": "专业代开发票"}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "内容包含违规内容,请修改")

    def test_too_many_images_rejected(self):
        """超过 9 张图给 400 与「最多 9 张图片」。

        参数说明:
            无。
        """
        images = [self.image(f"{i}.png") for i in range(10)]
        resp = self.client.post(self.URL, {"text": "x", "images": images}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "最多 9 张图片")

    def test_oversized_image_rejected(self):
        """单张超过 5MB 给 400 与大小提示语。

        参数说明:
            无。
        """
        big = SimpleUploadedFile("big.png", b"x" * (5 * 1024 * 1024 + 1),
                                 content_type="image/png")
        resp = self.client.post(self.URL, {"text": "x", "images": [big]}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "单张图片不能超过 5MB")

    def test_requires_auth(self):
        """不带令牌发布给 401。

        参数说明:
            无。
        """
        self.client.credentials()
        resp = self.client.post(self.URL, {"text": "x"}, format="multipart")
        self.assertEqual(resp.status_code, 401)

    def test_throttled(self):
        """把发布限流临时改成 2/day:前两次 201,第三次 429。

        参数说明:
            无。
        """
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
        """切临时 MEDIA_ROOT,造两个资料完善的用户并以「我」登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            昵称参与断言(``小红``),改名要同改用例。
        """
        self.use_temp_media()
        self.me = self._make_user("13800138000", "我")
        self.other = self._make_user("13900139000", "小红")
        self.login(self.me)

    def _make_user(self, phone, nickname):
        """造一个资料完善的用户。

        参数说明:
            phone: 手机号。
            nickname: 昵称。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make_user("13800138000", "我")``

        备注信息:
            资料状态固定 ``COMPLETE``;可见性过滤只放行资料完善的作者。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=nickname, status=ProfileStatus.COMPLETE)
        return user

    def test_flow_orders_newest_first(self):
        """广场按发帖时间倒序,并带出作者昵称。

        参数说明:
            无。
        """
        old = Post.objects.create(author=self.other, text="旧")
        new = Post.objects.create(author=self.other, text="新")
        data = self.client.get("/api/v1/posts").json()
        self.assertEqual([item["id"] for item in data["results"]], [new.id, old.id])
        self.assertEqual(data["results"][0]["author"]["nickname"], "小红")

    def test_flow_paginates(self):
        """25 条动态首屏取 20 条,``count`` 是全量 25,``has_more`` 为真并给游标。

        参数说明:
            无。
        """
        for i in range(25):
            Post.objects.create(author=self.other, text=f"p{i}")
        data = self.client.get("/api/v1/posts").json()
        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 20)
        self.assertTrue(data["has_more"])
        self.assertIsNotNone(data["next_cursor"])

    def test_flow_excludes_blocked_both_ways(self):
        """我拉黑对方、对方拉黑我,两个方向都看不到对方动态。

        参数说明:
            无。
        """
        Block.objects.create(blocker=self.me, blocked=self.other)
        Post.objects.create(author=self.other, text="看不到")
        self.assertEqual(self.client.get("/api/v1/posts").json()["results"], [])
        Block.objects.all().delete()
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get("/api/v1/posts").json()["results"], [])

    def test_flow_hides_heavy_banned_author(self):
        """作者重封禁后动态从广场消失。

        参数说明:
            无。
        """
        Post.objects.create(author=self.other, text="封号内容")
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self.client.get("/api/v1/posts").json()["results"], [])

    def test_light_banned_still_visible(self):
        """轻封禁只禁滑卡,作者动态在广场照常可见。

        参数说明:
            无。
        """
        Post.objects.create(author=self.other, text="轻封可见")
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_LIGHT)
        self.assertEqual(len(self.client.get("/api/v1/posts").json()["results"]), 1)

    def test_like_and_comment_counts_and_liked_by_me(self):
        """列表行带出赞数、评论数与「我是否已赞」。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.other, text="计数")
        PostLike.objects.create(post=post, user=self.me)
        PostComment.objects.create(post=post, author=self.other, text="评论")
        item = self.client.get("/api/v1/posts").json()["results"][0]
        self.assertEqual(item["like_count"], 1)
        self.assertEqual(item["comment_count"], 1)
        self.assertTrue(item["liked_by_me"])

    def test_detail_visible_returns_post(self):
        """可见动态的详情返回 200 与正文。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.other, text="看详情")
        resp = self.client.get(f"/api/v1/posts/{post.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["text"], "看详情")

    def test_detail_invisible_returns_404(self):
        """被作者拉黑后详情给 404。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.other, text="拉黑后不可见")
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get(f"/api/v1/posts/{post.id}").status_code, 404)

    def test_detail_heavy_banned_author_returns_404(self):
        """作者重封禁后详情给 404。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.other, text="重封")
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self.client.get(f"/api/v1/posts/{post.id}").status_code, 404)

    def test_mine_only_shows_own(self):
        """``/posts/mine`` 只列自己的动态。

        参数说明:
            无。
        """
        mine = Post.objects.create(author=self.me, text="我的")
        Post.objects.create(author=self.other, text="别人的")
        data = self.client.get("/api/v1/posts/mine").json()
        self.assertEqual([item["id"] for item in data["results"]], [mine.id])


class PostDeleteTests(FeedApiMixin, APITestCase):
    """删除动态:作者可删(连带图片文件与子行)、非作者 404、同时关闭待处理举报。"""

    def setUp(self):
        """切临时 MEDIA_ROOT,造作者与另一个用户,以作者身份登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            用例要校验磁盘文件是否删掉,所以必须走临时 MEDIA_ROOT。
        """
        self.use_temp_media()
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13900139000")
        self.login(self.me)

    def test_author_can_delete_with_files_and_children(self):
        """作者删除动态:204,动态、点赞、评论行清空,磁盘图片文件也没了。

        参数说明:
            无。
        """
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
        """非作者删除给 404,动态仍然存在。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.other, text="别人的")
        self.assertEqual(self.client.delete(f"/api/v1/posts/{post.id}").status_code, 404)
        self.assertTrue(Post.objects.filter(pk=post.id).exists())

    def test_delete_closes_pending_reports_and_notifies(self):
        """删除带待处理举报的动态:举报转已处理、写备注与时间,并通知举报人。

        参数说明:
            无。
        """
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
        """造作者与点赞者,发布一条待点赞的动态,以点赞者身份登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            动态由 ``self.other`` 发布;不可见 404 用例靠用例内的拉黑关系构造。
        """
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13900139000")
        self.post = Post.objects.create(author=self.other, text="点赞我")
        self.login(self.me)

    def test_like_is_idempotent(self):
        """首次点赞 201,重复点赞 200,表里仍只有一行。

        参数说明:
            无。
        """
        first = self.client.post(f"/api/v1/posts/{self.post.id}/like")
        second = self.client.post(f"/api/v1/posts/{self.post.id}/like")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PostLike.objects.count(), 1)

    def test_unlike_is_idempotent(self):
        """取消点赞两次都 204,表里 0 行。

        参数说明:
            无。
        """
        PostLike.objects.create(post=self.post, user=self.me)
        self.assertEqual(self.client.delete(f"/api/v1/posts/{self.post.id}/like").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/v1/posts/{self.post.id}/like").status_code, 204)
        self.assertEqual(PostLike.objects.count(), 0)

    def test_like_invisible_post_404(self):
        """被作者拉黑后点赞不可见动态给 404。

        参数说明:
            无。
        """
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.post(f"/api/v1/posts/{self.post.id}/like").status_code, 404)


class PostCommentTests(FeedApiMixin, APITestCase):
    """评论:通知作者、自己评自己不通知、违禁词、正序分页、隐藏被拉黑评论者、限流。"""

    def setUp(self):
        """清限流,造「我」与作者(都带资料),发布一条动态并登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            昵称参与断言(``我`` / ``小红``);评论限流用例依赖清空 Redis 计数。
        """
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我")
        self.author = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.author, nickname="小红")
        self.post = Post.objects.create(author=self.author, text="评论我")
        self.login(self.me)

    def test_create_comment_notifies_author(self):
        """发评论 201,回显正文与昵称,提交后投递 ``post_commented`` 通知。

        参数说明:
            无。
        """
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
        """评论命中违禁词给 400 与评论专用的提示语。

        参数说明:
            无。
        """
        resp = self.client.post(f"/api/v1/posts/{self.post.id}/comments",
                                {"text": "代开发票"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["message"], "评论包含违规内容,请修改")

    def test_self_comment_does_not_notify(self):
        """作者评论自己的动态不发通知。

        参数说明:
            无。
        """
        self.login(self.author)
        with patch("im.tasks.post_commented.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/api/v1/posts/{self.post.id}/comments",
                                        {"text": "自评"}, format="json")
        self.assertEqual(resp.status_code, 201)
        delay.assert_not_called()

    def test_list_is_oldest_first_and_paginated(self):
        """评论列表按时间正序返回,``count`` 是总数。

        参数说明:
            无。
        """
        for i in range(3):
            PostComment.objects.create(post=self.post, author=self.me, text=f"c{i}")
        data = self.client.get(f"/api/v1/posts/{self.post.id}/comments").json()
        self.assertEqual([c["text"] for c in data["results"]], ["c0", "c1", "c2"])
        self.assertEqual(data["count"], 3)

    def test_list_hides_blocked_commenters(self):
        """被我拉黑的评论者,其评论不出现在列表里。

        参数说明:
            无。
        """
        PostComment.objects.create(post=self.post, author=self.me, text="可见")
        blocked = User.objects.create_user(phone="13700137000")
        Profile.objects.create(user=blocked, nickname="拉黑")
        PostComment.objects.create(post=self.post, author=blocked, text="不可见")
        Block.objects.create(blocker=self.me, blocked=blocked)
        data = self.client.get(f"/api/v1/posts/{self.post.id}/comments").json()
        self.assertEqual([c["text"] for c in data["results"]], ["可见"])

    def test_comment_throttled(self):
        """把评论限流临时改成 2/day:第三次给 429。

        参数说明:
            无。
        """
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
        """清限流,造举报人与作者,发布被举报动态并登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            ``self.url`` 是本条动态的举报路径,各用例复用;举报限流用例依赖清空 Redis 计数。
        """
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        self.author = User.objects.create_user(phone="13900139000")
        self.post = Post.objects.create(author=self.author, text="被举报的动态")
        self.login(self.me)
        self.url = f"/api/v1/posts/{self.post.id}/report"

    def test_creates_pending_report(self):
        """举报成功建待处理行,并写入待处理去重键。

        参数说明:
            无。
        """
        resp = self.client.post(self.url, {"type": "porn", "detail": "色情图"}, format="json")
        self.assertEqual(resp.status_code, 201)
        report = PostReport.objects.get()
        self.assertEqual((report.reporter, report.post, report.type),
                         (self.me, self.post, "porn"))
        self.assertEqual(report.status, ReportStatus.PENDING)
        # 待处理举报带去重键,并发提交由数据库唯一约束兜底(L-2)
        self.assertEqual(report.dedupe_key, f"{self.me.id}:{self.post.id}:pending")

    def test_duplicate_pending_is_idempotent(self):
        """重复举报待处理中的动态:第二次 200 且返回同一条,去重键不变。

        参数说明:
            无。
        """
        first = self.client.post(self.url, {"type": "porn"}, format="json")
        second = self.client.post(self.url, {"type": "fraud"}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(PostReport.objects.count(), 1)
        # 幂等命中已有行时,去重键与首次举报保持一致
        self.assertEqual(PostReport.objects.get().dedupe_key,
                         f"{self.me.id}:{self.post.id}:pending")

    def test_cannot_report_own_post(self):
        """举报自己的动态给 400。

        参数说明:
            无。
        """
        self.login(self.author)
        self.assertEqual(
            self.client.post(self.url, {"type": "other"}, format="json").status_code, 400)

    def test_invisible_post_404(self):
        """被作者拉黑后举报给 404。

        参数说明:
            无。
        """
        Block.objects.create(blocker=self.author, blocked=self.me)
        self.assertEqual(
            self.client.post(self.url, {"type": "other"}, format="json").status_code, 404)

    def test_invalid_type_rejected(self):
        """非法举报类型给 400。

        参数说明:
            无。
        """
        self.assertEqual(
            self.client.post(self.url, {"type": "spam"}, format="json").status_code, 400)

    def test_throttled(self):
        """把举报限流临时改成 1/day:第二条动态的举报给 429。

        参数说明:
            无。
        """
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
        """清限流,造三个带资料的用户,发布动态并以「我」登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            昵称参与断言(``我`` / ``楼主`` / ``路人``);``self.url`` 是本条动态的评论路径。
        """
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
        """直接落一条评论或回复,跳过接口(构造场景用)。

        参数说明:
            text: 正文。
            author: 作者,默认 ``self.me``。
            parent: 父评论,``None`` 表示顶级评论。

        返回参数:
            新建的评论实例。

        使用示例:
            ``self._comment("一楼", author=self.author)``

        备注信息:
            传了 ``parent`` 时 ``reply_to`` 自动指向父评论作者,与接口的归一化结果一致。
        """
        return PostComment.objects.create(
            post=self.post, author=author or self.me, text=text, parent=parent,
            reply_to=parent.author if parent is not None else None)

    def test_reply_to_top_level_sets_parent_and_reply_to(self):
        """回复顶级评论:``parent`` 指向该评论,``reply_to`` 指向它的作者。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.author)
        resp = self.client.post(self.url, {"text": "回复一楼", "parent_id": root.id},
                                format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["parent_id"], root.id)
        created = PostComment.objects.get(id=resp.json()["id"])
        self.assertEqual(created.parent_id, root.id)
        self.assertEqual(created.reply_to_id, self.author.id)

    def test_reply_to_reply_is_normalized_to_root(self):
        """回复楼中楼的回复:``parent`` 归一到顶级评论,``reply_to`` 仍是被回复者。

        参数说明:
            无。
        """
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
        """父评论属于另一条动态时给 404。

        参数说明:
            无。
        """
        other_post = Post.objects.create(author=self.author, text="别的")
        foreign = PostComment.objects.create(post=other_post, author=self.author, text="外")
        resp = self.client.post(self.url, {"text": "x", "parent_id": foreign.id},
                                format="json")
        self.assertEqual(resp.status_code, 404)

    def test_missing_parent_404(self):
        """父评论 id 不存在时给 404。

        参数说明:
            无。
        """
        resp = self.client.post(self.url, {"text": "x", "parent_id": 999999}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_list_only_top_level_with_two_embedded_replies(self):
        """评论列表只分页顶级评论,每项内嵌前两条回复并带 ``reply_count``。

        参数说明:
            无。
        """
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
        """被拉黑者的回复不计入 ``reply_count``,也不内嵌。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.author)
        self._comment("可见", author=self.third, parent=root)
        Block.objects.create(blocker=self.me, blocked=self.third)
        self._comment("被拉黑", author=self.third, parent=root)
        item = self.client.get(self.url).json()["results"][0]
        self.assertEqual(item["reply_count"], 0)
        self.assertEqual(item["replies"], [])

    def test_comment_count_includes_replies(self):
        """动态的 ``comment_count`` 把楼中楼回复也算进去。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.author)
        self._comment("回复", author=self.third, parent=root)
        post = self.client.get(f"/api/v1/posts/{self.post.id}").json()
        self.assertEqual(post["comment_count"], 2)

    def test_create_response_includes_reply_meta(self):
        """回复的创建响应带 ``reply_to``,``replies`` 为空、``reply_count`` 为 0。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.author)
        resp = self.client.post(self.url, {"text": "回复", "parent_id": root.id},
                                format="json")
        data = resp.json()
        self.assertEqual(data["reply_to"]["user_id"], self.author.id)
        self.assertEqual(data["reply_to"]["nickname"], "楼主")
        self.assertEqual(data["reply_count"], 0)
        self.assertEqual(data["replies"], [])

    def test_replies_endpoint_paginates_oldest_first(self):
        """回复展开接口按时间正序分页:25 条首屏取 20 条并给 ``next``。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.author)
        for i in range(25):
            self._comment(f"r{i}", author=self.third, parent=root)
        resp = self.client.get(
            f"/api/v1/posts/{self.post.id}/comments/{root.id}/replies")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 20)
        self.assertEqual(data["results"][0]["text"], "r0")
        self.assertIsNotNone(data["next"])

    def test_replies_endpoint_404_for_reply_id(self):
        """把回复 id 当楼号请求展开接口给 404。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.author)
        reply = self._comment("回复", author=self.third, parent=root)
        resp = self.client.get(
            f"/api/v1/posts/{self.post.id}/comments/{reply.id}/replies")
        self.assertEqual(resp.status_code, 404)

    def test_replies_endpoint_404_for_other_post_comment(self):
        """用别的动态的评论 id 请求展开接口给 404。

        参数说明:
            无。
        """
        other_post = Post.objects.create(author=self.author, text="别的")
        foreign = PostComment.objects.create(post=other_post, author=self.author, text="外")
        resp = self.client.get(
            f"/api/v1/posts/{self.post.id}/comments/{foreign.id}/replies")
        self.assertEqual(resp.status_code, 404)

    def test_delete_top_level_comment_cascades_replies(self):
        """删顶级评论连带删掉它的回复,返回 204。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.me)
        self._comment("回复", author=self.third, parent=root)
        resp = self.client.delete(
            f"/api/v1/posts/{self.post.id}/comments/{root.id}")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(PostComment.objects.count(), 0)

    def test_delete_reply_only_removes_itself(self):
        """删自己的回复只掉那一行,兄弟回复与楼都留着。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.author)
        mine = self._comment("我的回复", author=self.me, parent=root)
        other = self._comment("别人的回复", author=self.third, parent=root)
        resp = self.client.delete(
            f"/api/v1/posts/{self.post.id}/comments/{mine.id}")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(list(PostComment.objects.values_list("id", flat=True)),
                         [root.id, other.id])

    def test_delete_others_comment_404(self):
        """删别人的评论给 404,行还在。

        参数说明:
            无。
        """
        other = self._comment("别人的", author=self.third)
        resp = self.client.delete(
            f"/api/v1/posts/{self.post.id}/comments/{other.id}")
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(PostComment.objects.filter(pk=other.id).exists())

    def test_delete_comment_of_other_post_404(self):
        """删别的动态下的评论给 404。

        参数说明:
            无。
        """
        other_post = Post.objects.create(author=self.author, text="别的")
        foreign = PostComment.objects.create(post=other_post, author=self.me, text="外")
        resp = self.client.delete(
            f"/api/v1/posts/{self.post.id}/comments/{foreign.id}")
        self.assertEqual(resp.status_code, 404)

    def test_top_level_comment_still_notifies_post_author(self):
        """顶级评论仍走 ``post_commented`` 通知,不触发 ``post_replied``。

        参数说明:
            无。
        """
        with patch("im.tasks.post_commented.delay") as commented, \
                patch("im.tasks.post_replied.delay") as replied:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(self.url, {"text": "沙发"}, format="json")
        self.assertEqual(resp.status_code, 201)
        commented.assert_called_once_with(resp.json()["id"])
        replied.assert_not_called()

    def test_reply_notifies_replied_user(self):
        """回复走 ``post_replied`` 通知,不再触发 ``post_commented``。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.author)
        with patch("im.tasks.post_commented.delay") as commented, \
                patch("im.tasks.post_replied.delay") as replied:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(
                    self.url, {"text": "回你", "parent_id": root.id}, format="json")
        self.assertEqual(resp.status_code, 201)
        replied.assert_called_once_with(resp.json()["id"])
        commented.assert_not_called()

    def test_self_reply_does_not_notify(self):
        """自己回复自己发的楼不发提醒。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.me)
        with patch("im.tasks.post_replied.delay") as replied:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(self.url, {"text": "自回", "parent_id": root.id},
                                 format="json")
        replied.assert_not_called()

    def test_replies_are_throttled_per_user(self):
        """R4-C1:回复列表按用户限流,超限 429(生产额度 360/hour)。

        参数说明:
            无。
        """
        root = self._comment("一楼", author=self.author)
        url = f"{self.url}/{root.id}/replies"
        with patch.dict(CommentRepliesThrottle.THROTTLE_RATES, {"comment_replies": "2/hour"}):
            responses = [self.client.get(url) for _ in range(3)]
        self.assertEqual([resp.status_code for resp in responses], [200, 200, 429])
        self.assertEqual(responses[-1].json()["code"], 429)    # 统一错误信封


class FollowModelTests(TestCase):
    """关注模型:同一对关系只能有一行,方向不可互换。"""

    def setUp(self):
        """为每个用例造两个账号。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            只建 ``User``,关注关系由用例自己建;本类只验模型约束。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_follow_pair_is_unique(self):
        """同一对关注关系重复落库抛 ``IntegrityError``。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.a, followee=self.b)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Follow.objects.create(follower=self.a, followee=self.b)

    def test_follow_is_directed(self):
        """关注是有向的:``following`` 与 ``followers`` 各自只含对端。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.a, followee=self.b)
        self.assertEqual(list(self.a.following.values_list("followee_id", flat=True)),
                         [self.b.id])
        self.assertEqual(list(self.b.followers.values_list("follower_id", flat=True)),
                         [self.a.id])
        self.assertEqual(self.b.following.count(), 0)


class FollowApiTests(FeedApiMixin, APITestCase):
    """关注接口:幂等、自关注 400、拉黑/重封禁/不存在 404、鉴权与限流。"""

    def setUp(self):
        """清限流,造两个带资料的账号并以「我」登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            关注限流用例依赖清空 Redis 计数;昵称参与不了断言,可随意改。
        """
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我")
        self.other = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.other, nickname="对方")
        self.login(self.me)

    def follow_url(self, user_id=None):
        """关注接口的完整路径。

        参数说明:
            user_id: 目标账号 id;``None`` 表示 ``self.other``。

        返回参数:
            ``/api/v1/users/{id}/follow``。

        使用示例:
            ``self.follow_url(self.me.id)``

        备注信息:
            关注与取关共用同一条路径,只差 HTTP 方法。
        """
        return f"/api/v1/users/{user_id or self.other.id}/follow"

    def test_follow_creates_relation(self):
        """关注成功 204 并落一行关注关系。

        参数说明:
            无。
        """
        resp = self.client.post(self.follow_url())
        self.assertEqual(resp.status_code, 204)
        self.assertTrue(Follow.objects.filter(follower=self.me,
                                              followee=self.other).exists())

    def test_follow_is_idempotent(self):
        """关注两次都 204,表里仍只有一行。

        参数说明:
            无。
        """
        self.assertEqual(self.client.post(self.follow_url()).status_code, 204)
        self.assertEqual(self.client.post(self.follow_url()).status_code, 204)
        self.assertEqual(Follow.objects.count(), 1)

    def test_unfollow_is_idempotent(self):
        """取关两次都 204,表里 0 行(没关注过取关也是 204)。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.me, followee=self.other)
        self.assertEqual(self.client.delete(self.follow_url()).status_code, 204)
        self.assertEqual(self.client.delete(self.follow_url()).status_code, 204)
        self.assertEqual(Follow.objects.count(), 0)

    def test_cannot_follow_self(self):
        """关注自己给 400,不留关系行。

        参数说明:
            无。
        """
        resp = self.client.post(self.follow_url(self.me.id))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Follow.objects.count(), 0)

    def test_blocked_target_is_404(self):
        """目标拉黑我给 404,不留关系行。

        参数说明:
            无。
        """
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.post(self.follow_url()).status_code, 404)
        self.assertEqual(Follow.objects.count(), 0)

    def test_heavy_banned_target_is_404(self):
        """目标被重封禁给 404。

        参数说明:
            无。
        """
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self.client.post(self.follow_url()).status_code, 404)

    def test_missing_target_is_404(self):
        """目标账号不存在给 404。

        参数说明:
            无。
        """
        self.assertEqual(self.client.post(self.follow_url(999999)).status_code, 404)

    def test_requires_auth(self):
        """不带令牌关注给 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.post(self.follow_url()).status_code, 401)

    def test_follow_is_throttled(self):
        """把关注限流临时改成 1/day:同额度下的取关也给 429。

        参数说明:
            无。
        """
        from .throttles import FollowThrottle

        with patch.object(FollowThrottle, "rate", "1/day", create=True):
            self.assertEqual(self.client.post(self.follow_url()).status_code, 204)
            self.assertEqual(self.client.delete(self.follow_url()).status_code, 429)


class FollowingFeedTests(FeedApiMixin, APITestCase):
    """关注流:只含关注的人、不含自己、拉黑/重封禁过滤、游标翻页不重复。"""

    URL = "/api/v1/feed/following"

    def setUp(self):
        """清限流,造「我」与两个带资料的作者并登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            关注关系由各用例自己建;``URL`` 是关注流路径,限流用例依赖清空 Redis 计数。
        """
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我")
        self.alice = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.alice, nickname="爱丽丝")
        self.bob = User.objects.create_user(phone="13700137000")
        Profile.objects.create(user=self.bob, nickname="鲍勃")
        self.login(self.me)

    def test_empty_when_following_nobody(self):
        """没关注任何人:``count`` 为 0、列表为空、无游标。

        参数说明:
            无。
        """
        Post.objects.create(author=self.alice, text="别人的动态")
        data = self.client.get(self.URL).json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])
        self.assertIsNone(data["next_cursor"])
        self.assertFalse(data["has_more"])

    def test_only_followed_authors(self):
        """关注流只含关注的人的动态。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.me, followee=self.alice)
        mine = Post.objects.create(author=self.alice, text="关注的")
        Post.objects.create(author=self.bob, text="没关注的")
        results = self.client.get(self.URL).json()["results"]
        self.assertEqual([row["id"] for row in results], [mine.id])

    def test_excludes_own_posts_even_with_self_follow_row(self):
        """即使存在自己关注自己的脏数据,关注流也不含自己的动态。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.me, followee=self.me)   # 脏数据兜底
        Post.objects.create(author=self.me, text="自己的")
        followed = Post.objects.create(author=self.alice, text="关注的人")
        Follow.objects.create(follower=self.me, followee=self.alice)
        results = self.client.get(self.URL).json()["results"]
        self.assertEqual([row["id"] for row in results], [followed.id])

    def test_blocked_author_disappears(self):
        """被我拉黑的作者从关注流消失。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.me, followee=self.alice)
        Post.objects.create(author=self.alice, text="将被拉黑")
        Block.objects.create(blocker=self.me, blocked=self.alice)
        self.assertEqual(self.client.get(self.URL).json()["results"], [])

    def test_heavy_banned_author_hidden(self):
        """作者重封禁后其动态从关注流消失。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.me, followee=self.alice)
        Post.objects.create(author=self.alice, text="封号内容")
        Profile.objects.filter(user=self.alice).update(status=ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self.client.get(self.URL).json()["results"], [])

    def test_cursor_pagination_has_no_duplicates(self):
        """25 条动态按游标翻完:总数 25,不重复也不漏行。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.me, followee=self.alice)
        for index in range(25):
            Post.objects.create(author=self.alice, text=f"动态{index}")
        first = self.client.get(self.URL, {"limit": 10}).json()
        self.assertEqual(len(first["results"]), 10)
        self.assertTrue(first["has_more"])
        self.assertIsNotNone(first["next_cursor"])

        seen = [row["id"] for row in first["results"]]
        cursor = first["next_cursor"]
        while cursor:
            page = self.client.get(self.URL, {"limit": 10, "before": cursor}).json()
            seen.extend(row["id"] for row in page["results"])
            cursor = page["next_cursor"]
        self.assertEqual(len(seen), 25)
        self.assertEqual(len(set(seen)), 25)   # 翻页不重复、不漏行

    def test_following_feed_is_throttled_per_user(self):
        """R4-C1:关注流按用户限流,超限 429(生产额度 240/hour)。

        参数说明:
            无。
        """
        with patch.dict(FollowingReadThrottle.THROTTLE_RATES, {"following_read": "2/hour"}):
            responses = [self.client.get(self.URL) for _ in range(3)]
        self.assertEqual([resp.status_code for resp in responses], [200, 200, 429])
        self.assertEqual(responses[-1].json()["code"], 429)    # 统一错误信封


class PostLikesListTests(FeedApiMixin, APITestCase):
    """点赞列表:按点赞时间倒序、拉黑与重封禁过滤、``count`` 口径、空列表与 404、翻页。"""

    def setUp(self):
        """清限流,造「我」与作者(都带资料),发布一条动态并登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            ``self.url()`` 默认指向 ``self.post``;点赞者由 ``_liker`` 现造。
        """
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我")
        self.author = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.author, nickname="作者")
        self.post = Post.objects.create(author=self.author, text="谁赞了我")
        self.login(self.me)

    def url(self, post_id=None):
        """点赞列表的路径(默认指向 ``setUp`` 里那条动态)。

        参数说明:
            post_id: 目标动态主键;``None`` 表示 ``setUp`` 里的动态。

        返回参数:
            接口路径。

        使用示例:
            ``self.url(post_id=999999)``

        备注信息:
            动态 id 缺省取 ``self.post``;404 用例靠传一个不存在的 id 构造。
        """
        return f"/api/v1/posts/{post_id or self.post.id}/likes"

    def _liker(self, phone, nickname, at):
        """造一个点赞者,并把点赞时间钉死(避免同一微秒造成顺序不稳定)。

        参数说明:
            phone: 手机号(唯一)。
            nickname: 昵称。
            at: 点赞时间。

        返回参数:
            新建的点赞者用户。

        使用示例:
            ``self._liker("13700137000", "最早", now - timedelta(minutes=3))``

        备注信息:
            点赞行用 ``update`` 直接改 ``created_at``,绕过 ``auto_now_add``。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=nickname)
        like = PostLike.objects.create(post=self.post, user=user)
        PostLike.objects.filter(pk=like.pk).update(created_at=at)
        return user

    def test_three_likers_newest_first(self):
        """3 人点赞 → 3 条,按点赞时间倒序,字段齐全。

        参数说明:
            无。
        """
        now = timezone.now()
        first = self._liker("13700137000", "最早", now - timedelta(minutes=3))
        second = self._liker("13700137001", "中间", now - timedelta(minutes=2))
        third = self._liker("13700137002", "最后", now - timedelta(minutes=1))
        data = self.client.get(self.url()).json()
        self.assertEqual(data["count"], 3)
        self.assertEqual([row["user_id"] for row in data["results"]],
                         [third.id, second.id, first.id])
        self.assertEqual(data["results"][0]["nickname"], "最后")
        self.assertIsNone(data["results"][0]["avatar_url"])   # 无照片 → null
        self.assertEqual(sorted(data["results"][0]),
                         ["avatar_url", "liked_at", "nickname", "user_id"])
        self.assertFalse(data["has_more"])
        self.assertIsNone(data["next_cursor"])

    def test_blocked_liker_is_filtered_and_count_follows(self):
        """我拉黑的人不出现,``count`` 是**过滤后**的人数(不是原始点赞数)。

        参数说明:
            无。
        """
        now = timezone.now()
        blocked = self._liker("13700137000", "被拉黑", now - timedelta(minutes=3))
        kept = self._liker("13700137001", "可见", now - timedelta(minutes=2))
        self._liker("13700137002", "也可见", now - timedelta(minutes=1))
        Block.objects.create(blocker=self.me, blocked=blocked)
        data = self.client.get(self.url()).json()
        self.assertEqual(data["count"], 2)
        visible_ids = [row["user_id"] for row in data["results"]]
        self.assertEqual(len(visible_ids), 2)
        self.assertNotIn(blocked.id, visible_ids)
        self.assertIn(kept.id, visible_ids)

    def test_liker_who_blocked_me_is_filtered_too(self):
        """反方向拉黑同样过滤:对方拉黑我,他也从我的点赞列表里消失。

        参数说明:
            无。
        """
        now = timezone.now()
        blocker = self._liker("13700137000", "拉黑我的人", now - timedelta(minutes=2))
        self._liker("13700137001", "可见", now - timedelta(minutes=1))
        Block.objects.create(blocker=blocker, blocked=self.me)
        data = self.client.get(self.url()).json()
        self.assertEqual(data["count"], 1)
        self.assertNotIn(blocker.id, [row["user_id"] for row in data["results"]])

    def test_heavy_banned_liker_is_filtered(self):
        """被重封禁的账号不出现,且不计入 ``count``。

        参数说明:
            无。
        """
        now = timezone.now()
        banned = self._liker("13700137000", "封号", now - timedelta(minutes=2))
        self._liker("13700137001", "可见", now - timedelta(minutes=1))
        Profile.objects.filter(user=banned).update(status=ProfileStatus.BANNED_HEAVY)
        data = self.client.get(self.url()).json()
        self.assertEqual(data["count"], 1)
        self.assertNotIn(banned.id, [row["user_id"] for row in data["results"]])

    def test_heavy_banned_author_returns_404(self):
        """动态作者被重封禁 → 整个接口 404(不是空列表)。

        参数说明:
            无。
        """
        Profile.objects.filter(user=self.author).update(status=ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_invisible_post_returns_404(self):
        """与作者互相拉黑 → 404(不暴露动态是否存在)。

        参数说明:
            无。
        """
        Block.objects.create(blocker=self.author, blocked=self.me)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_missing_post_returns_404(self):
        """动态不存在 → 404。

        参数说明:
            无。
        """
        self.assertEqual(self.client.get(self.url(post_id=999999)).status_code, 404)

    def test_no_likes_returns_empty_list(self):
        """没人点赞 → 200 + ``results: []`` + ``count: 0``(不 404)。

        参数说明:
            无。
        """
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])
        self.assertFalse(data["has_more"])

    def test_cursor_pagination_has_no_duplicates(self):
        """游标翻页不重复、不漏行(游标建在点赞行上)。

        参数说明:
            无。
        """
        now = timezone.now()
        expected = [
            self._liker(f"1370013{index:04d}", f"赞{index}",
                        now - timedelta(minutes=10 - index)).id
            for index in range(5)
        ]
        seen = []
        cursor = None
        while True:
            params = {"limit": 2}
            if cursor:
                params["before"] = cursor
            page = self.client.get(self.url(), params).json()
            seen.extend(row["user_id"] for row in page["results"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(seen, list(reversed(expected)))

    def test_likes_list_is_throttled_per_user(self):
        """按用户限流,超限 429(生产额度 120/hour)。

        参数说明:
            无。
        """
        with patch.dict(PostLikesReadThrottle.THROTTLE_RATES, {"post_likes_read": "2/hour"}):
            responses = [self.client.get(self.url()) for _ in range(3)]
        self.assertEqual([resp.status_code for resp in responses], [200, 200, 429])
        self.assertEqual(responses[-1].json()["code"], 429)    # 统一错误信封


class PostFavoriteApiTests(FeedApiMixin, APITestCase):
    """收藏/取消收藏:恒 204 幂等、不发通知、不可见 404、可收藏自己的动态、限流。"""

    def setUp(self):
        """清限流,造「我」与作者(都带资料),发布一条动态并登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            ``self.url()`` 默认指向 ``self.post``;收藏限流用例依赖清空 Redis 计数。
        """
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我")
        self.author = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.author, nickname="作者")
        self.post = Post.objects.create(author=self.author, text="收藏我")
        self.login(self.me)

    def url(self, post_id=None):
        """收藏接口的路径(默认指向 ``setUp`` 里那条动态)。

        参数说明:
            post_id: 目标动态主键;``None`` 表示 ``setUp`` 里的动态。

        返回参数:
            接口路径。

        使用示例:
            ``self.url(post_id=999999)``

        备注信息:
            收藏与取消收藏共用同一条路径,只差 HTTP 方法。
        """
        return f"/api/v1/posts/{post_id or self.post.id}/favorite"

    def test_favorite_is_idempotent(self):
        """POST 两次都 204,表里只落一行。

        参数说明:
            无。
        """
        first = self.client.post(self.url())
        second = self.client.post(self.url())
        self.assertEqual([first.status_code, second.status_code], [204, 204])
        self.assertEqual(first.content, b"")
        self.assertEqual(PostFavorite.objects.count(), 1)

    def test_unfavorite_is_idempotent(self):
        """DELETE 两次都 204,表里 0 行(没收藏过取消也是 204)。

        参数说明:
            无。
        """
        PostFavorite.objects.create(post=self.post, user=self.me)
        self.assertEqual(self.client.delete(self.url()).status_code, 204)
        self.assertEqual(self.client.delete(self.url()).status_code, 204)
        self.assertEqual(PostFavorite.objects.count(), 0)

    def test_favorite_does_not_notify_or_enqueue_im(self):
        """收藏前后站内通知条数不变;不动通知服务,也不入队任何 IM 灰条。

        参数说明:
            无。
        """
        before = InAppNotification.objects.count()
        with patch("feed.views.notify_on_commit") as notify, \
                patch("im.tasks.post_commented.delay") as im_commented, \
                patch("im.tasks.post_replied.delay") as im_replied:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(self.url())
        self.assertEqual(resp.status_code, 204)
        notify.assert_not_called()
        im_commented.assert_not_called()
        im_replied.assert_not_called()
        self.assertEqual(InAppNotification.objects.count(), before)

    def test_favorite_invisible_post_404(self):
        """与作者互相拉黑后收藏给 404。

        参数说明:
            无。
        """
        Block.objects.create(blocker=self.author, blocked=self.me)
        self.assertEqual(self.client.post(self.url()).status_code, 404)

    def test_favorite_missing_post_404(self):
        """动态不存在时收藏给 404。

        参数说明:
            无。
        """
        self.assertEqual(self.client.post(self.url(post_id=999999)).status_code, 404)

    def test_can_favorite_own_post(self):
        """书签语义:收藏自己的动态允许。

        参数说明:
            无。
        """
        mine = Post.objects.create(author=self.me, text="自己的")
        self.assertEqual(self.client.post(self.url(mine.id)).status_code, 204)
        self.assertEqual(PostFavorite.objects.filter(post=mine).count(), 1)

    def test_favorite_is_throttled_per_user(self):
        """POST/DELETE 共用 ``post_favorite`` 额度(生产 300/hour)。

        参数说明:
            无。
        """
        with patch.dict(PostFavoriteThrottle.THROTTLE_RATES, {"post_favorite": "2/hour"}):
            responses = [self.client.post(self.url()) for _ in range(3)]
        self.assertEqual([resp.status_code for resp in responses], [204, 204, 429])
        self.assertEqual(responses[-1].json()["code"], 429)


class FavoritesFeedTests(FeedApiMixin, APITestCase):
    """我的收藏:按收藏时间倒序(不是发帖时间)、帖子删除/作者拉黑后消失、翻页。"""

    URL = "/api/v1/feed/favorites"

    def setUp(self):
        """清限流,造「我」与作者(都带资料)并登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            动态与收藏行都由各用例自己造,收藏时间用 ``_favorite`` 钉死。
        """
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我")
        self.author = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.author, nickname="作者")
        self.login(self.me)

    def _favorite(self, post, at):
        """收藏一条动态并把收藏时间钉死。

        参数说明:
            post: 目标动态。
            at: 收藏时间。

        返回参数:
            新建的收藏行。

        使用示例:
            ``self._favorite(post, now - timedelta(minutes=2))``

        备注信息:
            用 ``update`` 直改 ``created_at``,绕过 ``auto_now_add``;排序断言依赖它。
        """
        favorite = PostFavorite.objects.create(post=post, user=self.me)
        PostFavorite.objects.filter(pk=favorite.pk).update(created_at=at)
        return favorite

    def test_empty_when_nothing_favorited(self):
        """没收藏任何动态:``count`` 为 0、列表为空、无游标。

        参数说明:
            无。
        """
        Post.objects.create(author=self.author, text="没人收藏")
        data = self.client.get(self.URL).json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])
        self.assertIsNone(data["next_cursor"])

    def test_ordered_by_favorite_time_not_post_time(self):
        """先收藏新帖、后收藏老帖 → 返回顺序与**发帖时间相反**(抓「按发帖时间排」)。

        参数说明:
            无。
        """
        now = timezone.now()
        old_post = Post.objects.create(author=self.author, text="老帖")
        new_post = Post.objects.create(author=self.author, text="新帖")
        Post.objects.filter(pk=old_post.pk).update(created_at=now - timedelta(days=2))
        Post.objects.filter(pk=new_post.pk).update(created_at=now)
        self._favorite(new_post, now - timedelta(minutes=2))   # 先收藏的是新帖
        self._favorite(old_post, now - timedelta(minutes=1))   # 后收藏的是老帖
        data = self.client.get(self.URL).json()
        self.assertEqual([row["id"] for row in data["results"]],
                         [old_post.id, new_post.id])

    def test_deleted_post_disappears(self):
        """删掉中间那条帖子 → 列表少一条,``count`` 也跟着减。

        参数说明:
            无。
        """
        now = timezone.now()
        posts = [Post.objects.create(author=self.author, text=f"帖{index}") for index in range(3)]
        for index, post in enumerate(posts):
            self._favorite(post, now - timedelta(minutes=3 - index))
        posts[1].delete()
        data = self.client.get(self.URL).json()
        self.assertEqual(data["count"], 2)
        self.assertEqual([row["id"] for row in data["results"]],
                         [posts[2].id, posts[0].id])

    def test_blocked_author_disappears(self):
        """某条动态的作者把我拉黑 → 那条消失,另一条照常返回。

        参数说明:
            无。
        """
        now = timezone.now()
        blocker = User.objects.create_user(phone="13700137000")
        Profile.objects.create(user=blocker, nickname="会拉黑我")
        kept = Post.objects.create(author=self.author, text="留着")
        gone = Post.objects.create(author=blocker, text="会被拉黑")
        self._favorite(kept, now - timedelta(minutes=2))
        self._favorite(gone, now - timedelta(minutes=1))
        Block.objects.create(blocker=blocker, blocked=self.me)
        data = self.client.get(self.URL).json()
        self.assertEqual([row["id"] for row in data["results"]], [kept.id])
        self.assertEqual(data["count"], 1)
    def test_cursor_pagination_has_no_duplicates(self):
        """游标翻页按收藏时间倒序,不重复、不漏行。

        参数说明:
            无。
        """
        now = timezone.now()
        posts = [Post.objects.create(author=self.author, text=f"帖{index}") for index in range(5)]
        for index, post in enumerate(posts):
            self._favorite(post, now - timedelta(minutes=10 - index))
        seen = []
        cursor = None
        while True:
            params = {"limit": 2}
            if cursor:
                params["before"] = cursor
            page = self.client.get(self.URL, params).json()
            seen.extend(row["id"] for row in page["results"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(seen, [post.id for post in reversed(posts)])

    def test_favorites_feed_is_throttled_per_user(self):
        """按用户限流,超限 429(生产额度 120/hour)。

        参数说明:
            无。
        """
        with patch.dict(FavoritesReadThrottle.THROTTLE_RATES, {"favorites_read": "2/hour"}):
            responses = [self.client.get(self.URL) for _ in range(3)]
        self.assertEqual([resp.status_code for resp in responses], [200, 200, 429])


class PostFavoriteStateTests(FeedApiMixin, APITestCase):
    """``is_favorited``:广场/详情/我的动态都随收藏翻转,``liked_by_me`` 行为不变。"""

    def setUp(self):
        """清限流,造「我」与作者(都带资料)并登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``(由 ``unittest`` 在每个用例前自动调用)

        备注信息:
            本类只验 ``is_favorited`` 的口径;动态与收藏行由各用例自己造。
        """
        self.clear_throttle_cache()
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我")
        self.author = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.author, nickname="作者")
        self.login(self.me)

    def test_square_marks_only_favorited_post(self):
        """广场一页里只有收藏过的那条 ``is_favorited`` 为 true。

        参数说明:
            无。
        """
        favorited = Post.objects.create(author=self.author, text="收藏了")
        Post.objects.create(author=self.author, text="没收藏")
        PostFavorite.objects.create(post=favorited, user=self.me)
        rows = {row["id"]: row for row in self.client.get("/api/v1/posts").json()["results"]}
        self.assertTrue(rows[favorited.id]["is_favorited"])
        others = [row for row_id, row in rows.items() if row_id != favorited.id]
        self.assertEqual(len(others), 1)
        self.assertFalse(others[0]["is_favorited"])

    def test_liked_by_me_is_unaffected(self):
        """收藏不影响 ``liked_by_me``:只收藏不点赞时它是 false,两者互相独立。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.author, text="只收藏")
        PostFavorite.objects.create(post=post, user=self.me)
        row = self.client.get("/api/v1/posts").json()["results"][0]
        self.assertTrue(row["is_favorited"])
        self.assertFalse(row["liked_by_me"])
        self.assertEqual(row["like_count"], 0)

    def test_detail_exposes_is_favorited(self):
        """详情响应同样带 ``is_favorited``。

        参数说明:
            无。
        """
        post = Post.objects.create(author=self.author, text="详情")
        PostFavorite.objects.create(post=post, user=self.me)
        self.assertTrue(self.client.get(f"/api/v1/posts/{post.id}").json()["is_favorited"])

    def test_my_posts_exposes_is_favorited(self):
        """``views.my_posts`` 也走了同一行注解,自己的收藏同样能看到。

        参数说明:
            无。
        """
        mine = Post.objects.create(author=self.me, text="我的")
        PostFavorite.objects.create(post=mine, user=self.me)
        rows = self.client.get("/api/v1/posts/mine").json()["results"]
        self.assertEqual([row["id"] for row in rows], [mine.id])
        self.assertTrue(rows[0]["is_favorited"])

    def test_following_feed_exposes_is_favorited(self):
        """关注流复用 ``visible_posts``,因此同样带 ``is_favorited``。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.me, followee=self.author)
        post = Post.objects.create(author=self.author, text="关注的")
        PostFavorite.objects.create(post=post, user=self.me)
        rows = self.client.get("/api/v1/feed/following").json()["results"]
        self.assertTrue(rows[0]["is_favorited"])
