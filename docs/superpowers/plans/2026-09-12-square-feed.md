# 广场页(动态流)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「广场」页:用户可发布文字/图片动态(≤9 图九宫格),浏览信息流、点赞评论、动态可举报,运营台可管理与审核。

**Architecture:** 后端新 Django app `feed`(五张表:Post/PostImage/PostLike/PostComment/PostReport;接口前缀 `/api/v1/posts`;IM 副作用走 Celery 任务;ops 加两个页面)。前端新 `features/square/`(广场流/发布页/详情页/我的动态),复用现有 repository/provider/假网络测试模式。

**Tech Stack:** Django 5.2 + DRF、Celery、Flutter(Riverpod 3.4、go_router)、腾讯云 IM(系统通知灰条)。

**Spec:** `docs/superpowers/specs/2026-09-12-square-feed-design.md`(实现细节以 spec 为准)

## Global Constraints

- 后端 cwd = `chatapp/`,Python 用 anaconda 环境 `Django`(python 命令);前端 cwd = `app/`,用 `../flutter/bin/flutter.bat`。
- 跑后端测试前 Redis 必须起:`docker compose -f docker-compose.dev.yml up -d`(测试自动用 DB15 缓存 / DB14 broker)。
- 后端全量:`python manage.py test`;单 app:`python manage.py test feed`。前端 `flutter.bat analyze` **必须零告警**,`flutter.bat test` 全绿。
- 任何触发 IM 入队的路径,测试一律 `patch("im.tasks.<任务名>.delay")` + `with self.captureOnCommitCallbacks(execute=True):`;任务体测试 mock `im.client.*`(腾讯 REST 一次不真打)。
- 图片上限:动态最多 9 张、单张 ≤5MB(与照片上传同款校验);文字 ≤500、评论 ≤200。
- 文案(固定值,接口 400 message / 前端提示都要一致):空动态「写点文字或选张图片吧」、超量「最多 9 张图片」、超大「单张图片不能超过 5MB」、评论敏感词「评论包含违规内容,请修改」、动态敏感词「内容包含违规内容,请修改」、举报提交提示「已收到举报,我们会尽快处理」、空态「还没有动态,发一条吧」、评论通知文案「{昵称} 评论了你的动态:{摘要}」(摘要 = 评论前 50 字)。
- 新增限流额度(settings `DEFAULT_THROTTLE_RATES`):`post_create: 20/day`、`post_comment: 60/day`、`post_report: 20/day`。
- 测试图片用 `users/tests.py` 同款 `PNG_1PX`;写盘用例用 `tempfile.mkdtemp()` + `self.settings(MEDIA_ROOT=...)` 并 `addCleanup(shutil.rmtree, ...)`。
- 每个任务末尾提交(conventional commits:`feat(feed): ...` / `feat(app): ...` / `docs: ...`)。

---

### Task 1: feed app 骨架 + 五张表模型 + 迁移

**Files:**
- Create: `chatapp/feed/__init__.py`、`chatapp/feed/apps.py`、`chatapp/feed/models.py`、`chatapp/feed/migrations/__init__.py`、`chatapp/feed/tests.py`(空起步,每任务往里加)
- Modify: `chatapp/config/settings.py`(INSTALLED_APPS 追加 `"feed"`)

**Interfaces:**
- Produces: 模型 `feed.models.Post`、`PostImage`、`PostLike`、`PostComment`、`PostReport`(含字段与 related_name,后续所有任务依赖)。

- [ ] **Step 1: 建 app 骨架并注册**

`chatapp/feed/__init__.py`、`chatapp/feed/migrations/__init__.py` 建空文件;`chatapp/feed/apps.py`:

```python
from django.apps import AppConfig


class FeedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "feed"
```

`settings.py` 的 INSTALLED_APPS 业务 app 列表末尾(`"notifications"` 后)加 `"feed"`。

- [ ] **Step 2: 写失败的模型测试**

`chatapp/feed/tests.py`:

```python
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from moderation.models import ReportStatus, ReportType

from .models import Post, PostComment, PostImage, PostLike, PostReport

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
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd chatapp && python manage.py test feed`
Expected: FAIL(`ModuleNotFoundError`/`ImportError`:feed.models 不存在)

- [ ] **Step 4: 写 models.py**

```python
from django.conf import settings
from django.db import models

from moderation.models import ReportStatus, ReportType


class Post(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="posts")
    text = models.TextField("正文", max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"post#{self.pk}({self.author_id})"


class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="images")
    file = models.ImageField("图片", upload_to="posts/%Y/%m/")
    order = models.PositiveSmallIntegerField("排序", default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"post_image#{self.pk}(post={self.post_id})"


class PostLike(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="post_likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "user"], name="uniq_post_like"),
        ]

    def __str__(self):
        return f"post_like({self.post_id}:{self.user_id})"


class PostComment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="post_comments")
    text = models.CharField("内容", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"post_comment#{self.pk}(post={self.post_id})"


class PostReport(models.Model):
    """动态举报;post 用 SET_NULL:动态删除后举报行留档(运营对账)。"""

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="post_reports")
    post = models.ForeignKey(Post, null=True, on_delete=models.SET_NULL,
                             related_name="reports")
    type = models.CharField("类型", max_length=20, choices=ReportType.choices)
    detail = models.CharField("补充说明", max_length=200, blank=True)
    status = models.CharField("状态", max_length=10, choices=ReportStatus.choices,
                              default=ReportStatus.PENDING)
    handled_note = models.CharField("处理备注", max_length=200, blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="post_reports_handled")
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"post_report#{self.pk}({self.reporter_id}->{self.post_id}:{self.type})"
```

- [ ] **Step 5: 生成迁移并跑测试**

Run: `cd chatapp && python manage.py makemigrations feed && python manage.py migrate && python manage.py test feed`
Expected: makemigrations 生成 `0001_initial`;测试 5 个全 PASS

- [ ] **Step 6: 提交**

```bash
git add chatapp/feed chatapp/config/settings.py
git commit -m "feat(feed): 新建 feed app 与五张表模型(动态/图片/点赞/评论/举报)"
```

---

### Task 2: 发布动态接口 + 序列化基础

**Files:**
- Create: `chatapp/feed/serializers.py`、`chatapp/feed/throttles.py`、`chatapp/feed/urls.py`、`chatapp/feed/views.py`、`chatapp/feed/services.py`
- Modify: `chatapp/config/settings.py`(DEFAULT_THROTTLE_RATES)、`chatapp/config/api_urls.py`、`chatapp/feed/tests.py`

**Interfaces:**
- Consumes: Task 1 的模型。
- Produces:
  - `feed.services.visible_posts(viewer) -> QuerySet[Post]`(带 `like_count`/`comment_count`/`liked_by_me` 注解;Task 3 起被流/详情/点赞/评论/举报复用)——本任务先放最小版本,仅注解不加过滤?**不**:过滤在 Task 3 写,本任务先产出该函数并只做注解 + select_related/prefetch,过滤与排序在 Task 3 补?为避免返工,本任务直接写完整版(含拉黑与重封禁过滤),测试在 Task 3。
  - `feed.services.delete_post(post) -> None`(Task 4 实现,本任务不写)
  - `feed.serializers.PostSerializer`(字段:`id/author/text/images/like_count/comment_count/liked_by_me/created_at`;author = `{user_id, nickname, avatar_url}`)
  - `feed.throttles.PostCreateThrottle`(scope `post_create`;非 POST 不限)
  - `POST /api/v1/posts`(multipart;201 返回 PostSerializer;限流)
  - `config.api_urls` 注册 `path("", include("feed.urls"))`

- [ ] **Step 1: 写失败的发布接口测试**

`chatapp/feed/tests.py` 追加:

```python
import base64
import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FeedApiMixin:
    def login(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def use_temp_media(self):
        media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=media_dir)
        override.enable()
        self.addCleanup(override.disable)

    def image(self, name="a.png"):
        return SimpleUploadedFile(name, PNG_1PX, content_type="image/png")


class PostCreateTests(FeedApiMixin, APITestCase):
    URL = "/api/v1/posts"

    def setUp(self):
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
        resp = self.client.post(self.URL, {"text": "看图", "images": [self.image("a.png"), self.image("b.png")]},
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
            self.assertEqual(self.client.post(self.URL, {"text": "1"}, format="multipart").status_code, 201)
            self.assertEqual(self.client.post(self.URL, {"text": "2"}, format="multipart").status_code, 201)
            self.assertEqual(self.client.post(self.URL, {"text": "3"}, format="multipart").status_code, 429)
```

注意:限流计数在 Redis,若用例间互相污染,在该测试类 `setUp` 加 `cache.clear()` + `addCleanup(cache.clear)`(参照 `moderation/tests.py::ReportApiTests`)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test feed.tests.PostCreateTests`
Expected: FAIL(404,路由不存在——Scripted 404 即「测试没铺」风格的后端等价:响应 404)

- [ ] **Step 3: 写 serializers.py / throttles.py / services.py / views.py / urls.py 并注册**

`chatapp/feed/serializers.py`:

```python
from rest_framework import serializers

from moderation.text_check import find_blocked_word
from users.models import PhotoStatus

from .models import Post, PostComment


def author_brief(user, request):
    profile = getattr(user, "profile", None)
    avatar_url = None
    for photo in user.photos.all():
        if photo.status == PhotoStatus.APPROVED:
            avatar_url = request.build_absolute_uri(photo.file.url)
            break
    return {"user_id": user.id, "nickname": profile.nickname if profile else "",
            "avatar_url": avatar_url}


class PostSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    like_count = serializers.IntegerField(read_only=True, default=0)
    comment_count = serializers.IntegerField(read_only=True, default=0)
    liked_by_me = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Post
        fields = ["id", "author", "text", "images", "like_count", "comment_count",
                  "liked_by_me", "created_at"]

    def get_author(self, post):
        return author_brief(post.author, self.context["request"])

    def get_images(self, post):
        request = self.context["request"]
        return [request.build_absolute_uri(image.file.url) for image in post.images.all()]


class PostCommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = PostComment
        fields = ["id", "author", "text", "created_at"]

    def get_author(self, comment):
        return author_brief(comment.author, self.context["request"])


class PostCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate_text(self, value):
        if value and find_blocked_word(value):
            raise serializers.ValidationError("内容包含违规内容,请修改")
        return value.strip()

    def validate(self, attrs):
        files = self.context["request"].FILES.getlist("images")
        if not attrs.get("text") and not files:
            raise serializers.ValidationError("写点文字或选张图片吧")
        if len(files) > 9:
            raise serializers.ValidationError("最多 9 张图片")
        image_field = serializers.ImageField()
        for file in files:
            if file.size > 5 * 1024 * 1024:
                raise serializers.ValidationError("单张图片不能超过 5MB")
            image_field.run_validation(file)   # PIL 校验确实是图片,失败抛 400
        return attrs
```

`chatapp/feed/throttles.py`:

```python
from rest_framework.throttling import SimpleRateThrottle


class PostCreateThrottle(SimpleRateThrottle):
    """按用户限流发布动态;额度在 settings.DEFAULT_THROTTLE_RATES["post_create"]。"""

    scope = "post_create"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
```

`chatapp/feed/services.py`(本任务先写 `visible_posts`,过滤规则完整版一并写;delete_post/notify 后续任务加):

```python
from django.db.models import Count, Exists, OuterRef

from moderation.services import blocked_user_ids
from users.models import ProfileStatus

from .models import Post, PostLike


def visible_posts(viewer):
    """广场可见动态:排除双向拉黑与重封禁作者;命中注解赞/评数与「我是否已赞」。"""
    blocked = blocked_user_ids(viewer)
    return (Post.objects
            .exclude(author_id__in=blocked)
            .exclude(author__profile__status=ProfileStatus.BANNED_HEAVY)
            .select_related("author__profile")
            .prefetch_related("author__photos", "images")
            .annotate(like_count=Count("likes", distinct=True),
                      comment_count=Count("comments", distinct=True),
                      liked_by_me=Exists(
                          PostLike.objects.filter(post=OuterRef("pk"), user=viewer))))
```

`chatapp/feed/views.py`:

```python
from django.db import transaction
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from .models import Post, PostImage
from .serializers import PostCreateSerializer, PostSerializer
from .throttles import PostCreateThrottle


@api_view(["POST"])
@throttle_classes([PostCreateThrottle])
def posts(request):
    serializer = PostCreateSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        post = Post.objects.create(author=request.user, text=serializer.validated_data["text"])
        for order, file in enumerate(request.FILES.getlist("images")):
            PostImage.objects.create(post=post, file=file, order=order)
    post = visible_posts(request.user).get(pk=post.pk)
    return Response(PostSerializer(post, context={"request": request}).data, status=201)
```

`chatapp/feed/urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("posts", views.posts),
]
```

`chatapp/config/api_urls.py` 的 urlpatterns 末尾(`path("matches", ...)` 后)加:

```python
    path("", include("feed.urls")),
```

`chatapp/config/settings.py` 的 `DEFAULT_THROTTLE_RATES` 加三个键:

```python
        "post_create": "20/day",
        "post_comment": "60/day",
        "post_report": "20/day",
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test feed.tests.PostCreateTests`
Expected: PASS(8 个)

- [ ] **Step 5: 提交**

```bash
git add chatapp/feed chatapp/config
git commit -m "feat(feed): 发布动态接口(multipart 多图/敏感词/限流)"
```

---

### Task 3: 广场流 + 详情 + 我的动态

**Files:**
- Modify: `chatapp/feed/views.py`、`chatapp/feed/urls.py`、`chatapp/feed/tests.py`

**Interfaces:**
- Consumes: `feed.services.visible_posts`、`feed.serializers.PostSerializer`(Task 2)。
- Produces:
  - `GET /api/v1/posts`(分页 `{count,next,previous,results}`)
  - `GET /api/v1/posts/{id}`(不可见 → 404)
  - `GET /api/v1/posts/mine`(仅自己,标注计数,不过滤)

- [ ] **Step 1: 写失败的测试**

`chatapp/feed/tests.py` 追加:

```python
from moderation.models import Block
from users.models import Profile, ProfileStatus


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test feed.tests.FeedFlowTests`
Expected: FAIL(`GET /api/v1/posts` 405;mine/详情 404)

- [ ] **Step 3: 实现视图与路由**

`chatapp/feed/views.py` 改 `posts` 支持 GET,并新增详情与 mine。文件顶部 import 更新为:

```python
from django.db import transaction
from django.db.models import Count, Exists, OuterRef
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config.pagination import DefaultLimitOffsetPagination

from .models import Post, PostImage, PostLike
from .serializers import PostCreateSerializer, PostSerializer
from .services import visible_posts
from .throttles import PostCreateThrottle


def _page_response(request, queryset):
    paginator = DefaultLimitOffsetPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(
        PostSerializer(page, many=True, context={"request": request}).data)


@api_view(["GET", "POST"])
@throttle_classes([PostCreateThrottle])
def posts(request):
    if request.method == "POST":
        return _create_post(request)
    return _page_response(request, visible_posts(request.user))


def _create_post(request):
    serializer = PostCreateSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        post = Post.objects.create(author=request.user, text=serializer.validated_data["text"])
        for order, file in enumerate(request.FILES.getlist("images")):
            PostImage.objects.create(post=post, file=file, order=order)
    post = visible_posts(request.user).get(pk=post.pk)
    return Response(PostSerializer(post, context={"request": request}).data, status=201)


@api_view(["GET"])
def my_posts(request):
    queryset = (Post.objects.filter(author=request.user)
                .select_related("author__profile").prefetch_related("author__photos", "images")
                .annotate(like_count=Count("likes", distinct=True),
                          comment_count=Count("comments", distinct=True),
                          liked_by_me=Exists(
                              PostLike.objects.filter(post=OuterRef("pk"), user=request.user))))
    return _page_response(request, queryset)


@api_view(["GET"])
def post_detail(request, post_id):
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    return Response(PostSerializer(post, context={"request": request}).data)
```

注意:`PostCreateThrottle` 现在挂在 `posts` 的 GET 上也会被调用 —— 在 throttle 里放行非 POST(见 Step 4)。

`chatapp/feed/urls.py` 全量:

```python
urlpatterns = [
    path("posts", views.posts),
    path("posts/mine", views.my_posts),
    path("posts/<int:post_id>", views.post_detail),
]
```

(mine 必须在 `<int:post_id>` 之前无冲突——int 转换器不匹配 "mine",但保持此顺序可读性更好。)

- [ ] **Step 4: throttle 放行非 POST**

`chatapp/feed/throttles.py` 的 `PostCreateThrottle` 加:

```python
    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd chatapp && python manage.py test feed`
Expected: PASS(全部)

- [ ] **Step 6: 提交**

```bash
git add chatapp/feed
git commit -m "feat(feed): 广场流/详情/我的动态接口(拉黑与重封禁过滤/分页/计数)"
```

---

### Task 4: 删除动态(服务收口:先关举报再删)

**Files:**
- Modify: `chatapp/feed/services.py`、`chatapp/feed/views.py`、`chatapp/feed/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `PostReport` 模型、`moderation.services.notify_report_handled`(签名:`(report) -> None`,只取 `report.reporter_id`)。
- Produces: `feed.services.delete_post(post) -> None`(作者自删与 ops 删除共用;Task 7/8 依赖)。`DELETE /api/v1/posts/{id}`(非作者 404)。

- [ ] **Step 1: 写失败的测试**

```python
class PostDeleteTests(FeedApiMixin, APITestCase):
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
        import os
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test feed.tests.PostDeleteTests`
Expected: FAIL(405,DELETE 未实现)

- [ ] **Step 3: 实现 delete_post 服务 + 视图**

`chatapp/feed/services.py` 追加(顶部补 import):

```python
from django.db import transaction
from django.utils import timezone

from im import tasks as im_tasks
from moderation.models import ReportStatus
from moderation.services import notify_report_handled


def delete_post(post) -> None:
    """删除动态:先关闭该动态全部待处理举报(标记 + 通知),再删图片文件与行。

    作者自删与运营删除共用:否则作者自删后举报会在 ops 队列里悬空。
    """
    pending = list(PostReport.objects.filter(post=post, status=ReportStatus.PENDING))
    for report in pending:
        report.status = ReportStatus.HANDLED
        report.handled_note = "动态已删除"
        report.handled_at = timezone.now()
        report.save(update_fields=["status", "handled_note", "handled_at"])
        notify_report_handled(report)   # 内部 on_commit 入队
    for image in post.images.all():
        image.file.delete(save=False)
    post.delete()
```

(`PostReport` 从 `.models` import;`_enqueue` 帮助函数本任务还不存在则直接调 `notify_report_handled`,它与本项目其他服务一样用 on_commit——注意 `moderation.services.notify_report_handled` 已含 on_commit,不需要再包。)

`chatapp/feed/views.py` 的 `post_detail` 改为:

```python
@api_view(["GET", "DELETE"])
def post_detail(request, post_id):
    if request.method == "DELETE":
        post = get_object_or_404(Post, pk=post_id, author=request.user)   # 非作者 404
        delete_post(post)
        return Response(status=204)
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    return Response(PostSerializer(post, context={"request": request}).data)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test feed`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/feed
git commit -m "feat(feed): 删除动态接口 + delete_post 服务收口(连带关闭举报)"
```

---

### Task 5: 点赞 + 评论 + 评论通知

**Files:**
- Modify: `chatapp/im/client.py`、`chatapp/im/tasks.py`、`chatapp/im/tests.py`、`chatapp/feed/services.py`、`chatapp/feed/serializers.py`、`chatapp/feed/throttles.py`、`chatapp/feed/views.py`、`chatapp/feed/urls.py`、`chatapp/feed/tests.py`

**Interfaces:**
- Consumes: Task 2 的 `visible_posts`/`PostCommentSerializer`。
- Produces:
  - `im.client.send_post_commented(to_identifier, commenter_nickname, snippet) -> bool`
  - `im.tasks.post_commented(comment_id: int)`(Celery 任务,注册名 `im.tasks.post_commented`)
  - `feed.services.notify_post_commented(comment) -> None`(作者本人评论不入队)
  - `POST/DELETE /api/v1/posts/{id}/like`(201/200/204)
  - `GET/POST /api/v1/posts/{id}/comments`(POST 201 返回评论;限流;列表分页正序)
  - `feed.throttles.PostCommentThrottle`(scope `post_comment`;非 POST 不限)

- [ ] **Step 1: 写失败的测试(后端三处)**

`chatapp/im/tests.py` 追加(贴该文件现有 `test_send_report_handled_payload` / `test_report_handled_task` 的风格:client 打桩用 `patch("im.client._request", return_value={"ErrorCode": 0})`,任务体打桩用 `patch("im.client.send_post_commented", return_value=True)`):

```python
class PostCommentedClientTests(TestCase):
    def test_send_post_commented_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_post_commented("u9", "小红", "好漂亮"))
        args = req.call_args[0]
        self.assertEqual(args[:2], ("openim", "sendmsg"))
        payload = args[2]
        self.assertEqual(payload["From_Account"], "system_notice")
        self.assertEqual(payload["To_Account"], "u9")
        content = payload["MsgBody"][0]["MsgContent"]
        self.assertEqual(json.loads(content["Data"]), {"type": "post_commented"})
        self.assertEqual(content["Desc"], "小红 评论了你的动态:好漂亮")

    def test_send_post_commented_network_error_returns_false(self):
        with patch("im.client._request", side_effect=RuntimeError("boom")):
            self.assertFalse(send_post_commented("u9", "小红", "好漂亮"))


class PostCommentedTaskTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(phone="13800138000")
        self.commenter = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.commenter, nickname="小红")
        self.post = Post.objects.create(author=self.author, text="动态")

    def test_task_sends_notice_to_author(self):
        comment = PostComment.objects.create(post=self.post, author=self.commenter, text="好漂亮")
        with patch("im.client.send_post_commented", return_value=True) as send:
            post_commented_task.run(comment.id)
        send.assert_called_once_with(self.author.im_user_id, "小红", "好漂亮")

    def test_self_comment_not_sent(self):
        comment = PostComment.objects.create(post=self.post, author=self.author, text="自评")
        with patch("im.client.send_post_commented") as send:
            post_commented_task.run(comment.id)
        send.assert_not_called()

    def test_missing_comment_is_silent(self):
        post_commented_task.run(999999)   # 不抛异常
```

顶部 import 调整:`from .client import (...)` 行加 `send_post_commented`;`from .tasks import (...)` 的别名 import 行加 `post_commented as post_commented_task`;另补 `from feed.models import Post, PostComment` 与 `from users.models import Profile`(以该文件现有 import 情况为准,已有则不重复)。

`chatapp/feed/tests.py` 追加:

```python
class PostLikeTests(FeedApiMixin, APITestCase):
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
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test feed.tests.PostLikeTests feed.tests.PostCommentTests im.tests`
Expected: FAIL(路由 404 / 函数不存在)

- [ ] **Step 3: 实现后端**

`chatapp/im/client.py` 顶部文案区加:

```python
POST_COMMENTED_TEMPLATE = "{nickname} 评论了你的动态:{snippet}"
```

并在 `send_report_handled` 后加:

```python
def send_post_commented(to_identifier: str, commenter_nickname: str, snippet: str) -> bool:
    """动态被评论通知:以「系统通知」身份发给动态作者。"""
    desc = POST_COMMENTED_TEMPLATE.format(nickname=commenter_nickname, snippet=snippet)
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "post_commented"}, desc)
```

`chatapp/im/tasks.py` 尾部加(函数内 import feed 模型,避免模块加载顺序问题):

```python
@shared_task(**RETRY_POLICY)
def post_commented(comment_id: int) -> None:
    """动态被评论:告知动态作者(自己评自己不打扰;内容缺失静默)。"""
    from feed.models import PostComment

    comment = (PostComment.objects.filter(id=comment_id)
               .select_related("post__author__profile", "author__profile").first())
    if comment is None or comment.post is None:
        return
    author = comment.post.author
    if author.id == comment.author_id:
        return
    nickname = getattr(comment.author.profile, "nickname", "") or f"u{comment.author_id}"
    _require(im_client.send_post_commented(author.im_user_id, nickname, comment.text[:50]),
             "post_commented")
```

(注意:若 `comment.author` 没有 profile,`getattr(comment.author, "profile", None)` 更稳 —— 用 `profile = getattr(comment.author, "profile", None)` 再取 nickname。)

`chatapp/feed/services.py` 追加:

```python
from im import tasks as im_tasks


def notify_post_commented(comment) -> None:
    """评论创建后调用:给动态作者发通知(经任务队列)。

    评论者是作者本人时不入队(自己评自己不打扰)。
    """
    if comment.post.author_id == comment.author_id:
        return
    transaction.on_commit(lambda: im_tasks.post_commented.delay(comment.id), robust=True)
```

(`im` 与 `django.db.transaction` 顶部 import;`PostReport` 等已有 import 保持。)

`chatapp/feed/serializers.py` 追加评论创建校验:

```python
class PostCommentCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=200)

    def validate_text(self, value):
        if find_blocked_word(value):
            raise serializers.ValidationError("评论包含违规内容,请修改")
        text = value.strip()
        if not text:
            raise serializers.ValidationError("评论不能为空")
        return text
```

`chatapp/feed/throttles.py` 追加:

```python
class PostCommentThrottle(SimpleRateThrottle):
    """按用户限流发评论;只限 POST(看评论列表不限)。"""

    scope = "post_comment"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)
```

`chatapp/feed/views.py`:顶部 import 追加(合并进已有 import 行)——

```python
from moderation.services import blocked_user_ids
from users.models import ProfileStatus

from .models import PostComment, PostLike
from .serializers import PostCommentCreateSerializer, PostCommentSerializer
from .services import notify_post_commented
from .throttles import PostCommentThrottle
```

再追加两个视图:

```python
@api_view(["POST", "DELETE"])
def post_like(request, post_id):
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    if request.method == "POST":
        _, created = PostLike.objects.get_or_create(post=post, user=request.user)
        return Response({"liked": True}, status=201 if created else 200)
    PostLike.objects.filter(post=post, user=request.user).delete()
    return Response(status=204)


@api_view(["GET", "POST"])
@throttle_classes([PostCommentThrottle])
def post_comments(request, post_id):
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    if request.method == "POST":
        serializer = PostCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = PostComment.objects.create(post=post, author=request.user,
                                             text=serializer.validated_data["text"])
        notify_post_commented(comment)
        return Response(PostCommentSerializer(comment, context={"request": request}).data,
                        status=201)
    blocked = blocked_user_ids(request.user)
    comments = (post.comments
                .exclude(author_id__in=blocked)
                .exclude(author__profile__status=ProfileStatus.BANNED_HEAVY)
                .select_related("author__profile").prefetch_related("author__photos"))
    return _page_response(request, comments)
```

`chatapp/feed/urls.py` 加:

```python
    path("posts/<int:post_id>/like", views.post_like),
    path("posts/<int:post_id>/comments", views.post_comments),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test feed im`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/feed chatapp/im
git commit -m "feat(feed): 点赞/评论接口 + 评论通知任务(post_commented)"
```

---

### Task 6: 动态举报接口

**Files:**
- Modify: `chatapp/feed/serializers.py`、`chatapp/feed/throttles.py`、`chatapp/feed/views.py`、`chatapp/feed/urls.py`、`chatapp/feed/tests.py`

**Interfaces:**
- Consumes: Task 2 的 `visible_posts`、Task 1 的 `PostReport`。
- Produces: `POST /api/v1/posts/{id}/report`(201 新建 / 200 幂等);`feed.throttles.PostReportThrottle`(scope `post_report`)。

- [ ] **Step 1: 写失败的测试**

```python
class PostReportTests(FeedApiMixin, APITestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test feed.tests.PostReportTests`
Expected: FAIL(404 路由不存在)

- [ ] **Step 3: 实现**

`chatapp/feed/serializers.py` 追加:

```python
from moderation.models import ReportType


class PostReportCreateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=ReportType.choices)
    detail = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
```

`chatapp/feed/throttles.py` 追加:

```python
class PostReportThrottle(SimpleRateThrottle):
    """按用户限流举报动态;额度在 settings.DEFAULT_THROTTLE_RATES["post_report"]。"""

    scope = "post_report"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
```

`chatapp/feed/views.py`:顶部 import 追加——

```python
from rest_framework.exceptions import ValidationError

from moderation.models import ReportStatus

from .models import PostReport
from .serializers import PostReportCreateSerializer
from .throttles import PostReportThrottle
```

再追加视图:

```python
@api_view(["POST"])
@throttle_classes([PostReportThrottle])
def post_report(request, post_id):
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    if post.author_id == request.user.id:
        raise ValidationError("不能举报自己的动态")
    serializer = PostReportCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    report, created = PostReport.objects.get_or_create(
        reporter=request.user, post=post, status=ReportStatus.PENDING,
        defaults={"type": serializer.validated_data["type"],
                  "detail": serializer.validated_data["detail"]})
    return Response({"id": report.id, "status": report.status},
                    status=201 if created else 200)
```

`chatapp/feed/urls.py` 加:

```python
    path("posts/<int:post_id>/report", views.post_report),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test feed`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/feed
git commit -m "feat(feed): 动态举报接口(幂等/可见性校验/限流)"
```

---

### Task 7: ops 动态管理页

**Files:**
- Modify: `chatapp/ops/views.py`、`chatapp/ops/urls.py`、`chatapp/ops/templates/ops/base.html`、`chatapp/ops/context_processors.py`、`chatapp/ops/tests.py`
- Create: `chatapp/ops/templates/ops/posts.html`、`chatapp/ops/templates/ops/partials/posts_table.html`

**Interfaces:**
- Consumes: `feed.services.delete_post`(Task 4)。
- Produces: `/ops/posts/`(列表)、`POST /ops/posts/{id}/delete`(HTMX 局部刷新表格 partial)。

- [ ] **Step 1: 写失败的测试**

`chatapp/ops/tests.py` 追加(复用文件里 `make_staff`):

```python
class OpsPostsTests(TestCase):
    def setUp(self):
        from feed.models import Post, PostLike

        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.user, nickname="小红")
        self.post = Post.objects.create(author=self.user, text="违规动态")
        PostLike.objects.create(post=self.post, user=self.staff)

    def test_posts_list_shows_post(self):
        resp = self.client.get("/ops/posts/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "违规动态")
        self.assertContains(resp, "小红")

    def test_delete_removes_post(self):
        from feed.models import Post

        resp = self.client.post(f"/ops/posts/{self.post.id}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Post.objects.filter(pk=self.post.id).exists())

    def test_non_staff_forbidden(self):
        plain = User.objects.create_user(phone="13800138001")
        self.client.force_login(plain)
        self.assertEqual(self.client.get("/ops/posts/").status_code, 403)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test ops.tests.OpsPostsTests`
Expected: FAIL(404)

- [ ] **Step 3: 实现**

`chatapp/ops/views.py` 追加(import 顶部补 `from feed.models import Post`、`from feed.services import delete_post`;`Count` 已在该文件 import):

```python
def _posts_queryset():
    return (Post.objects.select_related("author__profile")
            .prefetch_related("images")
            .annotate(like_count=Count("likes", distinct=True),
                      comment_count=Count("comments", distinct=True))
            .order_by("-created_at")[:200])


@staff_required
def posts(request):
    return render(request, "ops/posts.html", {"posts": _posts_queryset()})


@require_POST
@staff_required
def post_delete(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    delete_post(post)
    return render(request, "ops/partials/posts_table.html", {"posts": _posts_queryset()})
```

`chatapp/ops/urls.py` 加:

```python
    path("posts/", views.posts, name="posts"),
    path("posts/<int:post_id>/delete", views.post_delete, name="post_delete"),
```

`chatapp/ops/templates/ops/posts.html`:

```html
{% extends "ops/base.html" %}
{% block page_title %}动态管理{% endblock %}
{% block content %}
{% include "ops/partials/posts_table.html" %}
{% endblock %}
```

`chatapp/ops/templates/ops/partials/posts_table.html`:

```html
<article>
<table id="posts-table">
  <thead><tr><th>图</th><th>时间</th><th>作者</th><th>内容</th><th>赞</th><th>评</th><th></th></tr></thead>
  <tbody>
  {% for post in posts %}
    <tr>
      <td>{% with image=post.images.first %}{% if image %}<img class="thumb" src="{{ image.file.url }}" alt="">{% endif %}{% endwith %}</td>
      <td>{{ post.created_at|date:"m-d H:i" }}</td>
      <td>{{ post.author.profile.nickname|default:post.author.phone }}({{ post.author.phone }})</td>
      <td>{{ post.text|truncatechars:40|default:"(无文字)" }}</td>
      <td>{{ post.like_count }}</td>
      <td>{{ post.comment_count }}</td>
      <td>
        <form hx-post="{% url 'ops:post_delete' post.id %}" hx-target="#posts-table" hx-swap="outerHTML">
          <button type="submit" class="danger" onclick="return confirm('删除这条动态?')">删除</button>
        </form>
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="7">还没有动态</td></tr>
  {% endfor %}
  </tbody>
</table>
</article>
```

`chatapp/ops/templates/ops/base.html` 导航在「照片审核」后插入:

```html
      <a href="{% url 'ops:posts' %}" class="{% if '/ops/posts' in request.path %}active{% endif %}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
        动态管理
      </a>
```

`chatapp/ops/context_processors.py` 加 badge(导入 `from feed.models import PostReport`):

```python
        "pending_post_report_count": PostReport.objects.filter(status=ReportStatus.PENDING).count(),
```

(导航 badge 在 Task 8 的「动态举报」项上使用;本任务先不加展示,处理器加字段即可。)

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test ops`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): 动态管理页(列表 + 删除)"
```

---

### Task 8: ops 动态举报队列页

**Files:**
- Modify: `chatapp/ops/views.py`、`chatapp/ops/urls.py`、`chatapp/ops/templates/ops/base.html`(导航加「动态举报」+ badge)、`chatapp/ops/tests.py`
- Create: `chatapp/ops/templates/ops/post_reports.html`、`chatapp/ops/templates/ops/partials/post_reports_table.html`

**Interfaces:**
- Consumes: `feed.services.delete_post`、`moderation.services.notify_report_handled`、`feed.models.PostReport`。
- Produces: `/ops/post-reports/`(筛选列表)、`POST /ops/post-reports/{id}/handle`(忽略)、`POST /ops/post-reports/{id}/delete-post`(删除动态)。

- [ ] **Step 1: 写失败的测试**

```python
class OpsPostReportsTests(TestCase):
    def setUp(self):
        from feed.models import Post, PostReport

        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.reporter = User.objects.create_user(phone="13800138000")
        self.author = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.author, nickname="小红")
        self.post = Post.objects.create(author=self.author, text="被举报的动态")
        self.report = PostReport.objects.create(reporter=self.reporter, post=self.post,
                                                type="porn", detail="色情")

    def test_queue_shows_pending(self):
        resp = self.client.get("/ops/post-reports/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "被举报的动态")
        self.assertContains(resp, "色情")

    def test_ignore_marks_handled_and_notifies(self):
        from feed.models import PostReport

        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/post-reports/{self.report.id}/handle",
                                        {"note": "内容没问题"})
        self.assertEqual(resp.status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.HANDLED)
        self.assertEqual(self.report.handled_note, "内容没问题")
        self.assertEqual(self.report.handled_by, self.staff)
        delay.assert_called_once_with(self.reporter.id)
        self.assertTrue(PostReport.objects.filter(pk=self.report.pk).exists())

    def test_delete_post_removes_and_closes_all_pending(self):
        from feed.models import Post, PostReport

        second = PostReport.objects.create(reporter=self.staff, post=self.post, type="other")
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/post-reports/{self.report.id}/delete-post")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Post.objects.filter(pk=self.post.pk).exists())
        self.report.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.HANDLED)
        self.assertEqual(self.report.handled_note, "动态已删除")
        self.assertEqual(second.status, ReportStatus.HANDLED)
        self.assertEqual(delay.call_count, 2)   # 两个举报者各一次

    def test_repeat_handle_does_not_notify_again(self):
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/post-reports/{self.report.id}/handle", {"note": "一"})
                self.client.post(f"/ops/post-reports/{self.report.id}/handle", {"note": "二"})
        self.assertEqual(delay.call_count, 1)

    def test_non_staff_forbidden(self):
        plain = User.objects.create_user(phone="13800138001")
        self.client.force_login(plain)
        self.assertEqual(self.client.get("/ops/post-reports/").status_code, 403)
```

注意:测试文件顶部已 import 的东西按现有文件补(`ReportStatus` 来自 `moderation.models`,已在文件顶部 import)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test ops.tests.OpsPostReportsTests`
Expected: FAIL(404)

- [ ] **Step 3: 实现**

`chatapp/ops/views.py` 追加:

```python
from django.utils import timezone

from feed.models import PostReport
from moderation.models import ReportStatus, ReportType
from moderation.services import notify_report_handled

from .decorators import staff_required   # 已有


def _post_reports_queryset(status):
    qs = (PostReport.objects.select_related("post__author__profile", "reporter", "handled_by")
          .order_by("-status", "-created_at"))
    if status in ReportStatus.values:
        qs = qs.filter(status=status)
    return qs[:200]


def _render_post_reports(request):
    status = request.POST.get("status") or request.GET.get("status") or ReportStatus.PENDING
    return render(request, "ops/partials/post_reports_table.html",
                  {"reports": _post_reports_queryset(status), "status": status})


@staff_required
def post_reports(request):
    status = request.GET.get("status", ReportStatus.PENDING)
    return render(request, "ops/post_reports.html", {
        "reports": _post_reports_queryset(status), "status": status,
        "types": ReportType.choices,
    })


@require_POST
@staff_required
def post_report_handle(request, report_id):
    report = get_object_or_404(PostReport, pk=report_id)
    if report.status == ReportStatus.PENDING:
        report.status = ReportStatus.HANDLED
        report.handled_note = request.POST.get("note", "").strip()[:200]
        report.handled_by = request.user
        report.handled_at = timezone.now()
        report.save(update_fields=["status", "handled_note", "handled_by", "handled_at"])
        notify_report_handled(report)
    return _render_post_reports(request)


@require_POST
@staff_required
def post_report_delete_post(request, report_id):
    from feed.services import delete_post

    report = get_object_or_404(PostReport.objects.select_related("post"), pk=report_id)
    if report.status == ReportStatus.PENDING:
        if report.post is not None:
            delete_post(report.post)   # 内部:全部 pending 标 handled + 各举报者通知 + 删行
        else:
            # 动态已被作者删除(post 置空)但举报还挂着:只关闭这条
            report.status = ReportStatus.HANDLED
            report.handled_note = "动态已删除"
            report.handled_by = request.user
            report.handled_at = timezone.now()
            report.save(update_fields=["status", "handled_note", "handled_by", "handled_at"])
            notify_report_handled(report)
    return _render_post_reports(request)
```

`chatapp/ops/urls.py` 加:

```python
    path("post-reports/", views.post_reports, name="post_reports"),
    path("post-reports/<int:report_id>/handle", views.post_report_handle, name="post_report_handle"),
    path("post-reports/<int:report_id>/delete-post", views.post_report_delete_post,
         name="post_report_delete_post"),
```

`chatapp/ops/templates/ops/post_reports.html`:

```html
{% extends "ops/base.html" %}
{% block page_title %}动态举报{% endblock %}
{% block content %}
<p class="ops-tabs">
  <a href="?status=pending" class="{% if status == 'pending' %}active{% endif %}">待处理</a>
  <a href="?status=handled" class="{% if status == 'handled' %}active{% endif %}">已处理</a>
</p>
{% include "ops/partials/post_reports_table.html" %}
{% endblock %}
```

`chatapp/ops/templates/ops/partials/post_reports_table.html`:

```html
<article>
<table id="post-reports-table">
  <thead><tr><th>时间</th><th>类型</th><th>举报人</th><th>动态</th><th>作者</th><th>状态</th><th></th></tr></thead>
  <tbody>
  {% for r in reports %}
    <tr>
      <td>{{ r.created_at|date:"m-d H:i" }}</td>
      <td>{{ r.get_type_display }}</td>
      <td>{{ r.reporter.phone }}</td>
      <td>{% if r.post %}{{ r.post.text|truncatechars:30|default:"(无文字)" }}{% else %}(动态已删除){% endif %}</td>
      <td>{% if r.post %}<a href="{% url 'ops:user_detail' r.post.author.id %}">{{ r.post.author.profile.nickname|default:r.post.author.phone }}</a>{% else %}—{% endif %}</td>
      <td>{% if r.status == 'pending' %}<span class="tag tag-orange">待处理</span>{% else %}<span class="tag tag-green">已处理</span>{% if r.handled_note %}({{ r.handled_note }}){% endif %}{% endif %}</td>
      <td>
        {% if r.status == 'pending' %}
        <form hx-post="{% url 'ops:post_report_delete_post' r.id %}" hx-target="#post-reports-table" hx-swap="outerHTML" style="display:inline">
          <button type="submit" class="danger" onclick="return confirm('删除这条动态?')">删除动态</button>
        </form>
        <form hx-post="{% url 'ops:post_report_handle' r.id %}" hx-target="#post-reports-table" hx-swap="outerHTML" style="display:inline">
          <input type="text" name="note" maxlength="200" placeholder="备注(可选)">
          <button type="submit" class="secondary">忽略</button>
        </form>
        {% endif %}
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="7">没有符合条件的举报</td></tr>
  {% endfor %}
  </tbody>
</table>
</article>
```

`chatapp/ops/templates/ops/base.html` 在「动态管理」后加导航项(带 badge):

```html
      <a href="{% url 'ops:post_reports' %}" class="{% if '/ops/post-reports' in request.path %}active{% endif %}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round"><path d="M4 22V4"/><path d="M4 4c4-2 8 2 12 0v10c-4 2-8-2-12 0"/></svg>
        动态举报{% if pending_post_report_count %}<span class="ops-badge">{{ pending_post_report_count }}</span>{% endif %}
      </a>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test ops`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): 动态举报队列(删除动态/忽略 + 举报者通知闭环)"
```

---

### Task 9: 前端——底部 tab + 广场流页

**Files:**
- Create: `app/lib/features/square/models.dart`、`app/lib/features/square/feed_repository.dart`、`app/lib/features/square/square_controller.dart`、`app/lib/features/square/square_page.dart`、`app/lib/features/square/widgets/post_card.dart`、`app/lib/features/square/widgets/post_images.dart`、`app/test/features/square/square_page_test.dart`
- Modify: `app/lib/features/shell/home_shell.dart`、`app/lib/core/format.dart`、`app/test/features/shell/home_shell_test.dart`、`app/test/core/format_test.dart`

**Interfaces:**
- Consumes: 后端 `GET /posts`(分页 results 结构同现有约定)。
- Produces(后续任务依赖):
  - `models.dart`:`Post`(id/author/`FeedAuthor`/text/images/likeCount/commentCount/likedByMe/createdAt + `copyWith`)、`FeedAuthor(userId,nickname,avatarUrl)`、`PostCommentItem(id,author,text,createdAt)`
  - `feed_repository.dart`:`FeedRepository.fetchPosts({limit,offset}) -> Future<({List<Post> items, bool hasMore})>`;`feedRepositoryProvider`
  - `square_controller.dart`:`squareProvider`(AsyncNotifier,autoDispose;方法 `reload()`、`loadMore()`、`toggleLike(Post)`);`myPostsProvider`(同型,后续任务用)
  - `widgets/post_card.dart`:`PostCard({post, onToggleLike, onTap, onOpenImage, menuAction})` —— `menuAction` 为后续任务(删除/举报)预留:`void Function(String action)?`(action 取 `'delete'`/`'report'`)
  - `widgets/post_images.dart`:`PostImages({urls, onTap})`(九宫格:1 大 / 2-4 两列 / 5-9 三列)
  - `format.dart::formatPostTime(DateTime, {DateTime? now})`
- 注意:tab 顺序改为 发现 / 广场 / 消息 / 我的;`home_shell_test.dart` 的「三个 Tab 都在」必须同步改为断言 4 个。

- [ ] **Step 1: 写失败的测试**

`app/test/core/format_test.dart` 追加:

```dart
import 'package:chatapp_app/core/format.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('formatPostTime 按间隔返回相对时间', () {
    final now = DateTime(2026, 9, 12, 20, 0);
    expect(formatPostTime(now.subtract(const Duration(seconds: 30)), now: now), '刚刚');
    expect(formatPostTime(now.subtract(const Duration(minutes: 5)), now: now), '5 分钟前');
    expect(formatPostTime(now.subtract(const Duration(hours: 3)), now: now), '3 小时前');
    expect(formatPostTime(now.subtract(const Duration(days: 2)), now: now), '2 天前');
    expect(formatPostTime(DateTime(2026, 8, 1), now: now), '8 月 1 日');
    expect(formatPostTime(DateTime(2025, 12, 1), now: now), '2025 年 12 月 1 日');
  });
}
```

`app/test/features/shell/home_shell_test.dart` 的「三个 Tab 都在」用例改为:

```dart
  testWidgets('四个 Tab 都在;广场可切换', (tester) async {
    final adapter = _adapter(profile: profileJson(nickname: '小明'))
      ..routes['GET /posts'] = (options) => ok(postsPageJson([]));

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(navTab('发现'), findsOneWidget);
    expect(navTab('广场'), findsOneWidget);
    expect(navTab('消息'), findsOneWidget);
    expect(navTab('我的'), findsOneWidget);

    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();
    expect(find.text('还没有动态,发一条吧'), findsOneWidget);
  });
```

(需要 `app/test/support/sample_data.dart` 增加 `postsPageJson(List<Map<String, dynamic>> items)` 帮助函数:`{'count': items.length, 'next': null, 'previous': null, 'results': items}`。)

`app/test/features/square/square_page_test.dart`(新建):

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('广场流渲染卡片(昵称/文字/计数)', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(postsPageJson([
            postJson(id: 1, nickname: 'Alice', text: '今天天气真好', likeCount: 3, commentCount: 1),
          ])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    expect(find.text('Alice'), findsOneWidget);
    expect(find.text('今天天气真好'), findsOneWidget);
    expect(find.text('3'), findsOneWidget);
    expect(find.byKey(const Key('square.fab')), findsOneWidget);
  });

  testWidgets('空态显示提示与刷新', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(postsPageJson([])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    expect(find.text('还没有动态,发一条吧'), findsOneWidget);
  });

  testWidgets('点赞乐观更新;失败回滚', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(postsPageJson([postJson(id: 1, nickname: 'Alice', text: '赞我')])),
      // 请求失败 → 走回滚分支
      'POST /posts/1/like': offline,
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.like.1')));
    await tester.pump();   // 乐观:马上变红
    expect(tester.widget<Icon>(find.byIcon(Icons.favorite)).color, const Color(0xFFFF2C55));
    await tester.pumpAndSettle();   // 请求失败 → 回滚
    expect(find.byIcon(Icons.favorite_border), findsOneWidget);
  });
}
```

(假网络抛错的 helper 名字以 `scripted_adapter.dart` 现有导出为准——文件里已有一个抛连接错误的函数 `offline(options)`;直接用它:`'POST /posts/1/like': offline`。)

`app/test/support/sample_data.dart` 追加:

```dart
Map<String, dynamic> postJson({
  int id = 1,
  int authorId = 9,
  String nickname = 'Alice',
  String? avatarUrl,
  String text = '你好',
  List<String> images = const [],
  int likeCount = 0,
  int commentCount = 0,
  bool likedByMe = false,
  String createdAt = '2026-09-12T20:00:00+08:00',
}) =>
    {
      'id': id,
      'author': {'user_id': authorId, 'nickname': nickname, 'avatar_url': avatarUrl},
      'text': text,
      'images': images,
      'like_count': likeCount,
      'comment_count': commentCount,
      'liked_by_me': likedByMe,
      'created_at': createdAt,
    };

Map<String, dynamic> postsPageJson(List<Map<String, dynamic>> items, {bool hasMore = false}) =>
    {'count': items.length, 'next': hasMore ? 'more' : null, 'previous': null, 'results': items};
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/core/format_test.dart test/features/shell test/features/square`
Expected: FAIL(formatPostTime 未定义 / 广场 tab 不存在 / 文件不存在)

- [ ] **Step 3: 实现**

`app/lib/core/format.dart` 追加:

```dart
/// 动态相对时间:刚刚 / x 分钟前 / x 小时前 / x 天前(7 天内)/ M 月 d 日 / yyyy 年 M 月 d 日。
String formatPostTime(DateTime time, {DateTime? now}) {
  final n = now ?? DateTime.now();
  final diff = n.difference(time);
  if (diff.inMinutes < 1) return '刚刚';
  if (diff.inMinutes < 60) return '${diff.inMinutes} 分钟前';
  if (diff.inHours < 24) return '${diff.inHours} 小时前';
  if (diff.inDays < 7) return '${diff.inDays} 天前';
  if (time.year == n.year) return '${time.month} 月 ${time.day} 日';
  return '${time.year} 年 ${time.month} 月 ${time.day} 日';
}
```

`app/lib/features/square/models.dart`:

```dart
class FeedAuthor {
  const FeedAuthor({required this.userId, required this.nickname, this.avatarUrl});

  final int userId;
  final String nickname;
  final String? avatarUrl;

  factory FeedAuthor.fromJson(Map<String, dynamic> json) => FeedAuthor(
        userId: json['user_id'] as int,
        nickname: json['nickname'] as String? ?? '',
        avatarUrl: json['avatar_url'] as String?,
      );
}

class Post {
  const Post({
    required this.id,
    required this.author,
    required this.text,
    required this.images,
    required this.likeCount,
    required this.commentCount,
    required this.likedByMe,
    required this.createdAt,
  });

  final int id;
  final FeedAuthor author;
  final String text;
  final List<String> images;
  final int likeCount;
  final int commentCount;
  final bool likedByMe;
  final DateTime createdAt;

  factory Post.fromJson(Map<String, dynamic> json) => Post(
        id: json['id'] as int,
        author: FeedAuthor.fromJson(json['author'] as Map<String, dynamic>),
        text: json['text'] as String? ?? '',
        images: (json['images'] as List<dynamic>? ?? []).cast<String>(),
        likeCount: json['like_count'] as int? ?? 0,
        commentCount: json['comment_count'] as int? ?? 0,
        likedByMe: json['liked_by_me'] as bool? ?? false,
        createdAt: DateTime.parse(json['created_at'] as String),
      );

  Post copyWith({int? likeCount, bool? likedByMe}) => Post(
        id: id, author: author, text: text, images: images,
        likeCount: likeCount ?? this.likeCount,
        commentCount: commentCount, likedByMe: likedByMe ?? this.likedByMe,
        createdAt: createdAt);
}

class PostCommentItem {
  const PostCommentItem({required this.id, required this.author,
      required this.text, required this.createdAt});

  final int id;
  final FeedAuthor author;
  final String text;
  final DateTime createdAt;

  factory PostCommentItem.fromJson(Map<String, dynamic> json) => PostCommentItem(
        id: json['id'] as int,
        author: FeedAuthor.fromJson(json['author'] as Map<String, dynamic>),
        text: json['text'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
      );
}
```

`app/lib/features/square/feed_repository.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

class FeedRepository {
  FeedRepository(this._api);

  final ApiClient _api;

  Future<({List<Post> items, bool hasMore})> fetchPosts(
      {int limit = 20, int offset = 0, String path = '/posts'}) async {
    final page = await _api.get(path, query: {'limit': limit, 'offset': offset})
        as Map<String, dynamic>;
    final items = (page['results'] as List<dynamic>)
        .map((item) => Post.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, hasMore: page['next'] != null);
  }

  Future<void> toggleLike(int postId, {required bool like}) async {
    if (like) {
      await _api.post('/posts/$postId/like');
    } else {
      await _api.delete('/posts/$postId/like');
    }
  }
}

final feedRepositoryProvider = Provider<FeedRepository>(
    (ref) => FeedRepository(ref.watch(apiClientProvider)));
```

`app/lib/features/square/square_controller.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'feed_repository.dart';
import 'models.dart';

class SquareController extends AsyncNotifier<List<Post>> {
  bool _hasMore = true;

  @override
  Future<List<Post>> build() => _fetchFirst();

  Future<List<Post>> _fetchFirst() async {
    final page = await ref.read(feedRepositoryProvider).fetchPosts();
    _hasMore = page.hasMore;
    return page.items;
  }

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(_fetchFirst);
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !_hasMore) return;
    final page = await ref
        .read(feedRepositoryProvider)
        .fetchPosts(offset: current.length);
    _hasMore = page.hasMore;
    final existing = current.map((post) => post.id).toSet();
    state = AsyncValue.data(
        [...current, ...page.items.where((post) => !existing.contains(post.id))]);
  }

  /// 点赞乐观更新:先改本地再发请求,失败回滚并抛出(页面弹提示)。
  Future<void> toggleLike(Post post) async {
    final target = !post.likedByMe;
    _patch(post.id, likedByMe: target, likeCount: post.likeCount + (target ? 1 : -1));
    try {
      await ref.read(feedRepositoryProvider).toggleLike(post.id, like: target);
    } catch (_) {
      _patch(post.id, likedByMe: post.likedByMe, likeCount: post.likeCount);
      rethrow;
    }
  }

  void _patch(int postId, {required bool likedByMe, required int likeCount}) {
    final current = state.value;
    if (current == null) return;
    state = AsyncValue.data([
      for (final post in current)
        post.id == postId ? post.copyWith(likedByMe: likedByMe, likeCount: likeCount) : post,
    ]);
  }
}

final squareProvider =
    AsyncNotifierProvider.autoDispose<SquareController, List<Post>>(
  SquareController.new,
  retry: (retryCount, error) => null,
);
```

(notifier 基类与 provider 写法照抄项目现有 `chat_controller.dart`:`AsyncNotifierProvider.autoDispose` 是 Riverpod 3.4 的标准 builder,notifier 类 `extends AsyncNotifier<State>`。)

`app/lib/features/square/widgets/post_images.dart`:

```dart
import 'package:flutter/material.dart';

/// 微博式九宫格:1 张大图;2-4 张两列;5-9 张三列。
class PostImages extends StatelessWidget {
  const PostImages({super.key, required this.urls, this.onTap});

  final List<String> urls;
  final void Function(int index)? onTap;

  @override
  Widget build(BuildContext context) {
    if (urls.isEmpty) return const SizedBox.shrink();
    if (urls.length == 1) {
      return GestureDetector(
        onTap: () => onTap?.call(0),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: SizedBox(width: 200, height: 200, child: _image(0)),
        ),
      );
    }
    final columns = urls.length <= 4 ? 2 : 3;
    return GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: columns,
      mainAxisSpacing: 4,
      crossAxisSpacing: 4,
      children: [
        for (var i = 0; i < urls.length; i++)
          GestureDetector(onTap: () => onTap?.call(i), child: _image(i)),
      ],
    );
  }

  Widget _image(int index) => Image.network(
        urls[index],
        fit: BoxFit.cover,
        errorBuilder: (c, e, s) => Container(
          color: const Color(0xFFEFE3E7),
          child: const Icon(Icons.image_outlined, color: Colors.white70),
        ),
      );
}
```

`app/lib/features/square/widgets/post_card.dart`:

```dart
import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../models.dart';
import 'post_images.dart';

/// 动态卡片:头像/昵称/相对时间/正文/九宫格/点赞评论行;右上 ··· 菜单。
class PostCard extends StatelessWidget {
  const PostCard({
    super.key,
    required this.post,
    required this.isMine,
    this.onTap,
    this.onToggleLike,
    this.onOpenImage,
    this.menuAction,
  });

  final Post post;
  /// 是否自己的动态(决定 ··· 菜单是「删除」还是「举报」);调用方算:
  /// post.author.userId == ref.watch(profileProvider).value?.userId
  final bool isMine;
  final VoidCallback? onTap;
  final VoidCallback? onToggleLike;
  final void Function(int index)? onOpenImage;
  /// 菜单动作:'delete' | 'report';为 null 时不显示 ··· 菜单。
  final void Function(String action)? menuAction;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.white,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 6),
      child: InkWell(
        key: Key('post.card.${post.id}'),
        onTap: onTap,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 40, height: 40,
              decoration: BoxDecoration(
                  color: const Color(0xFFC9CDD4),
                  borderRadius: BorderRadius.circular(6)),
              clipBehavior: Clip.antiAlias,
              child: post.author.avatarUrl == null
                  ? Center(child: Text(
                      post.author.nickname.isEmpty ? '?' : post.author.nickname.substring(0, 1),
                      style: const TextStyle(color: Colors.white)))
                  : Image.network(post.author.avatarUrl!, fit: BoxFit.cover,
                      errorBuilder: (c, e, s) => const Icon(Icons.person, color: Colors.white)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    Expanded(child: Text(post.author.nickname,
                        style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15))),
                    if (menuAction != null)
                      SizedBox(
                        width: 28, height: 20,
                        child: PopupMenuButton<String>(
                          key: Key('post.more.${post.id}'),
                          padding: EdgeInsets.zero,
                          iconSize: 18,
                          icon: const Icon(Icons.more_horiz, color: Color(0xFF999999)),
                          onSelected: (value) => menuAction!(value),
                          itemBuilder: (context) => [
                            if (isMine)
                              const PopupMenuItem(
                                  key: Key('post.menu.delete'), value: 'delete',
                                  child: Text('删除'))
                            else
                              const PopupMenuItem(
                                  key: Key('post.menu.report'), value: 'report',
                                  child: Text('举报')),
                          ],
                        ),
                      ),
                  ]),
                  if (post.text.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(post.text, style: const TextStyle(fontSize: 15, height: 1.4)),
                  ],
                  if (post.images.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    PostImages(urls: post.images, onTap: onOpenImage),
                  ],
                  const SizedBox(height: 4),
                  Row(children: [
                    _ActionIcon(
                      iconKey: Key('post.like.${post.id}'),
                      icon: post.likedByMe ? Icons.favorite : Icons.favorite_border,
                      color: post.likedByMe ? const Color(0xFFFF2C55) : const Color(0xFF999999),
                      count: post.likeCount,
                      onTap: onToggleLike,
                    ),
                    const SizedBox(width: 24),
                    _ActionIcon(
                      icon: Icons.mode_comment_outlined,
                      color: const Color(0xFF999999),
                      count: post.commentCount,
                      onTap: onTap,
                    ),
                  ]),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
```

`isMine` 由调用方传入:`post.author.userId == ref.watch(profileProvider).value?.userId`(广场页/详情页/我的动态页统一这样算;我的动态页固定传 `true`)。

`_ActionIcon`(同文件私有组件):`InkWell(onTap: onTap, child: Row(children: [Icon(icon, size: 18, color: color), SizedBox(width: 4), Text('$count', style: TextStyle(fontSize: 13, color: color))]))`;count 为 0 时也可显示 0。

`app/lib/features/square/square_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../chat/widgets/photo_viewer.dart';
import '../profile/profile_controller.dart';
import 'models.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';

class SquarePage extends ConsumerStatefulWidget {
  const SquarePage({super.key});

  @override
  ConsumerState<SquarePage> createState() => _SquarePageState();
}

class _SquarePageState extends ConsumerState<SquarePage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        ref.read(squareProvider.notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _toggleLike(Post post) async {
    try {
      await ref.read(squareProvider.notifier).toggleLike(post);
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final posts = ref.watch(squareProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    return Scaffold(
      appBar: AppBar(title: const Text('广场')),
      backgroundColor: const Color(0xFFF7F3F5),
      floatingActionButton: FloatingActionButton(
        key: const Key('square.fab'),
        onPressed: () => context.push('/posts/compose'),
        child: const Icon(Icons.add),
      ),
      body: posts.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(error is ApiException ? error.message : '加载失败,请重试'),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: () => ref.invalidate(squareProvider),
              child: const Text('重试'),
            ),
          ]),
        ),
        data: (items) => items.isEmpty
            ? Center(
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const Text('还没有动态,发一条吧'),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: () => ref.invalidate(squareProvider),
                    child: const Text('刷新'),
                  ),
                ]),
              )
            : RefreshIndicator(
                onRefresh: () => ref.read(squareProvider.notifier).reload(),
                child: ListView.separated(
                  key: const Key('square.list'),
                  controller: _scroll,
                  itemCount: items.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final post = items[index];
                    return PostCard(
                      post: post,
                      isMine: post.author.userId == myId,
                      onToggleLike: () => _toggleLike(post),
                      onTap: () => context.push('/posts/${post.id}'),
                      onOpenImage: (i) =>
                          openPhotoViewer(context, urls: post.images, initialIndex: i),
                      // 删除/举报菜单在 Task 12 接入
                    );
                  },
                ),
              ),
      ),
    );
  }
}
```

`app/lib/features/shell/home_shell.dart` 改为 4 页 4 tab:

```dart
  static const _pages = [DiscoveryPage(), SquarePage(), ChatsPage(), MyProfilePage()];
  // destinations 中「发现」后插入:
  const NavigationDestination(icon: Icon(Icons.grid_view_outlined), label: '广场'),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/core/format_test.dart test/features/shell test/features/square && ../flutter/bin/flutter.bat analyze`
Expected: 全 PASS、analyze 零告警

- [ ] **Step 5: 提交**

```bash
git add app/lib app/test
git commit -m "feat(app): 广场 tab 与信息流页(卡片/九宫格/点赞乐观更新)"
```

---

### Task 10: 前端——发布页

**Files:**
- Create: `app/lib/features/square/post_compose_page.dart`、`app/test/features/square/post_compose_page_test.dart`
- Modify: `app/lib/core/image_pick.dart`、`app/lib/features/square/feed_repository.dart`、`app/lib/router.dart`

**Interfaces:**
- Consumes: `FeedRepository`(Task 9)、`squareProvider`(发布成功后 invalidate)。
- Produces: 路由 `/posts/compose`;`pickImagesFromGallery({int limit}) -> Future<List<XFile>>`;`FeedRepository.createPost({required String text, required List<({Uint8List bytes, String name})> images})`。

- [ ] **Step 1: 写失败的测试**

`app/test/features/square/post_compose_page_test.dart`:

```dart
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';

import 'package:chatapp_app/features/square/post_compose_page.dart';

import '../../support/scripted_adapter.dart';

// 直接 pump 单页(避开全 App 路由),相册用注入的假实现。
void main() {
  testWidgets('空内容发布按钮置灰;输入后可发', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /posts': (options) => ok(postJson(id: 1, text: '你好'), status: 201),
    });
    await pumpCompose(tester, adapter, pickImages: () async => const []);

    final button = find.byKey(const Key('compose.submit'));
    expect(tester.widget<FilledButton>(button).onPressed, isNull);   // 置灰

    await tester.enterText(find.byKey(const Key('compose.text')), '你好');
    await tester.pump();
    expect(tester.widget<FilledButton>(button).onPressed, isNotNull);
  });

  testWidgets('选图后发布带 multipart', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /posts': (options) => ok(postJson(id: 1, text: '', images: ['http://t/a.png']), status: 201),
    });
    await pumpCompose(tester, adapter, pickImages: () async => [
      XFile.fromData(Uint8List.fromList(List.filled(10, 1)), name: 'a.png'),
    ]);

    await tester.tap(find.byKey(const Key('compose.add')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('compose.picked.0')), findsOneWidget);

    await tester.tap(find.byKey(const Key('compose.submit')));
    await tester.pumpAndSettle();
    expect(adapter.log.where((r) => r.path == '/posts'), hasLength(1));
  });
}
```

`pumpCompose` helper(同文件)按 `photo_grid_test.dart` 的模式搭 ProviderScope + MaterialApp,注入 `PostComposePage(pickImages: ...)`;`postJson` 从 `../../support/sample_data.dart` 引入。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/square/post_compose_page_test.dart`
Expected: FAIL(文件不存在)

- [ ] **Step 3: 实现**

`app/lib/core/image_pick.dart` 追加:

```dart
typedef PickImages = Future<List<XFile>> Function();

/// 相册多选(发布动态用);部分平台不支持 limit,前端再做一次截断。
Future<List<XFile>> pickImagesFromGallery({int limit = 9}) =>
    ImagePicker().pickMultiImage(maxWidth: 1080, imageQuality: 85, limit: limit);
```

`app/lib/features/square/feed_repository.dart` 追加:

```dart
  Future<Post> createPost({
    required String text,
    required List<({Uint8List bytes, String name})> images,
  }) async {
    final data = await _api.post('/posts', data: FormData.fromMap({
      'text': text,
      'images': [
        for (final image in images)
          MultipartFile.fromBytes(image.bytes, filename: image.name),
      ],
    }));
    return Post.fromJson(data as Map<String, dynamic>);
  }
```

(顶部 import 需补 `package:dio/dio.dart` 与 `dart:typed_data`。)

`app/lib/features/square/post_compose_page.dart`:

```dart
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/api_exception.dart';
import '../../core/image_pick.dart';
import 'feed_repository.dart';
import 'square_controller.dart';

const _maxBytes = 5 * 1024 * 1024;
const _maxCount = 9;

typedef _Picked = ({Uint8List bytes, String name});

/// 发布动态:文字(≤500)+ 九宫格选图(≤9);两者至少其一。
class PostComposePage extends ConsumerStatefulWidget {
  const PostComposePage({super.key, this.pickImages = pickImagesFromGallery});

  final PickImages pickImages;

  @override
  ConsumerState<PostComposePage> createState() => _PostComposePageState();
}

class _PostComposePageState extends ConsumerState<PostComposePage> {
  final _text = TextEditingController();
  final _images = <_Picked>[];
  bool _submitting = false;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _pick() async {
    final files = await widget.pickImages();
    if (!mounted || files.isEmpty) return;
    for (final file in files) {
      if (_images.length >= _maxCount) {
        _show('最多 9 张图片');
        break;
      }
      final bytes = await file.readAsBytes();
      if (bytes.length > _maxBytes) {
        _show('单张图片不能超过 5MB');
        continue;
      }
      _images.add((bytes: bytes, name: file.name));
    }
    setState(() {});
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    try {
      await ref.read(feedRepositoryProvider).createPost(
          text: _text.text.trim(), images: List.of(_images));
      ref.invalidate(squareProvider);
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final canSubmit = !_submitting && (_text.text.trim().isNotEmpty || _images.isNotEmpty);
    return Scaffold(
      appBar: AppBar(
        title: const Text('发布动态'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: FilledButton(
              key: const Key('compose.submit'),
              onPressed: canSubmit ? _submit : null,
              child: const Text('发布'),
            ),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            key: const Key('compose.text'),
            controller: _text,
            maxLength: 500,
            maxLines: 6,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              hintText: '分享新鲜事…',
              border: InputBorder.none,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (var i = 0; i < _images.length; i++)
                _PickedTile(
                  key: Key('compose.picked.$i'),
                  bytes: _images[i].bytes,
                  onRemove: () => setState(() => _images.removeAt(i)),
                ),
              if (_images.length < _maxCount)
                InkWell(
                  key: const Key('compose.add'),
                  onTap: _pick,
                  child: Container(
                    width: 88, height: 88,
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.black26),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Icon(Icons.add_a_photo_outlined),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PickedTile extends StatelessWidget {
  const _PickedTile({super.key, required this.bytes, required this.onRemove});

  final Uint8List bytes;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 88, height: 88,
        child: Stack(fit: StackFit.expand, children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: Image.memory(bytes, fit: BoxFit.cover,
                errorBuilder: (c, e, s) => Container(color: Colors.black12)),
          ),
          Positioned(
            right: 0, top: 0,
            child: IconButton(
              onPressed: onRemove, iconSize: 18,
              icon: const CircleAvatar(radius: 11, child: Icon(Icons.close, size: 14)),
            ),
          ),
        ]),
      );
}
```

`app/lib/router.dart` 加路由(import `features/square/post_compose_page.dart`):

```dart
      GoRoute(path: '/posts/compose', builder: (context, state) => const PostComposePage()),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/square && ../flutter/bin/flutter.bat analyze`
Expected: PASS、零告警

- [ ] **Step 5: 提交**

```bash
git add app/lib app/test
git commit -m "feat(app): 发布动态页(多图九宫格 + multipart 一次提交)"
```

---

### Task 11: 前端——详情页(评论)

**Files:**
- Create: `app/lib/features/square/post_detail_controller.dart`、`app/lib/features/square/post_detail_page.dart`、`app/test/features/square/post_detail_page_test.dart`
- Modify: `app/lib/features/square/feed_repository.dart`、`app/lib/router.dart`

**Interfaces:**
- Consumes: `Post`/`PostCommentItem` 模型、`FeedRepository`、`PostCard`/`PostImages`。
- Produces:
  - `feed_repository.dart`:`fetchPost(int id) -> Future<Post>`、`fetchComments(int postId, {limit, offset}) -> Future<({List<PostCommentItem> items, bool hasMore})>`、`addComment(int postId, String text) -> Future<void>`、`deletePost(int id) -> Future<void>`、`reportPost(int postId, {required String type, String detail}) -> Future<void>`(后两个 Task 12 用,本任务一并写进 repository)
  - `post_detail_controller.dart`:`postDetailProvider`(family, autoDispose, `Future<Post>`)、`commentsProvider`(family, autoDispose, `Future<List<PostCommentItem>>`,方法 `loadMore()`、`send(String text)`)——为简单起见:commentsProvider 返回全量已加载列表并支持 `loadMore`;发送新评论后 `ref.invalidateSelf`。
  - 路由 `/posts/:id`。

- [ ] **Step 1: 写失败的测试**

`app/test/features/square/post_detail_page_test.dart`(要点,helper 模式同 compose 测试):

```dart
  testWidgets('渲染动态与评论,发送后清空并刷新', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/1': (options) => ok(postJson(id: 1, nickname: 'Alice', text: '正文', commentCount: 1)),
      'GET /posts/1/comments': (options) => ok(postsPageJson([
            commentJson(id: 5, nickname: 'Bob', text: '好漂亮'),
          ])),
      'POST /posts/1/comments': (options) => ok(commentJson(id: 6, nickname: '我', text: '谢谢'), status: 201),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    expect(find.text('正文'), findsOneWidget);
    expect(find.text('好漂亮'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('post.comment.input')), '谢谢');
    await tester.tap(find.byKey(const Key('post.comment.send')));
    await tester.pumpAndSettle();
    expect(adapter.log.where((r) => r.method == 'POST' && r.path == '/posts/1/comments'), hasLength(1));
    expect(tester.widget<TextField>(find.byKey(const Key('post.comment.input'))).controller!.text, '');
  });

  testWidgets('动态不存在 → 显示错误态', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/404': (options) => jsonError(404, '动态不存在'),
    });
    await pumpDetail(tester, adapter, postId: 404);
    await tester.pumpAndSettle();
    expect(find.text('动态不存在'), findsOneWidget);
  });
```

`sample_data.dart` 加:

```dart
Map<String, dynamic> commentJson({
  int id = 1, int authorId = 9, String nickname = 'Bob', String text = '评论',
  String createdAt = '2026-09-12T20:00:00+08:00',
}) => {
      'id': id,
      'author': {'user_id': authorId, 'nickname': nickname, 'avatar_url': null},
      'text': text,
      'created_at': createdAt,
    };
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/square/post_detail_page_test.dart`
Expected: FAIL(文件不存在)

- [ ] **Step 3: 实现**

`feed_repository.dart` 追加:

```dart
  Future<Post> fetchPost(int id) async =>
      Post.fromJson(await _api.get('/posts/$id') as Map<String, dynamic>);

  Future<({List<PostCommentItem> items, bool hasMore})> fetchComments(
      int postId, {int limit = 100, int offset = 0}) async {
    final page = await _api.get('/posts/$postId/comments',
        query: {'limit': limit, 'offset': offset}) as Map<String, dynamic>;
    final items = (page['results'] as List<dynamic>)
        .map((item) => PostCommentItem.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, hasMore: page['next'] != null);
  }

  Future<void> addComment(int postId, String text) async {
    await _api.post('/posts/$postId/comments', data: {'text': text});
  }

  Future<void> deletePost(int id) async {
    await _api.delete('/posts/$id');
  }

  Future<void> reportPost(int postId, {required String type, String detail = ''}) async {
    await _api.post('/posts/$postId/report', data: {'type': type, 'detail': detail});
  }
```

`post_detail_controller.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'feed_repository.dart';
import 'models.dart';

class PostDetailController extends AsyncNotifier<Post> {
  PostDetailController(this.postId);

  final int postId;

  @override
  Future<Post> build() => ref.read(feedRepositoryProvider).fetchPost(postId);

  Future<void> toggleLike() async {
    final post = state.value;
    if (post == null) return;
    final target = !post.likedByMe;
    state = AsyncValue.data(post.copyWith(
        likedByMe: target, likeCount: post.likeCount + (target ? 1 : -1)));
    try {
      await ref.read(feedRepositoryProvider).toggleLike(post.id, like: target);
    } catch (_) {
      state = AsyncValue.data(post);
      rethrow;
    }
  }
}

final postDetailProvider = AsyncNotifierProvider.autoDispose
    .family<PostDetailController, Post, int>(PostDetailController.new,
        retry: (retryCount, error) => null);

class CommentsController extends AsyncNotifier<List<PostCommentItem>> {
  CommentsController(this.postId);

  final int postId;

  @override
  Future<List<PostCommentItem>> build() async =>
      (await ref.read(feedRepositoryProvider).fetchComments(postId)).items;

  Future<void> send(String text) async {
    await ref.read(feedRepositoryProvider).addComment(postId, text);
  }
}

final commentsProvider = AsyncNotifierProvider.autoDispose
    .family<CommentsController, List<PostCommentItem>, int>(CommentsController.new,
        retry: (retryCount, error) => null);
```

(family 参数照 `chat_controller.dart` 的模式:**构造器注入**(`PostDetailController(this.postId)`)+ `AsyncNotifierProvider.autoDispose.family<C, S, P>(C.new)`;发送评论后由页面 `ref.invalidate(commentsProvider(postId))` 刷新,不在 controller 内自 invalidate。)

`post_detail_page.dart`(结构与要点):

```dart
class PostDetailPage extends ConsumerStatefulWidget {
  const PostDetailPage({super.key, required this.postId});
  final int postId;
  ...
}

class _PostDetailPageState extends ConsumerState<PostDetailPage> {
  final _input = TextEditingController();
  bool _sending = false;

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    setState(() => _sending = true);
    try {
      await ref.read(commentsProvider(widget.postId).notifier).send(text);
      _input.clear();
      ref.invalidate(commentsProvider(widget.postId));      // 评论列表刷新
      ref.invalidate(postDetailProvider(widget.postId));    // 评论数 +1
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final post = ref.watch(postDetailProvider(widget.postId));
    final comments = ref.watch(commentsProvider(widget.postId));
    return Scaffold(
      appBar: AppBar(title: const Text('动态详情')),
      body: Column(children: [
        Expanded(
          child: post.when(
            loading: ..., error: (e, _) => Center(child: Text(e is ApiException ? e.message : '加载失败')), 
            data: (data) => ListView(children: [
              PostCard(
                post: data,
                isMine: ref.watch(profileProvider).value?.userId == data.author.userId,
                onToggleLike: () => ref.read(postDetailProvider(widget.postId).notifier).toggleLike(),
                onOpenImage: (i) => openPhotoViewer(context, urls: data.images, initialIndex: i),
                menuAction: ...,   // Task 12 接入删除/举报
              ),
              const Divider(height: 1),
              comments.when(
                loading: ..., error: ...,
                data: (items) => Column(children: [
                  for (final comment in items) _CommentTile(comment),
                  if (items.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Text('还没有评论')),
                ]),
              ),
            ]),
          ),
        ),
        SafeArea(child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
          child: Row(children: [
            Expanded(child: TextField(
              key: const Key('post.comment.input'),
              controller: _input,
              maxLength: 200,
              decoration: const InputDecoration(hintText: '说点什么…', counterText: ''),
              onSubmitted: (_) => _send(),
            )),
            IconButton(
              key: const Key('post.comment.send'),
              onPressed: _sending ? null : _send,
              icon: const Icon(Icons.send),
            ),
          ]),
        )),
      ]),
    );
  }
}
```

`_CommentTile`:行内小头像(28)+ 昵称(灰、小)+ 内容 + `formatPostTime` 时间;key `Key('post.comment.$id')`。

`router.dart` 加:

```dart
      GoRoute(
        path: '/posts/:id',
        builder: (context, state) =>
            PostDetailPage(postId: int.parse(state.pathParameters['id']!)),
      ),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/square && ../flutter/bin/flutter.bat analyze`
Expected: PASS、零告警

- [ ] **Step 5: 提交**

```bash
git add app/lib app/test
git commit -m "feat(app): 动态详情页(评论列表与发送)"
```

---

### Task 12: 前端——···菜单(删除/举报)+ 我的动态页 + 灰条映射

**Files:**
- Create: `app/lib/features/square/my_posts_page.dart`、`app/test/features/square/my_posts_page_test.dart`
- Modify: `app/lib/features/square/square_controller.dart`(加 `myPostsProvider`)、`app/lib/features/square/square_page.dart`(接菜单)、`app/lib/features/square/post_detail_page.dart`(接菜单)、`app/lib/features/profile/my_profile_page.dart`(入口行)、`app/lib/features/square/feed_repository.dart`(已完成)、`app/lib/router.dart`(`/my-posts`)、`app/lib/im/tencent_im_client.dart`(灰条白名单)、`app/test/im/tencent_im_client_test.dart`、`app/test/features/profile/my_profile_page_test.dart`(入口断言)

**Interfaces:**
- Consumes: `ReportSheet`(`features/moderation/widgets/report_sheet.dart`,`showModalBottomSheet` pop 出 `({String type, String detail})`)、`feed_repository.reportPost/deletePost`、`squareProvider.toggleLike` 同型。
- Produces: `myPostsProvider`(autoDispose,`List<Post>`,`reload()`);`/my-posts` 路由;菜单动作接线(删除带确认框、举报弹 ReportSheet + SnackBar「已收到举报,我们会尽快处理」);`_kindOf` 白名单加 `post_commented`。

- [ ] **Step 1: 写失败的测试**

`app/test/features/square/my_posts_page_test.dart`:

```dart
// 从「我的」页点「我的动态」→ /my-posts 渲染自己的动态;删除后消失。
  testWidgets('我的动态列表与删除', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': ...,
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts/mine': (options) => ok(postsPageJson([postJson(id: 7, authorId: 7, nickname: '小明', text: '我发的')])),
      'DELETE /posts/7': (options) => ok({}, status: 204),
      'GET /posts': (options) => ok(postsPageJson([])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.posts')));
    await tester.pumpAndSettle();
    expect(find.text('我发的'), findsOneWidget);

    await tester.tap(find.byKey(const Key('post.more.7')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.menu.delete')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));   // 确认框
    await tester.pumpAndSettle();
    expect(adapter.log.where((r) => r.method == 'DELETE' && r.path == '/posts/7'), hasLength(1));
    expect(find.text('我发的'), findsNothing);
  });
```

(删除确认框的按钮文案与 key 以落地实现为准,测试同步——建议确认按钮加 `Key('post.delete.confirm')` 便于断言。)

`app/test/features/square/square_page_test.dart` 追加:

```dart
  testWidgets('别人的动态菜单是举报,提交后提示', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': ...,
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(postsPageJson([postJson(id: 2, authorId: 9, nickname: 'Alice', text: '别人的')])),
      'POST /posts/2/report': (options) => ok({'id': 1, 'status': 'pending'}, status: 201),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.more.2')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.menu.report')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('report.type.porn')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('report.submit')));
    await tester.pumpAndSettle();
    expect(find.text('已收到举报,我们会尽快处理'), findsOneWidget);
  });
```

`app/test/im/tencent_im_client_test.dart` 追加(参照该文件现有的 ban_notice 映射用例):

```dart
  test('post_commented 映射为灰条 banNotice', () {
    // 构造与现有 report_handled 用例同款 custom 消息,断言 _kindOf → ChatMessageKind.banNotice
  });
```

(该文件已有 `report_handled`/`ban_notice` 的同款断言用例,复制其中最新一条改写 type 即可。)

`app/test/features/profile/my_profile_page_test.dart` 追加断言「我的动态」行存在(key `my.row.posts`)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/square test/im/tencent_im_client_test.dart test/features/profile/my_profile_page_test.dart`
Expected: FAIL(菜单 key 不存在/行不存在/映射未加)

- [ ] **Step 3: 实现**

`square_controller.dart` 追加:

```dart
final myPostsProvider = AsyncNotifierProvider.autoDispose<MyPostsController, List<Post>>(
  MyPostsController.new,
  retry: (retryCount, error) => null,
);

class MyPostsController extends AsyncNotifier<List<Post>> {
  bool _hasMore = true;

  @override
  Future<List<Post>> build() async {
    final page = await ref.read(feedRepositoryProvider).fetchPosts(path: '/posts/mine');
    _hasMore = page.hasMore;
    return page.items;
  }

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(build);
  }

  Future<void> remove(int postId) async {
    await ref.read(feedRepositoryProvider).deletePost(postId);
    final current = state.value ?? const <Post>[];
    state = AsyncValue.data(current.where((post) => post.id != postId).toList());
  }
}
```

`square_page.dart`:`PostCard` 传 `menuAction`:

```dart
                      menuAction: (action) => action == 'delete'
                          ? _deletePost(post)
                          : _reportPost(post),
```

两个方法(页面内):

```dart
  Future<void> _deletePost(Post post) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这条动态?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(
            key: const Key('post.delete.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(feedRepositoryProvider).deletePost(post.id);
      await ref.read(squareProvider.notifier).reload();
      if (mounted) _show('已删除');
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    }
  }

  Future<void> _reportPost(Post post) async {
    final result = await showModalBottomSheet<({String type, String detail})>(
      context: context,
      isScrollControlled: true,
      builder: (context) => const ReportSheet(),
    );
    if (result == null) return;
    try {
      await ref.read(feedRepositoryProvider)
          .reportPost(post.id, type: result.type, detail: result.detail);
      if (mounted) _show('已收到举报,我们会尽快处理');
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    }
  }
```

`_show` 为页面私有 SnackBar 帮助(同 Task 9 的写法)。

`post_detail_page.dart`:同样接 `menuAction`;删除成功后 `context.pop()`;举报逻辑同广场页(可抽为 `showReportSheet(context, ref, postId)` 帮助函数放在 square 目录内共享:`app/lib/features/square/report_actions.dart`——放一个 `Future<void> reportPostFromSheet(BuildContext, WidgetRef, int postId)`)。

`my_posts_page.dart`:

```dart
class MyPostsPage extends ConsumerWidget {
  const MyPostsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final posts = ref.watch(myPostsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('我的动态')),
      backgroundColor: const Color(0xFFF7F3F5),
      body: posts.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(child: Text(error is ApiException ? error.message : '加载失败')),
        data: (items) => items.isEmpty
            ? const Center(child: Text('还没发过动态'))
            : ListView.separated(
                itemCount: items.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (context, index) {
                  final post = items[index];
                  return PostCard(
                    post: post,
                    isMine: true,
                    onTap: () => context.push('/posts/${post.id}'),
                    onOpenImage: (i) => openPhotoViewer(context, urls: post.images, initialIndex: i),
                    menuAction: (action) => ...同上(删除/举报),
                  );
                },
              ),
      ),
    );
  }
}
```

`my_profile_page.dart` 第二组 `_Group` 的「设置」行上方插入:

```dart
              _InfoRow(
                rowKey: 'my.row.posts',
                label: '我的动态',
                onTap: () => context.push('/my-posts'),
              ),
```

`router.dart` 加:

```dart
      GoRoute(path: '/my-posts', builder: (context, state) => const MyPostsPage()),
```

`tencent_im_client.dart` 的 `_kindOf` 白名单改:

```dart
    if (type == 'ban_notice' || type == 'ban_lifted' || type == 'report_handled'
        || type == 'post_commented') {
      return ChatMessageKind.banNotice;
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze`
Expected: 全 PASS、零告警

- [ ] **Step 5: 提交**

```bash
git add app/lib app/test
git commit -m "feat(app): 动态 ··· 菜单(删除/举报)+ 我的动态页 + 评论通知灰条"
```

---

### Task 13: 收尾——CLAUDE.md 更新 + 双端全量回归

**Files:**
- Modify: `CLAUDE.md`(顶部进度段 + 新增「广场页」小节)、`docs/superpowers/plans/2026-09-12-square-feed.md`(勾选)

**Interfaces:**
- Consumes: 前 12 个任务全部产出。

- [ ] **Step 1: 后端全量回归**

Run: `cd chatapp && python manage.py test`
Expected: 全绿(基线 256 + 本次新增 ≈27~32)

- [ ] **Step 2: 前端全量回归**

Run: `cd app && ../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze`
Expected: 全绿(基线 157 + 本次新增 ≈12~15)、analyze 零告警

- [ ] **Step 3: 更新 CLAUDE.md**

- 顶部进度段加「**六追加:广场页(动态流)**」:一句话范围 + 后端/前端测试数 + spec/plan 文件名。
- 常用命令区不动;「合规与审核」或新起「广场页(动态流)」小节,记录:
  - 接口清单与限流额度(post_create 20/day、post_comment 60/day、post_report 20/day)
  - 删除动态的服务收口(`feed.services.delete_post`:先关举报再删,作者自删与 ops 共用)
  - 举报留档(SET_NULL,动态删除后 post 置空)
  - 评论通知任务 `im.tasks.post_commented`(文案模板在 `im/client.py`)
  - 前端:`features/square/`,测试注图模式(`PostComposePage(pickImages:)` / `PostGrid` 注入同款)
- 手测提醒:`/ops/` 新增「动态管理」「动态举报」两个菜单;worker 改了 `im/tasks.py` 要重启。

- [ ] **Step 4: 勾选本计划全部 checkbox 并提交**

```bash
git add CLAUDE.md docs/superpowers/plans/2026-09-12-square-feed.md
git commit -m "docs: 广场页交付记录(CLAUDE.md + 计划勾选)"
```

- [ ] **Step 5: 手测清单(交给用户,双模拟器 + /ops/)**

1. 两台模拟器分别登录两个账号;A 发文字 + 多图动态 → B 在广场可见。
2. B 点赞(A 无通知)、B 评论 → A 消息页「系统通知」出现「B 评论了你的动态:…」灰条。
3. 图片点开全屏、左右切换、缩放;退出发布页图片被移除。
4. A 在广场/我的动态删除自己的动态(B 端刷新后消失;B 打开详情 404)。
5. B 举报 A 的动态 → /ops/「动态举报」队列可见 → 「删除动态」→ B 收到「举报已处理」系统通知;再测「忽略」路径(B 也收到通知、动态保留)。
6. 双向拉黑后互相看不到动态;重封禁账号的动态从广场隐藏(轻封禁照常)。
7. /ops/「动态管理」列表可见全部动态并删除。
8. 敏感词发动态/评论被 400 拒;连发触发 429。

---

## Self-Review 记录

- **Spec 覆盖**:§2 五表→T1;§3 接口→T2(发布)T3(流/详情/mine)T4(删除)T5(赞/评论)T6(举报);§4 规则→T2(校验/限流)T3(过滤)T4(删除收口)T5(通知);§5 前端→T9~T12;§6 ops→T7/T8;§7 测试→各任务内;§8 决策→已落实在各项。
- **类型一致性**:`visible_posts`/`delete_post`/`notify_post_commented`/`send_post_commented`/`post_commented`/`PostCreateThrottle`/`PostCommentThrottle`/`PostReportThrottle`、前端 `squareProvider`/`myPostsProvider`/`postDetailProvider`/`commentsProvider`/`formatPostTime`/`pickImagesFromGallery`/`fetchPosts`/`createPost`/`deletePost`/`reportPost`/`addComment`/`fetchComments` 在各任务引用一致。
- **未决提醒**(实施时以实际代码为准,不要臆造):`im/tests.py` 现有 mock 风格(参考 `send_report_handled` 用例);测试图片来源用 `users/tests.py::PNG_1PX`;`User.im_user_id` 断言用实例属性不写死;T11 详情页片段里 `menuAction: ...` 与 `_CommentTile` 的完整实现按 T12 与现有代码风格补全。
