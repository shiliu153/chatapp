# 广场评论楼中楼与回复提醒 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把广场评论从单层列表改成两级楼中楼,回复某人时通过 IM 灰条提醒对方,并允许作者删除自己的评论。

**Architecture:** `PostComment` 自引用 `parent` + `reply_to` 两列,服务层把"回复的回复"归一到顶级评论(数据库永远只有两层)。列表接口内嵌前 2 条回复,展开走独立分页接口;提醒复用 `im/tasks.py` 的灰条通道,顶级评论与回复各走一个任务。

**Tech Stack:** Django 5.2 + DRF / Flutter 3.47 (Riverpod + go_router) / Vue 3 + TypeScript + Vitest / MySQL 8 + Redis。

## Global Constraints

- 接口总数:**36 → 38**(`docs/api/README.md` 的计数与表格必须同步;`ApiDocsCoverageTests` 双向比对)。
- 评论正文上限 **200 字**,违禁词检查沿用 `moderation.text_check.find_blocked_word`。
- 发评论限流沿用 `post_comment` = **60/day**(回复同额度,不新增 scope)。
- 所有新增/修改的 `.py` 必须补模块与函数/类 docstring,公开函数带参数必须写 `Args:`(`CommentCoverageTests` 门禁)。
- 响应路径禁止第三方网络调用;IM 副作用一律走 `im/tasks.py` + `transaction.on_commit(..., robust=True)`。
- IM 客户端对外永不抛异常;任务参数一律传主键/用户 id,任务内查库。
- App 端禁止裸 hex / 裸字号 / 裸间距,一律用 `app/lib/core/theme/*` 的 token;图标用 `*_rounded`。
- Web 端禁止裸色值,一律用 `web/src/styles/tokens.css` 的 CSS 变量。
- 测试命令(cwd 见各任务);本机 Redis 映射在 **16379**,后端测试统一先设 `$env:TEST_REDIS_PORT="16379"`。
- 每步全绿再进下一步;提交信息用项目既有前缀(`feat(feed):` / `test(feed):` / `docs(api):` / `feat(app/square):` / `feat(web/square):`)。

## 文件结构

**后端**

| 文件 | 责任 |
|---|---|
| `chatapp/feed/models.py` | `PostComment` 加 `parent` / `reply_to` + 自引用 CheckConstraint |
| `chatapp/feed/migrations/0002_*.py` | 上述两列与约束(自动生成) |
| `chatapp/feed/services.py` | `visible_comments` / `create_comment` / `delete_comment` / `notify_comment_created` |
| `chatapp/feed/serializers.py` | 评论对象新字段;创建入参加 `parent_id` |
| `chatapp/feed/views.py` | 列表改顶级 + 内嵌;新增回复列表、删除评论 |
| `chatapp/feed/urls.py` | 两条新路由 |
| `chatapp/im/client.py` | `POST_REPLIED_TEMPLATE` + `send_post_replied` |
| `chatapp/im/tasks.py` | `post_replied` 任务 |
| `chatapp/feed/tests.py` | 楼中楼测试集 |

**App**

| 文件 | 责任 |
|---|---|
| `app/lib/features/square/models.dart` | `PostCommentItem` 新字段与嵌套解析 |
| `app/lib/features/square/feed_repository.dart` | `addComment(parentId)` / `fetchReplies` / `deleteComment` |
| `app/lib/features/square/post_detail_controller.dart` | `send(parentId)` + `RepliesController` |
| `app/lib/features/square/widgets/comment_thread.dart` | **新建**:楼层渲染、展开回复、回复/删除入口 |
| `app/lib/features/square/post_detail_page.dart` | 接入 `CommentThread`;输入栏回复态;删除处理 |
| `app/test/features/square/post_detail_page_test.dart` | 楼层与回复态用例 |
| `app/test/support/sample_data.dart` | `commentJson` 支持新字段 |

**Web**

| 文件 | 责任 |
|---|---|
| `web/src/api/types.ts` | `Comment` 新字段 |
| `web/src/api/feed.ts` | `createComment(parentId)` / `fetchReplies` / `deleteComment` |
| `web/src/features/square/CommentList.vue` | 两层渲染、展开、回复态、删除 |
| `web/src/features/square/PostDetailPage.vue` | 计数增减 |
| `web/tests/component/comment-list.spec.ts` | **新建**:组件用例 |
| `web/tests/component/post-detail-page.spec.ts` | 更新评论夹具 |

**文档**:`docs/api/feed.md`(5.8/5.9 改 + 5.11/5.12 新增)、`docs/api/README.md`(计数与表格)、`CLAUDE.md` / `README.md`(收尾回填)。

---

### Task 1: 模型两列 + 自引用约束

**Files:**
- Modify: `chatapp/feed/models.py`
- Create: `chatapp/feed/migrations/0002_postcomment_parent_reply_to.py`(由 `makemigrations` 生成)
- Test: `chatapp/feed/tests.py`

**Interfaces:**
- Consumes: 无
- Produces: `PostComment.parent`(FK self, null)、`PostComment.reply_to`(FK User, null)、约束名 `post_comment_not_self_parent`

- [ ] **Step 1: 写失败的模型测试**

在 `chatapp/feed/tests.py` 的 `FeedModelTests` 里追加:

```python
    def test_comment_cannot_be_own_parent(self):
        post = Post.objects.create(author=self.a, text="你好")
        comment = PostComment.objects.create(post=post, author=self.a, text="一")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PostComment.objects.filter(pk=comment.pk).update(parent_id=comment.pk)

    def test_reply_defaults(self):
        post = Post.objects.create(author=self.a, text="你好")
        root = PostComment.objects.create(post=post, author=self.a, text="楼")
        reply = PostComment.objects.create(post=post, author=self.b, text="回",
                                           parent=root, reply_to=self.a)
        self.assertEqual(reply.parent, root)
        self.assertEqual(reply.reply_to, self.a)
        self.assertEqual(list(root.replies.all()), [reply])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed.tests.FeedModelTests -v 2
```

Expected: FAIL —— `TypeError: PostComment() got unexpected keyword arguments: 'parent'`

- [ ] **Step 3: 改模型**

`chatapp/feed/models.py` 顶部导入改为:

```python
from django.conf import settings
from django.db import models
from django.db.models import F, Q
```

`PostComment` 整段替换为:

```python
class PostComment(models.Model):
    """一条动态评论;``parent`` 非空表示它是某条顶级评论下的回复。

    层级恒为两级:回复的回复由 ``services.create_comment`` 归一到顶级评论,
    ``parent`` 永远指向顶级评论;``reply_to`` 记录"回复的是谁",用于渲染
    「回复 @昵称」与发送提醒。
    """

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="post_comments")
    parent = models.ForeignKey("self", null=True, blank=True,
                               on_delete=models.CASCADE, related_name="replies")
    reply_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name="comment_replies_received")
    text = models.CharField("内容", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=~Q(id=F("parent_id")),
                                   name="post_comment_not_self_parent"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``post_comment#主键(post=动态 id)``。
        """
        return f"post_comment#{self.pk}(post={self.post_id})"
```

- [ ] **Step 4: 生成迁移并跑测试**

```bash
cd chatapp
python manage.py makemigrations feed
$env:TEST_REDIS_PORT="16379"
python manage.py test feed.tests.FeedModelTests -v 2
```

Expected: `feed/migrations/0002_postcomment_parent_reply_to.py` 生成(只含 `parent`、`reply_to` 与 `AddConstraint`);测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add chatapp/feed/models.py chatapp/feed/migrations/0002_postcomment_parent_reply_to.py chatapp/feed/tests.py
git commit -m "feat(feed): PostComment 增加 parent/reply_to 两列与自引用约束"
```

---

### Task 2: 发表评论支持 `parent_id`(归一化)

**Files:**
- Modify: `chatapp/feed/services.py`、`chatapp/feed/serializers.py`、`chatapp/feed/views.py`
- Test: `chatapp/feed/tests.py`

**Interfaces:**
- Consumes: Task 1 的两列
- Produces:
  - `visible_comments(post, viewer) -> QuerySet[PostComment]`(已过滤 + `select_related("author__profile", "reply_to__profile")` + `prefetch_related("author__photos")`)
  - `create_comment(post, author, text, parent=None) -> PostComment`
  - `PostCommentCreateSerializer.validated_data["parent_id"]: int | None`

- [ ] **Step 1: 写失败的接口测试**

在 `chatapp/feed/tests.py` 末尾追加:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed.tests.PostCommentThreadTests -v 2
```

Expected: FAIL —— 201 响应里没有 `parent_id` 字段(或回复被当成顶级评论)。

- [ ] **Step 3: 服务层加可见性与创建**

`chatapp/feed/services.py` 追加(保留原有 `visible_posts` / `delete_post`):

```python
def visible_comments(post, viewer):
    """某条动态下对 ``viewer`` 可见的评论与回复,按时间正序。

    Args:
        post: 目标动态。
        viewer: 当前浏览者。

    Returns:
        排除双向拉黑与重封禁作者后的评论查询集;作者与被回复者已预取。
    """
    blocked = blocked_user_ids(viewer)
    return (post.comments
            .exclude(author_id__in=blocked)
            .exclude(author__profile__status=ProfileStatus.BANNED_HEAVY)
            .select_related("author__profile", "reply_to__profile")
            .prefetch_related("author__photos"))


def create_comment(post, author, text, parent=None):
    """创建评论或回复,并把层级归一到两级。

    Args:
        post: 被评论的动态。
        author: 评论者。
        text: 已通过校验的正文。
        parent: 被回复的评论(调用方已确认它属于 ``post``);``None`` 表示顶级评论。

    Returns:
        新建的 ``PostComment``;回复的 ``parent`` 一定是顶级评论,
        ``reply_to`` 是真正被回复的那个人。
    """
    if parent is None:
        return PostComment.objects.create(post=post, author=author, text=text)
    root = parent.parent or parent
    return PostComment.objects.create(post=post, author=author, text=text,
                                      parent=root, reply_to=parent.author)
```

`PostComment` 已在文件顶部导入(`from .models import Post, PostLike, PostReport` 那行)——
把它改成 `from .models import Post, PostComment, PostLike, PostReport`。

同时把现有的 `notify_post_commented` **改名**为 `notify_comment_created`(函数体先保持不变,
Task 6 再改成分流),这样 Task 2 的视图可以立刻引用新名字:

```python
def notify_comment_created(comment) -> None:
    """评论创建后调用:给动态作者发通知(经任务队列)。

    评论者是作者本人时不入队(自己评自己不打扰)。

    Args:
        comment: 刚创建的评论。
    """
    if comment.post.author_id == comment.author_id:
        return
    transaction.on_commit(lambda: im_tasks.post_commented.delay(comment.id), robust=True)
```

- [ ] **Step 4: 序列化器加 `parent_id` 入参与新字段骨架**

`chatapp/feed/serializers.py`:

```python
class PostCommentCreateSerializer(serializers.Serializer):
    """发表评论的入参;``parent_id`` 非空表示这是一条回复。"""

    text = serializers.CharField(max_length=200)
    parent_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_text(self, value):
        """校验评论内容:违禁词检查、去空白、非空。

        Args:
            value: 提交的评论内容。

        Returns:
            去空白后的评论内容。

        Raises:
            serializers.ValidationError: 命中违禁词,或去空白后为空。
        """
        if find_blocked_word(value):
            raise serializers.ValidationError("评论包含违规内容,请修改")
        text = value.strip()
        if not text:
            raise serializers.ValidationError("评论不能为空")
        return text
```

`PostCommentSerializer` 的 `fields` 先加上 `"parent_id"`,并声明:

```python
    parent_id = serializers.IntegerField(read_only=True, allow_null=True)
```

(`reply_to` / `reply_count` / `replies` 在 Task 3 一次补齐。)

- [ ] **Step 5: 视图 POST 分支接服务层**

`chatapp/feed/views.py` 的 `post_comments` 改为:

```python
@api_view(["GET", "POST"])
@throttle_classes([PostCommentThrottle])
def post_comments(request, post_id):
    """评论列表与发表评论(GET/POST /api/v1/posts/{post_id}/comments)。

    GET 只返回顶级评论(内嵌前两条回复);POST 可带 ``parent_id`` 发表回复,
    层级由 ``services.create_comment`` 归一为两级,提醒在事务提交后入队。

    Args:
        request: DRF 请求对象;POST 时 body 需带 ``text``,可选 ``parent_id``。
        post_id: 动态主键。

    Returns:
        GET 返回分页后的顶级评论;POST 返回 201 + 新评论。
    """
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    if request.method == "POST":
        serializer = PostCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent = None
        parent_id = serializer.validated_data.get("parent_id")
        if parent_id is not None:
            parent = get_object_or_404(visible_comments(post, request.user), pk=parent_id)
        comment = create_comment(post, request.user,
                                 serializer.validated_data["text"], parent)
        notify_comment_created(comment)
        return Response(PostCommentSerializer(comment, context={"request": request}).data,
                        status=201)
    top = visible_comments(post, request.user).filter(parent__isnull=True)
    return _page_response(request, top, PostCommentSerializer)
```

导入改为:

```python
from .services import (create_comment, delete_post, notify_comment_created,
                       visible_comments, visible_posts)
```

- [ ] **Step 6: 跑测试**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed.tests.PostCommentThreadTests feed.tests.PostCommentTests -v 2
```

Expected: 新增 4 条 PASS,原有评论用例仍 PASS(此时顶级评论还没带 `reply_count`,Task 3 才补)。

- [ ] **Step 7: 提交**

```bash
git add chatapp/feed/services.py chatapp/feed/serializers.py chatapp/feed/views.py chatapp/feed/tests.py
git commit -m "feat(feed): 发表评论支持 parent_id 并归一到两级"
```

---

### Task 3: 评论列表返回 `reply_to` / `reply_count` / 内嵌 `replies`

**Files:**
- Modify: `chatapp/feed/serializers.py`、`chatapp/feed/views.py`
- Test: `chatapp/feed/tests.py`

**Interfaces:**
- Consumes: `visible_comments(post, viewer)`
- Produces: 评论对象 JSON 字段 `parent_id` / `reply_to` / `reply_count` / `replies`

- [ ] **Step 1: 写失败的列表测试**

在 `PostCommentThreadTests` 里追加:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed.tests.PostCommentThreadTests -v 2
```

Expected: FAIL —— `KeyError: 'reply_count'`

- [ ] **Step 3: 补序列化器**

`chatapp/feed/serializers.py` 的 `PostCommentSerializer` 整段替换为:

```python
class PostCommentSerializer(serializers.ModelSerializer):
    """评论的对外表示:作者摘要、被回复者、回复数与内嵌前两条回复。

    回复不再递归:回复对象的 ``replies`` 恒为空、``reply_count`` 恒为 0,
    避免响应随层级膨胀。
    """

    author = serializers.SerializerMethodField()
    parent_id = serializers.IntegerField(read_only=True, allow_null=True)
    reply_to = serializers.SerializerMethodField()
    reply_count = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        model = PostComment
        fields = ["id", "author", "text", "parent_id", "reply_to",
                  "reply_count", "replies", "created_at"]

    def get_author(self, comment):
        """取评论作者的简要信息。

        Args:
            comment: 评论对象。

        Returns:
            ``author_brief`` 的结果。
        """
        return author_brief(comment.author, self.context["request"])

    def _visible_replies(self, comment):
        """取该评论下的可见回复(优先用视图预取的结果)。

        Args:
            comment: 顶级评论。

        Returns:
            按时间正序的回复列表;结果会缓存在实例上,避免重复查询。
        """
        cached = getattr(comment, "visible_replies", None)
        if cached is not None:
            return cached
        cached = list(comment.replies.select_related("author__profile", "reply_to__profile")
                      .prefetch_related("author__photos"))
        comment.visible_replies = cached
        return cached

    def get_reply_to(self, comment):
        """取被回复者的简要信息。

        Args:
            comment: 评论对象。

        Returns:
            ``{user_id, nickname}``;顶级评论或被回复者已注销时为 ``None``。
        """
        user = comment.reply_to
        if user is None:
            return None
        profile = getattr(user, "profile", None)
        return {"user_id": user.id, "nickname": profile.nickname if profile else ""}

    def get_reply_count(self, comment):
        """取该楼层可见回复的总数(回复对象恒为 0)。

        Args:
            comment: 评论对象。

        Returns:
            可见回复条数。
        """
        if comment.parent_id is not None:
            return 0
        return len(self._visible_replies(comment))

    def get_replies(self, comment):
        """取该楼层内嵌的前两条回复(回复对象恒为空)。

        Args:
            comment: 评论对象。

        Returns:
            回复对象列表,最多 2 条。
        """
        if comment.parent_id is not None:
            return []
        replies = self._visible_replies(comment)[:2]
        return PostCommentSerializer(replies, many=True, context=self.context).data
```

- [ ] **Step 4: 视图用 Prefetch 预取可见回复**

`chatapp/feed/views.py` 的 GET 分支改为:

```python
    top = visible_comments(post, request.user).filter(parent__isnull=True)
    top = top.prefetch_related(
        Prefetch("replies",
                 queryset=visible_comments(post, request.user).filter(parent__isnull=False),
                 to_attr="visible_replies"))
    return _page_response(request, top, PostCommentSerializer)
```

顶部导入补 `from django.db.models import Count, Exists, OuterRef, Prefetch`。

- [ ] **Step 5: 跑测试**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed -v 2
```

Expected: 全 PASS(`PostCommentTests` 里的旧断言不涉及新字段,不受影响)。

- [ ] **Step 6: 提交**

```bash
git add chatapp/feed/serializers.py chatapp/feed/views.py chatapp/feed/tests.py
git commit -m "feat(feed): 评论列表内嵌前两条回复与回复数"
```

---

### Task 4: 回复列表接口

**Files:**
- Modify: `chatapp/feed/views.py`、`chatapp/feed/urls.py`
- Test: `chatapp/feed/tests.py`

**Interfaces:**
- Consumes: `visible_comments`、`_page_response`
- Produces: `GET /api/v1/posts/{post_id}/comments/{comment_id}/replies`

- [ ] **Step 1: 写失败的接口测试**

```python
    def test_replies_endpoint_paginates_oldest_first(self):
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
        root = self._comment("一楼", author=self.author)
        reply = self._comment("回复", author=self.third, parent=root)
        resp = self.client.get(
            f"/api/v1/posts/{self.post.id}/comments/{reply.id}/replies")
        self.assertEqual(resp.status_code, 404)

    def test_replies_endpoint_404_for_other_post_comment(self):
        other_post = Post.objects.create(author=self.author, text="别的")
        foreign = PostComment.objects.create(post=other_post, author=self.author, text="外")
        resp = self.client.get(
            f"/api/v1/posts/{self.post.id}/comments/{foreign.id}/replies")
        self.assertEqual(resp.status_code, 404)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed.tests.PostCommentThreadTests -v 2
```

Expected: FAIL —— 404(路由不存在)

- [ ] **Step 3: 加视图**

`chatapp/feed/views.py` 追加:

```python
@api_view(["GET"])
def post_comment_replies(request, post_id, comment_id):
    """某条顶级评论的回复列表(GET /api/v1/posts/{post_id}/comments/{comment_id}/replies)。

    Args:
        request: DRF 请求对象,支持 ``limit`` / ``offset``。
        post_id: 动态主键。
        comment_id: 顶级评论主键。

    Returns:
        分页后的回复列表,按时间正序。

    Raises:
        Http404: 动态不可见、评论不存在/不属于该动态/本身是回复。
    """
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    root = get_object_or_404(
        visible_comments(post, request.user).filter(parent__isnull=True), pk=comment_id)
    replies = visible_comments(post, request.user).filter(parent=root)
    return _page_response(request, replies, PostCommentSerializer)
```

- [ ] **Step 4: 加路由**

`chatapp/feed/urls.py` 的 `urlpatterns` 改为:

```python
urlpatterns = [
    path("posts", views.posts),
    path("posts/mine", views.my_posts),
    path("posts/<int:post_id>", views.post_detail),
    path("posts/<int:post_id>/like", views.post_like),
    path("posts/<int:post_id>/comments", views.post_comments),
    path("posts/<int:post_id>/comments/<int:comment_id>/replies",
         views.post_comment_replies),
    path("posts/<int:post_id>/report", views.post_report),
]
```

- [ ] **Step 5: 跑测试**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed -v 2
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add chatapp/feed/views.py chatapp/feed/urls.py chatapp/feed/tests.py
git commit -m "feat(feed): 回复列表接口(分页,正序)"
```

---

### Task 5: 删除评论接口

**Files:**
- Modify: `chatapp/feed/services.py`、`chatapp/feed/views.py`、`chatapp/feed/urls.py`
- Test: `chatapp/feed/tests.py`

**Interfaces:**
- Consumes: Task 4 的路由文件
- Produces: `DELETE /api/v1/posts/{post_id}/comments/{comment_id}`;`delete_comment(comment) -> None`

- [ ] **Step 1: 写失败的删除测试**

```python
    def test_delete_top_level_comment_cascades_replies(self):
        root = self._comment("一楼", author=self.me)
        self._comment("回复", author=self.third, parent=root)
        resp = self.client.delete(
            f"/api/v1/posts/{self.post.id}/comments/{root.id}")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(PostComment.objects.count(), 0)

    def test_delete_reply_only_removes_itself(self):
        root = self._comment("一楼", author=self.author)
        mine = self._comment("我的回复", author=self.me, parent=root)
        other = self._comment("别人的回复", author=self.third, parent=root)
        resp = self.client.delete(
            f"/api/v1/posts/{self.post.id}/comments/{mine.id}")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(list(PostComment.objects.values_list("id", flat=True)),
                         [root.id, other.id])

    def test_delete_others_comment_404(self):
        other = self._comment("别人的", author=self.third)
        resp = self.client.delete(
            f"/api/v1/posts/{self.post.id}/comments/{other.id}")
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(PostComment.objects.filter(pk=other.id).exists())

    def test_delete_comment_of_other_post_404(self):
        other_post = Post.objects.create(author=self.author, text="别的")
        foreign = PostComment.objects.create(post=other_post, author=self.me, text="外")
        resp = self.client.delete(
            f"/api/v1/posts/{self.post.id}/comments/{foreign.id}")
        self.assertEqual(resp.status_code, 404)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed.tests.PostCommentThreadTests -v 2
```

Expected: FAIL —— 405(方法不允许)

- [ ] **Step 3: 服务层加删除**

`chatapp/feed/services.py` 追加:

```python
def delete_comment(comment) -> None:
    """删除一条评论;删顶级评论时回复由数据库 CASCADE 一并删除。

    Args:
        comment: 待删除的评论(调用方已校验作者身份)。
    """
    comment.delete()
```

- [ ] **Step 4: 加视图与路由**

`chatapp/feed/views.py` 追加:

```python
@api_view(["DELETE"])
def post_comment_detail(request, post_id, comment_id):
    """删除自己的评论(DELETE /api/v1/posts/{post_id}/comments/{comment_id})。

    删顶级评论会连带删除该楼全部回复;非作者一律 404(不暴露存在性)。

    Args:
        request: DRF 请求对象。
        post_id: 动态主键。
        comment_id: 评论主键。

    Returns:
        204 空响应。

    Raises:
        Http404: 动态不可见,或评论不存在 / 不属于该动态 / 不是自己发的。
    """
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    comment = get_object_or_404(PostComment, pk=comment_id, post=post,
                                author=request.user)
    delete_comment(comment)
    return Response(status=204)
```

导入行改为:

```python
from .services import (create_comment, delete_comment, delete_post,
                       notify_comment_created, visible_comments, visible_posts)
```

`chatapp/feed/urls.py` 在 replies 路由后追加:

```python
    path("posts/<int:post_id>/comments/<int:comment_id>", views.post_comment_detail),
```

- [ ] **Step 5: 跑测试**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed -v 2
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add chatapp/feed/services.py chatapp/feed/views.py chatapp/feed/urls.py chatapp/feed/tests.py
git commit -m "feat(feed): 删除评论接口(删楼级联回复)"
```

---

### Task 6: 提醒分流(顶级 → 作者,回复 → 被回复者)

**Files:**
- Modify: `chatapp/feed/services.py`、`chatapp/im/client.py`、`chatapp/im/tasks.py`
- Test: `chatapp/feed/tests.py`

**Interfaces:**
- Consumes: Task 2 的 `create_comment`
- Produces: `notify_comment_created(comment)`;`im.tasks.post_replied.delay(comment_id)`;`im_client.send_post_replied(to_identifier, replier_nickname, snippet)`

- [ ] **Step 1: 写失败的提醒测试**

```python
    def test_top_level_comment_still_notifies_post_author(self):
        with patch("im.tasks.post_commented.delay") as commented, \
                patch("im.tasks.post_replied.delay") as replied:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(self.url, {"text": "沙发"}, format="json")
        self.assertEqual(resp.status_code, 201)
        commented.assert_called_once_with(resp.json()["id"])
        replied.assert_not_called()

    def test_reply_notifies_replied_user(self):
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
        root = self._comment("一楼", author=self.me)
        with patch("im.tasks.post_replied.delay") as replied:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(self.url, {"text": "自回", "parent_id": root.id},
                                 format="json")
        replied.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed.tests.PostCommentThreadTests -v 2
```

Expected: FAIL —— `AttributeError: <module 'im.tasks'> does not have the attribute 'post_replied'`

- [ ] **Step 3: IM 客户端加方法**

`chatapp/im/client.py` 常量区(`POST_COMMENTED_TEMPLATE` 下一行)加:

```python
POST_REPLIED_TEMPLATE = "{nickname} 回复了你:{snippet}"
```

`send_post_commented` 之后加:

```python
def send_post_replied(to_identifier: str, replier_nickname: str, snippet: str) -> bool:
    """被回复通知:以「系统通知」身份发给被回复者。

    Args:
        to_identifier: 被回复者的 IM 账号。
        replier_nickname: 回复者昵称,用于通知正文。
        snippet: 回复内容摘要(由调用方截断)。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    desc = POST_REPLIED_TEMPLATE.format(nickname=replier_nickname, snippet=snippet)
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "post_replied"}, desc)
```

- [ ] **Step 4: 任务加 `post_replied`**

`chatapp/im/tasks.py` 在 `post_commented` 之后加:

```python
@shared_task(**RETRY_POLICY)
def post_replied(comment_id: int) -> None:
    """回复通知:告知被回复者(自己回复自己不发;内容缺失静默)。

    Args:
        comment_id: 新回复的主键;任务内再查库取被回复者与作者昵称。
    """
    from feed.models import PostComment   # 延迟导入,避免 app 加载顺序问题

    comment = (PostComment.objects.filter(id=comment_id)
               .select_related("author__profile", "reply_to__profile").first())
    if comment is None or comment.reply_to_id is None:
        return
    if comment.reply_to_id == comment.author_id:
        return
    profile = getattr(comment.author, "profile", None)
    nickname = (profile.nickname if profile else "") or f"u{comment.author_id}"
    _require(im_client.send_post_replied(comment.reply_to.im_user_id, nickname,
                                         comment.text[:50]), "post_replied")
```

- [ ] **Step 5: 服务层改分流**

`chatapp/feed/services.py` 的 `notify_post_commented` 整段替换为:

```python
def notify_comment_created(comment) -> None:
    """评论创建后调用:顶级评论通知动态作者,回复通知被回复者。

    自己评论自己的动态、自己回复自己都不入队(不打扰)。

    Args:
        comment: 刚创建的评论或回复。
    """
    if comment.parent_id is None:
        if comment.post.author_id == comment.author_id:
            return
        transaction.on_commit(lambda: im_tasks.post_commented.delay(comment.id),
                              robust=True)
        return
    if comment.reply_to_id is None or comment.reply_to_id == comment.author_id:
        return
    transaction.on_commit(lambda: im_tasks.post_replied.delay(comment.id), robust=True)
```

- [ ] **Step 6: 跑测试**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test feed im -v 2
```

Expected: PASS(原有 `test_create_comment_notifies_author` / `test_self_comment_does_not_notify` 也必须绿)。

- [ ] **Step 7: 提交**

```bash
git add chatapp/feed/services.py chatapp/im/client.py chatapp/im/tasks.py chatapp/feed/tests.py
git commit -m "feat(feed): 回复提醒走 IM 灰条(顶级通知作者、回复通知被回复者)"
```

---

### Task 7: 接口文档与门禁

**Files:**
- Modify: `docs/api/feed.md`、`docs/api/README.md`

**Interfaces:**
- Consumes: Task 2–5 的四个接口
- Produces: 文档与 URLconf 对齐(38 个接口)

- [ ] **Step 1: 先跑门禁确认失败**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test config.tests.ApiDocsCoverageTests -v 2
```

Expected: FAIL —— 两条「接口 … 未写文档」(replies / 删除评论)

- [ ] **Step 2: 改 `docs/api/feed.md` 头部与 5.8 / 5.9**

第 3 行改为:

```markdown
本分册含 12 个接口:动态流(列表/发布)、我的动态、详情/删除、点赞/取消、评论(列表/发表/回复列表/删除)、举报动态。
```

5.8 响应参数表在 `created_at` 前插入:

```markdown
| parent_id | Integer / null | 顶级评论为 `null`;回复为所属顶级评论 ID |
| reply_to | Object / null | 被回复者摘要 `{user_id, nickname}`;顶级评论为 `null` |
| reply_count | Integer | 该楼层的可见回复总数(回复对象恒为 0) |
| replies | Object[] | 内嵌的前 2 条回复,结构同本表(回复对象恒为空数组) |
```

5.8 的接口描述改为:

```markdown
分页拉取某条动态的**顶级评论**(回复不单独分页,内嵌在每条评论里)。作者被双向拉黑或被重封禁的评论不会返回;`reply_count` 与 `replies` 同样按可见性过滤。
```

5.9 请求参数表加一行:

```markdown
| parent_id | 否 | Integer | 被回复的评论 ID;不传 = 发表顶级评论。指向回复时服务端自动归到其顶级评论 |
```

5.9 接口描述改为:

```markdown
给动态发表评论或回复。`parent_id` 为空时是顶级评论,评论成功后动态作者会收到一条系统通知;`parent_id` 非空时是回复,被回复者会收到「X 回复了你」的系统通知(自己回复自己不提醒)。层级恒为两级:回复一条回复时,新回复仍挂在同一楼层,`reply_to` 记录真正被回复的人。
```

5.9 响应参数表在 `created_at` 前插入与 5.8 相同的四行(直接复制)。

- [ ] **Step 3: 追加 5.11 / 5.12**

在 `docs/api/feed.md` 末尾追加:

````markdown
---

### 5.11 回复列表

> `GET` `/api/v1/posts/{post_id}/comments/{comment_id}/replies` · 需要鉴权 · 无额外限流

**接口描述**

分页拉取某条顶级评论下的全部回复,按时间正序(早 → 晚)。作者被双向拉黑或被重封禁的回复不会返回。`comment_id` 不存在、不属于该动态、或本身就是一条回复时返回 404。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |
| comment_id | 是 | Integer | 顶级评论 ID(路径参数) |
| limit | 否 | Integer | 每页条数,默认 20,上限 100(Query) |
| offset | 否 | Integer | 偏移量,默认 0(Query) |

**响应参数**

分页对象,`results[]` 为回复对象,字段见 5.8(其中 `replies` 恒为空数组、`reply_count` 恒为 0)。

**请求示例**

```bash
curl "http://<域名>/api/v1/posts/9/comments/3/replies?limit=20&offset=0" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 5,
      "author": {
        "user_id": 12,
        "nickname": "小雨12",
        "avatar_url": "http://<域名>/media/photos/2026/09/seed_12_0.jpg"
      },
      "text": "同问",
      "parent_id": 3,
      "reply_to": {"user_id": 7, "nickname": "阿哲"},
      "reply_count": 0,
      "replies": [],
      "created_at": "2026-10-20T10:05:00+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不可见,或评论不存在 / 不属于该动态 / 本身是回复 | 从列表移除该楼层,不要重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.12 删除评论

> `DELETE` `/api/v1/posts/{post_id}/comments/{comment_id}` · 需要鉴权 · 无额外限流

**接口描述**

删除自己发表的评论。**只有作者本人能删**:非作者、评论不存在、不属于该动态一律返回 404。删除顶级评论会**连带删除该楼全部回复**;删除回复只删这一条。删除后动态的 `comment_count` 相应减少。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |
| comment_id | 是 | Integer | 评论 ID(路径参数) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE "http://<域名>/api/v1/posts/9/comments/3" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不可见,或评论不存在 / 不属于该动态 / 不是自己发的 | 刷新评论列表后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
````

- [ ] **Step 4: 改 `docs/api/README.md`**

第 24 行改为:

```markdown
共 **38** 个接口(按「方法 + 路径」计)。
```

在「评论列表」两行之后插入:

```markdown
| GET | `/api/v1/posts/{post_id}/comments/{comment_id}/replies` | 回复列表(分页) | [feed](feed.md) |
| DELETE | `/api/v1/posts/{post_id}/comments/{comment_id}` | 删除我的评论 | [feed](feed.md) |
```

- [ ] **Step 5: 跑门禁**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test config -v 2
```

Expected: PASS(`ApiDocsCoverageTests` / `CommentCoverageTests` 全绿)

- [ ] **Step 6: 提交**

```bash
git add docs/api/feed.md docs/api/README.md
git commit -m "docs(api): 评论楼中楼四接口(36→38)"
```

---

### Task 8: App 模型 / 仓库 / 控制器

**Files:**
- Modify: `app/lib/features/square/models.dart`、`app/lib/features/square/feed_repository.dart`、`app/lib/features/square/post_detail_controller.dart`
- Test: `app/test/support/sample_data.dart`、`app/test/features/square/post_detail_page_test.dart`

**Interfaces:**
- Consumes: Task 2–5 的接口
- Produces:
  - `PostCommentItem.parentId: int?`、`.replyTo: FeedAuthor?`、`.replyCount: int`、`.replies: List<PostCommentItem>`
  - `FeedRepository.addComment(int postId, String text, {int? parentId})`
  - `FeedRepository.fetchReplies(int postId, int commentId, {int limit, int offset})`
  - `FeedRepository.deleteComment(int postId, int commentId)`
  - `CommentsController.send(String text, {int? parentId})`
  - `repliesProvider`(family key `({int postId, int commentId})`)

- [ ] **Step 1: 改测试夹具**

`app/test/support/sample_data.dart` 的 `commentJson` 整段替换为:

```dart
/// 造一条评论/回复;字段可覆盖。
Map<String, dynamic> commentJson({
  int id = 1,
  int authorId = 9,
  String nickname = 'Bob',
  String text = '评论',
  String createdAt = '2026-09-12T20:00:00+08:00',
  int? parentId,
  Map<String, dynamic>? replyTo,
  int replyCount = 0,
  List<Map<String, dynamic>> replies = const [],
}) =>
    {
      'id': id,
      'author': {'user_id': authorId, 'nickname': nickname, 'avatar_url': null},
      'text': text,
      'created_at': createdAt,
      'parent_id': parentId,
      'reply_to': replyTo,
      'reply_count': replyCount,
      'replies': replies,
    };

/// 造一个「被回复者」摘要(评论对象里的 `reply_to`)。
Map<String, dynamic> replyToJson({int userId = 7, String nickname = '阿哲'}) =>
    {'user_id': userId, 'nickname': nickname};
```

- [ ] **Step 2: 写失败的模型测试**

新建 `app/test/features/square/comment_model_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/square/models.dart';

import '../../support/sample_data.dart';

void main() {
  test('解析楼中楼字段', () {
    final item = PostCommentItem.fromJson(commentJson(
      id: 5,
      parentId: 3,
      replyTo: replyToJson(userId: 7, nickname: '阿哲'),
      replyCount: 2,
      replies: [
        commentJson(id: 6, text: '回复一', parentId: 3),
        commentJson(id: 7, text: '回复二', parentId: 3),
      ],
    ));
    expect(item.parentId, 3);
    expect(item.replyTo?.nickname, '阿哲');
    expect(item.replyCount, 2);
    expect(item.replies.map((e) => e.text), ['回复一', '回复二']);
  });

  test('顶级评论无 reply_to 时解析为 null', () {
    final item = PostCommentItem.fromJson(commentJson());
    expect(item.parentId, isNull);
    expect(item.replyTo, isNull);
    expect(item.replies, isEmpty);
  });
}
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/square/comment_model_test.dart
```

Expected: FAIL —— `The named parameter 'parentId' isn't defined`

- [ ] **Step 4: 改模型**

`app/lib/features/square/models.dart` 的 `PostCommentItem` 整段替换为:

```dart
class PostCommentItem {
  const PostCommentItem({
    required this.id,
    required this.author,
    required this.text,
    required this.createdAt,
    this.parentId,
    this.replyTo,
    this.replyCount = 0,
    this.replies = const [],
  });

  final int id;
  final FeedAuthor author;
  final String text;
  final DateTime createdAt;

  /// 顶级评论为 null;回复为所属顶级评论的 id。
  final int? parentId;

  /// 被回复者;顶级评论为 null。
  final FeedAuthor? replyTo;

  /// 该楼层的可见回复总数(回复对象恒为 0)。
  final int replyCount;

  /// 内嵌的前两条回复(回复对象恒为空)。
  final List<PostCommentItem> replies;

  factory PostCommentItem.fromJson(Map<String, dynamic> json) => PostCommentItem(
        id: json['id'] as int,
        author: FeedAuthor.fromJson(json['author'] as Map<String, dynamic>),
        text: json['text'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        parentId: json['parent_id'] as int?,
        replyTo: json['reply_to'] == null
            ? null
            : FeedAuthor.fromJson(json['reply_to'] as Map<String, dynamic>),
        replyCount: json['reply_count'] as int? ?? 0,
        replies: (json['replies'] as List<dynamic>? ?? [])
            .map((item) => PostCommentItem.fromJson(item as Map<String, dynamic>))
            .toList(),
      );
}
```

- [ ] **Step 5: 改仓库**

`app/lib/features/square/feed_repository.dart` 的 `addComment` 替换为下面三个方法:

```dart
  Future<void> addComment(int postId, String text, {int? parentId}) async {
    await _api.post('/posts/$postId/comments', data: {
      'text': text,
      if (parentId != null) 'parent_id': parentId,
    });
  }

  Future<({List<PostCommentItem> items, bool hasMore})> fetchReplies(
      int postId, int commentId, {int limit = 100, int offset = 0}) async {
    final page = await _api.get('/posts/$postId/comments/$commentId/replies',
        query: {'limit': limit, 'offset': offset}) as Map<String, dynamic>;
    final items = (page['results'] as List<dynamic>)
        .map((item) => PostCommentItem.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, hasMore: page['next'] != null);
  }

  Future<void> deleteComment(int postId, int commentId) async {
    await _api.delete('/posts/$postId/comments/$commentId');
  }
```

- [ ] **Step 6: 改控制器**

`app/lib/features/square/post_detail_controller.dart` 的 `CommentsController` 与文件末尾追加:

```dart
class CommentsController extends AsyncNotifier<List<PostCommentItem>> {
  CommentsController(this.postId);

  final int postId;

  @override
  Future<List<PostCommentItem>> build() async =>
      (await ref.read(feedRepositoryProvider).fetchComments(postId)).items;

  /// 发评论或回复;``parentId`` 非空表示回复某条评论。
  Future<void> send(String text, {int? parentId}) async {
    await ref.read(feedRepositoryProvider).addComment(postId, text, parentId: parentId);
  }

  /// 删除一条评论(顶级评论会连带删除其回复)。
  Future<void> delete(int commentId) async {
    await ref.read(feedRepositoryProvider).deleteComment(postId, commentId);
  }
}

final commentsProvider = AsyncNotifierProvider.autoDispose
    .family<CommentsController, List<PostCommentItem>, int>(CommentsController.new,
        retry: (retryCount, error) => null);

/// 某条顶级评论下「已展开」的全部回复。
class RepliesController extends AsyncNotifier<List<PostCommentItem>> {
  RepliesController(this.key);

  final ({int postId, int commentId}) key;

  @override
  Future<List<PostCommentItem>> build() async =>
      (await ref.read(feedRepositoryProvider)
              .fetchReplies(key.postId, key.commentId))
          .items;
}

final repliesProvider = AsyncNotifierProvider.autoDispose.family<RepliesController,
    List<PostCommentItem>, ({int postId, int commentId})>(RepliesController.new,
    retry: (retryCount, error) => null);
```

- [ ] **Step 7: 跑测试**

```bash
cd app
../flutter/bin/flutter.bat test test/features/square/comment_model_test.dart
../flutter/bin/flutter.bat analyze
```

Expected: 2 条测试 PASS,`analyze` 零告警。

- [ ] **Step 8: 提交**

```bash
git add app/lib/features/square/models.dart app/lib/features/square/feed_repository.dart app/lib/features/square/post_detail_controller.dart app/test/support/sample_data.dart app/test/features/square/comment_model_test.dart
git commit -m "feat(app/square): 评论模型/仓库/控制器支持楼中楼"
```

---

### Task 9: App 楼层 UI、回复态与删除

**Files:**
- Create: `app/lib/features/square/widgets/comment_thread.dart`
- Modify: `app/lib/features/square/post_detail_page.dart`
- Test: `app/test/features/square/post_detail_page_test.dart`

**Interfaces:**
- Consumes: Task 8 的模型与 provider
- Produces: `CommentThread`(参数见下)、`_CommentBar` 的回复态

- [ ] **Step 1: 写失败的 Widget 测试**

在 `app/test/features/square/post_detail_page_test.dart` 的 `main()` 里追加:

```dart
  testWidgets('楼层:内嵌前两条回复 + 查看全部按钮', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/1': (options) => ok(postJson(id: 1, text: '正文', commentCount: 3)),
      'GET /posts/1/comments': (options) => ok(pageJson([
            commentJson(
              id: 5,
              nickname: 'Bob',
              text: '一楼',
              replyCount: 3,
              replies: [
                commentJson(id: 6, nickname: 'Carol', text: '回复一', parentId: 5,
                    replyTo: replyToJson(userId: 9, nickname: 'Bob')),
                commentJson(id: 7, nickname: 'Dave', text: '回复二', parentId: 5,
                    replyTo: replyToJson(userId: 9, nickname: 'Bob')),
              ],
            ),
          ])),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    expect(find.textContaining('回复一'), findsOneWidget);
    expect(find.textContaining('回复二'), findsOneWidget);
    expect(find.textContaining('回复 @Bob'), findsWidgets);
    expect(find.byKey(const Key('post.comment.replies.more.5')), findsOneWidget);
  });

  testWidgets('点「回复」进入回复态,发送带 parent_id', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/1': (options) => ok(postJson(id: 1, text: '正文', commentCount: 1)),
      'GET /posts/1/comments': (options) => ok(pageJson([
            commentJson(id: 5, nickname: 'Bob', text: '一楼'),
          ])),
      'POST /posts/1/comments': (options) =>
          ok(commentJson(id: 8, nickname: '我', text: '回你', parentId: 5), status: 201),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.comment.reply.5')));
    await tester.pumpAndSettle();
    expect(find.textContaining('回复 @Bob'), findsWidgets);

    await tester.enterText(find.byKey(const Key('post.comment.input')), '回你');
    await tester.tap(find.byKey(const Key('post.comment.send')));
    await tester.pumpAndSettle();

    final sent = adapter.log.firstWhere(
        (r) => r.method == 'POST' && r.path == '/posts/1/comments');
    expect(sent.data, {'text': '回你', 'parent_id': 5});
  });

  testWidgets('删除自己的评论需二次确认', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /users/me': (options) => ok(profileJson(nickname: '小明', userId: 7)),
      'GET /posts/1': (options) => ok(postJson(id: 1, text: '正文', commentCount: 1)),
      'GET /posts/1/comments': (options) => ok(pageJson([
            commentJson(id: 5, authorId: 7, nickname: '小明', text: '我评的'),
          ])),
      'DELETE /posts/1/comments/5': (options) async =>
          ResponseBody.fromString('', 204),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.comment.delete.5')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.comment.delete.confirm')));
    await tester.pumpAndSettle();

    expect(adapter.log.where((r) => r.method == 'DELETE' && r.path == '/posts/1/comments/5'),
        hasLength(1));
  });
```

> `ResponseBody.fromString` 来自 `package:dio/dio.dart`,该测试文件已导入 `dio`;
> `ScriptedAdapter` 的响应必须是 `ResponseBody`,不能直接返回 `Response`。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/square/post_detail_page_test.dart
```

Expected: FAIL —— `Could not find a widget with key 'post.comment.reply.5'`

- [ ] **Step 3: 新建楼层组件**

新建 `app/lib/features/square/widgets/comment_thread.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_exception.dart';
import '../../../core/format.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_avatar.dart';
import '../../../core/widgets/app_empty_state.dart';
import '../../../core/widgets/app_error_view.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../models.dart';
import '../post_detail_controller.dart';

/// 评论流(附录 D):顶级评论 + 内嵌回复 + 「查看全部 N 条回复」。
///
/// 楼层恒为两级:回复对象不再递归展开,与后端一致。
class CommentThread extends StatelessWidget {
  const CommentThread({
    super.key,
    required this.postId,
    required this.comments,
    required this.myId,
    required this.onReply,
    required this.onDelete,
    required this.onRetry,
  });

  final int postId;
  final AsyncValue<List<PostCommentItem>> comments;
  final int? myId;
  final void Function(PostCommentItem comment) onReply;
  final void Function(PostCommentItem comment) onDelete;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return comments.when(
      loading: () => const Padding(
        padding: EdgeInsets.all(AppSpacing.xxl),
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: AppErrorView(message: apiMessageOf(error), onRetry: onRetry),
      ),
      data: (items) => items.isEmpty
          ? const Center(
              child: AppEmptyState(emoji: '💬', title: '还没有评论', description: '来抢沙发'),
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (var i = 0; i < items.length; i++) ...[
                  if (i > 0) const Divider(height: 1, color: AppColors.divider),
                  CommentTile(
                    comment: items[i],
                    depth: 0,
                    isMine: items[i].author.userId == myId,
                    onReply: () => onReply(items[i]),
                    onDelete: () => onDelete(items[i]),
                  ),
                  for (final reply in items[i].replies)
                    CommentTile(
                      comment: reply,
                      depth: 1,
                      isMine: reply.author.userId == myId,
                      onReply: () => onReply(reply),
                      onDelete: () => onDelete(reply),
                    ),
                  if (items[i].replyCount > items[i].replies.length)
                    _MoreReplies(
                      postId: postId,
                      root: items[i],
                      myId: myId,
                      onReply: onReply,
                      onDelete: onDelete,
                    ),
                ],
              ],
            ),
    );
  }
}

/// 一条评论或回复;`depth` 为 1 时缩进、头像缩到 24。
class CommentTile extends StatelessWidget {
  const CommentTile({
    super.key,
    required this.comment,
    required this.depth,
    required this.isMine,
    required this.onReply,
    required this.onDelete,
  });

  final PostCommentItem comment;
  final int depth;
  final bool isMine;
  final VoidCallback onReply;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final indent = depth == 0 ? 0.0 : AppSpacing.xxl;
    final size = depth == 0 ? 28.0 : 24.0;
    final heroTag = 'avatar-comment-${comment.id}';
    final replyTo = comment.replyTo;
    return Padding(
      key: Key('post.comment.${comment.id}'),
      padding: EdgeInsets.fromLTRB(indent, 12, 0, 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AvatarHero(
            tag: heroTag,
            imageUrl: comment.author.avatarUrl,
            fromRadius: AppRadius.full,
            child: GestureDetector(
              key: Key('post.comment.avatar.${comment.id}'),
              behavior: HitTestBehavior.opaque,
              onTap: isMine
                  ? null
                  : () => context.push('/users/${comment.author.userId}',
                      extra: heroTag),
              child: AppAvatar(
                imageUrl: comment.author.avatarUrl,
                size: size,
                fallbackText: comment.author.nickname,
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                GestureDetector(
                  key: Key('post.comment.nickname.${comment.id}'),
                  behavior: HitTestBehavior.opaque,
                  onTap: isMine
                      ? null
                      : () => context.push('/users/${comment.author.userId}',
                          extra: heroTag),
                  child: Text(comment.author.nickname,
                      style: AppText.caption.copyWith(
                          fontWeight: FontWeight.w600, color: AppColors.text2)),
                ),
                const SizedBox(height: 2),
                Text.rich(TextSpan(children: [
                  if (replyTo != null)
                    TextSpan(
                      text: '回复 @${replyTo.nickname} ',
                      style: AppText.body.copyWith(color: AppColors.text3),
                    ),
                  TextSpan(
                    text: comment.text,
                    style: AppText.body.copyWith(color: AppColors.text1),
                  ),
                ])),
                const SizedBox(height: 2),
                Row(
                  children: [
                    Text(formatPostTime(comment.createdAt),
                        style: AppText.micro.copyWith(color: AppColors.text3)),
                    const SizedBox(width: AppSpacing.md),
                    _TextButton(
                      key: Key('post.comment.reply.${comment.id}'),
                      label: '回复',
                      onTap: onReply,
                    ),
                    if (isMine) ...[
                      const SizedBox(width: AppSpacing.sm),
                      _TextButton(
                        key: Key('post.comment.delete.${comment.id}'),
                        label: '删除',
                        onTap: onDelete,
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _TextButton extends StatelessWidget {
  const _TextButton({super.key, required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 2, horizontal: 2),
          child: Text(label,
              style: AppText.micro.copyWith(color: AppColors.text2)),
        ),
      );
}

/// 「查看全部 N 条回复」:点击后走独立接口拉全量,原地展开。
class _MoreReplies extends ConsumerStatefulWidget {
  const _MoreReplies({
    required this.postId,
    required this.root,
    required this.myId,
    required this.onReply,
    required this.onDelete,
  });

  final int postId;
  final PostCommentItem root;
  final int? myId;
  final void Function(PostCommentItem comment) onReply;
  final void Function(PostCommentItem comment) onDelete;

  @override
  ConsumerState<_MoreReplies> createState() => _MoreRepliesState();
}

class _MoreRepliesState extends ConsumerState<_MoreReplies> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final root = widget.root;
    if (!_expanded) {
      return Padding(
        padding: const EdgeInsets.only(left: AppSpacing.xxl, bottom: AppSpacing.sm),
        child: GestureDetector(
          key: Key('post.comment.replies.more.${root.id}'),
          behavior: HitTestBehavior.opaque,
          onTap: () => setState(() => _expanded = true),
          child: Text('查看全部 ${root.replyCount} 条回复',
              style: AppText.micro.copyWith(color: AppColors.text2)),
        ),
      );
    }
    final replies = ref.watch(
        repliesProvider((postId: widget.postId, commentId: root.id)));
    return AnimatedSize(
      duration: const Duration(milliseconds: 180),
      alignment: Alignment.topCenter,
      child: replies.when(
        loading: () => const Padding(
          padding: EdgeInsets.symmetric(vertical: AppSpacing.md),
          child: Center(child: CircularProgressIndicator()),
        ),
        error: (error, _) => Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: Text(apiMessageOf(error),
              style: AppText.micro.copyWith(color: AppColors.text3)),
        ),
        data: (items) => Column(
          children: [
            for (final reply in items)
              CommentTile(
                comment: reply,
                depth: 1,
                isMine: reply.author.userId == widget.myId,
                onReply: () => widget.onReply(reply),
                onDelete: () => widget.onDelete(reply),
              ),
          ],
        ),
      ),
    );
  }
}
```

> `_MoreReplies` 只负责「拉全量 + 展开」;回复行的回复/删除回调由
> `CommentThread` 透传,与内嵌的两条回复行为一致。

- [ ] **Step 4: 详情页接入楼层 + 回复态 + 删除**

`app/lib/features/square/post_detail_page.dart` 的改动:

1. 导入 `widgets/comment_thread.dart`,删除文件内 `_CommentTile` 整类;
2. `_PostDetailPageState` 加字段与三个方法:

```dart
  PostCommentItem? _replyTo;

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    setState(() => _sending = true);
    try {
      await ref
          .read(commentsProvider(widget.postId).notifier)
          .send(text, parentId: _replyTo?.id);
      _input.clear();
      setState(() => _replyTo = null);
      ref.invalidate(commentsProvider(widget.postId));
      ref.invalidate(postDetailProvider(widget.postId));
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _startReply(PostCommentItem comment) {
    setState(() => _replyTo = comment);
    _focus.requestFocus();
  }

  Future<void> _deleteComment(PostCommentItem comment) async {
    final extra = comment.replyCount > 0 ? '连同 ${comment.replyCount} 条回复一起删除,' : '';
    final confirmed = await showConfirmDialog(
      context,
      title: '删除这条评论?',
      message: '$extra删除后不可恢复',
      confirmLabel: '删除',
      confirmKey: const Key('post.comment.delete.confirm'),
      danger: true,
    );
    if (!confirmed || !mounted) return;
    try {
      await ref.read(commentsProvider(widget.postId).notifier).delete(comment.id);
      ref.invalidate(commentsProvider(widget.postId));
      ref.invalidate(repliesProvider);
      ref.invalidate(postDetailProvider(widget.postId));
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }
```

3. `_Body` 的构造参数里,把 `comments` 相关的三行(loading/error/data 整段)替换为:

```dart
        CommentThread(
          postId: post.id,
          comments: comments,
          myId: myId,
          onReply: onReply,
          onDelete: onDelete,
          onRetry: onRetryComments,
        ),
```

4. `_Body` 增加两个字段 `final void Function(PostCommentItem) onReply;` /
   `final void Function(PostCommentItem) onDelete;`,两处 `_Body(...)` 调用各传
   `onReply: _startReply, onDelete: _deleteComment`;

5. `_CommentBar` 增加 `replyTo` 与 `onCancelReply` 参数,在输入框上方插入 chip:

```dart
            if (replyTo != null)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                child: Row(
                  children: [
                    Flexible(
                      child: Text('回复 @${replyTo!.author.nickname}',
                          style: AppText.micro.copyWith(color: AppColors.text2)),
                    ),
                    GestureDetector(
                      key: const Key('post.comment.reply.cancel'),
                      behavior: HitTestBehavior.opaque,
                      onTap: onCancelReply,
                      child: Icon(Icons.close_rounded,
                          size: 16, color: AppColors.text3),
                    ),
                  ],
                ),
              ),
```

并把 `hintText` 改成:

```dart
                        hintText: replyTo == null
                            ? '说点什么…'
                            : '回复 @${replyTo!.author.nickname}…',
```

6. 顶部导入补 `import '../../core/widgets/app_dialog.dart';`;
7. 删掉因此不再使用的导入:`app_avatar.dart`、`avatar_hero.dart`、`app_empty_state.dart`
   与 `format.dart` 的 `formatPostTime`(评论渲染已搬进 `comment_thread.dart`);
   跑 `flutter analyze` 确认没有 `unused_import` 告警。

- [ ] **Step 5: 跑测试**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test test/features/square
```

Expected: 新增 3 条 + 原有详情页用例全 PASS;`analyze` 零告警。

- [ ] **Step 6: 提交**

```bash
git add app/lib/features/square/widgets/comment_thread.dart app/lib/features/square/post_detail_page.dart app/test/features/square/post_detail_page_test.dart
git commit -m "feat(app/square): 评论楼层、回复态与删除"
```

---

### Task 10: Web 类型、接口、组件与计数

**Files:**
- Modify: `web/src/api/types.ts`、`web/src/api/feed.ts`、`web/src/features/square/CommentList.vue`、`web/src/features/square/PostDetailPage.vue`
- Create: `web/tests/component/comment-list.spec.ts`
- Test: `web/tests/component/post-detail-page.spec.ts`

**Interfaces:**
- Consumes: Task 2–5 的接口
- Produces: `Comment.parent_id / reply_to / reply_count / replies`;`feedApi.fetchReplies` / `deleteComment`

- [ ] **Step 1: 改类型与接口**

`web/src/api/types.ts` 的 `Comment` 替换为:

```ts
export interface ReplyTo {
  user_id: number
  nickname: string
}

export interface Comment {
  id: number
  author: PostAuthor
  text: string
  parent_id: number | null
  reply_to: ReplyTo | null
  reply_count: number
  replies: Comment[]
  created_at: string
}
```

`web/src/api/feed.ts` 的 `createComment` 替换为下面三个函数:

```ts
export async function createComment(
  postId: number,
  text: string,
  parentId?: number,
): Promise<Comment> {
  const body = parentId === undefined ? { text } : { text, parent_id: parentId }
  const { data } = await http.post(`/posts/${postId}/comments`, body)
  return data as Comment
}

export async function fetchReplies(
  postId: number,
  commentId: number,
  limit = 100,
  offset = 0,
): Promise<Page<Comment>> {
  const { data } = await http.get(`/posts/${postId}/comments/${commentId}/replies`, {
    params: { limit, offset },
  })
  return data as Page<Comment>
}

export async function deleteComment(postId: number, commentId: number): Promise<void> {
  await http.delete(`/posts/${postId}/comments/${commentId}`)
}
```

- [ ] **Step 2: 写失败的组件测试**

新建 `web/tests/component/comment-list.spec.ts`:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import CommentList from '@/features/square/CommentList.vue'
import type { Comment } from '@/api/types'
import { server } from '../support/server'

const replyTo = { user_id: 9, nickname: '阿哲' }

function comment(over: Partial<Comment> = {}): Comment {
  return {
    id: 1,
    author: { user_id: 9, nickname: '阿哲', avatar_url: null },
    text: '一楼',
    parent_id: null,
    reply_to: null,
    reply_count: 0,
    replies: [],
    created_at: '2026-10-01T11:00:00Z',
    ...over,
  }
}

function reply(id: number, text: string): Comment {
  return comment({
    id,
    text,
    parent_id: 1,
    reply_to: replyTo,
    author: { user_id: 12, nickname: '小雨', avatar_url: null },
  })
}

function mountList(comments: Comment[], count = comments.length) {
  return mount(CommentList, {
    props: { postId: 5, comments, count },
    global: {
      plugins: [createPinia()],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

describe('CommentList 楼中楼', () => {
  it('渲染内嵌回复与「回复 @」前缀', () => {
    const w = mountList([
      comment({ reply_count: 2, replies: [reply(2, '回复一'), reply(3, '回复二')] }),
    ])
    expect(w.text()).toContain('回复一')
    expect(w.text()).toContain('回复 @阿哲')
  })

  it('回复多于 2 条时展示「查看全部」并展开', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5/comments/1/replies', () =>
        HttpResponse.json({
          count: 2,
          next: null,
          previous: null,
          results: [reply(2, '回复一'), reply(3, '回复二')],
        }),
      ),
    )
    const w = mountList([comment({ reply_count: 3, replies: [reply(2, '回复一')] })])
    const more = w.find('.comment-list__more')
    expect(more.text()).toContain('查看全部 3 条回复')

    await more.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('回复二')
  })

  it('点「回复」后提交带 parent_id', async () => {
    const created = reply(9, '回你')
    let body: unknown = null
    server.use(
      mswHttp.post('/api/v1/posts/5/comments', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    const w = mountList([comment()])
    await w.find('.comment-list__reply').trigger('click')
    expect(w.text()).toContain('回复 @阿哲')

    await w.find('input[type="text"]').setValue('回你')
    await w.find('.comment-list__submit').trigger('click')
    await flushPromises()

    expect(body).toEqual({ text: '回你', parent_id: 1 })
    expect(w.emitted('added')?.[0]).toEqual([created])
  })

  it('自己的评论显示删除,确认后回调', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.use(
      mswHttp.delete('/api/v1/posts/5/comments/1', () => new HttpResponse(null, { status: 204 })),
    )
    const mine = comment({ author: { user_id: 7, nickname: '我', avatar_url: null } })
    const w = mountList([mine])

    await w.find('.comment-list__delete').trigger('click')
    await flushPromises()

    expect(w.emitted('deleted')?.[0]).toEqual([mine])
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd web
npm run test:run -- tests/component/comment-list.spec.ts
```

Expected: FAIL —— 找不到 `.comment-list__reply`

- [ ] **Step 4: 重写 `CommentList.vue`**

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
import { parseApiError } from '@/api/error'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import * as feedApi from '@/api/feed'
import type { Comment } from '@/api/types'
import { useSessionStore } from '@/stores/session'

const props = defineProps<{ postId: number; comments: Comment[]; count: number }>()
const emit = defineEmits<{ added: [Comment]; deleted: [Comment] }>()

const session = useSessionStore()
const text = ref('')
const error = ref('')
const submitting = ref(false)
const offset = ref(props.comments.length)
const loadingMore = ref(false)
const replyTo = ref<Comment | null>(null)
const expanded = ref<Record<number, Comment[]>>({})
const expanding = ref<number | null>(null)

const hasMore = computed(() => props.comments.length < props.count)

function isMine(comment: Comment): boolean {
  return session.userId === comment.author.user_id
}

function startReply(comment: Comment) {
  replyTo.value = comment
}

function cancelReply() {
  replyTo.value = null
}

async function onSubmit() {
  const value = text.value.trim()
  error.value = ''
  if (!value) {
    error.value = '评论不能为空'
    return
  }
  submitting.value = true
  try {
    const comment = await feedApi.createComment(
      props.postId,
      value,
      replyTo.value?.id,
    )
    text.value = ''
    replyTo.value = null
    emit('added', comment)
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}

async function loadMore() {
  loadingMore.value = true
  try {
    const page = await feedApi.fetchComments(props.postId, 20, offset.value)
    offset.value += page.results.length
    page.results.forEach((item) => emit('added', item))
  } finally {
    loadingMore.value = false
  }
}

async function expandReplies(comment: Comment) {
  expanding.value = comment.id
  try {
    const page = await feedApi.fetchReplies(props.postId, comment.id)
    expanded.value = { ...expanded.value, [comment.id]: page.results }
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    expanding.value = null
  }
}

function repliesOf(comment: Comment): Comment[] {
  return expanded.value[comment.id] ?? comment.replies
}

function showMore(comment: Comment): boolean {
  return comment.reply_count > repliesOf(comment).length
}

async function onDelete(comment: Comment) {
  const extra = comment.reply_count > 0 ? `连同 ${comment.reply_count} 条回复一起删除,` : ''
  if (!window.confirm(`${extra}删除后不可恢复。确定删除这条评论?`)) return
  try {
    await feedApi.deleteComment(props.postId, comment.id)
    if (comment.parent_id !== null && expanded.value[comment.parent_id]) {
      expanded.value = {
        ...expanded.value,
        [comment.parent_id]: expanded.value[comment.parent_id].filter(
          (item) => item.id !== comment.id,
        ),
      }
    }
    emit('deleted', comment)
  } catch (e) {
    error.value = parseApiError(e).message
  }
}
</script>

<template>
  <section class="comment-list">
    <h2 class="comment-list__title">评论 {{ props.count }}</h2>

    <p v-if="props.comments.length === 0" class="comment-list__empty">还没有评论,来说两句</p>

    <ul class="comment-list__items">
      <li v-for="comment in props.comments" :key="comment.id" class="comment-list__item">
        <AppAvatar :src="comment.author.avatar_url" :name="comment.author.nickname" :size="32" />
        <div class="comment-list__body">
          <span class="comment-list__name">{{ comment.author.nickname || '神秘人' }}</span>
          <p class="comment-list__text">{{ comment.text }}</p>
          <div class="comment-list__actions">
            <button type="button" class="comment-list__reply" @click="startReply(comment)">
              回复
            </button>
            <button
              v-if="isMine(comment)"
              type="button"
              class="comment-list__delete"
              @click="onDelete(comment)"
            >
              删除
            </button>
          </div>

          <ul v-if="repliesOf(comment).length" class="comment-list__replies">
            <li v-for="reply in repliesOf(comment)" :key="reply.id" class="comment-list__reply-item">
              <AppAvatar :src="reply.author.avatar_url" :name="reply.author.nickname" :size="24" />
              <div class="comment-list__body">
                <span class="comment-list__name">{{ reply.author.nickname || '神秘人' }}</span>
                <p class="comment-list__text">
                  <span v-if="reply.reply_to" class="comment-list__at">
                    回复 @{{ reply.reply_to.nickname }}
                  </span>
                  {{ reply.text }}
                </p>
                <div class="comment-list__actions">
                  <button type="button" class="comment-list__reply" @click="startReply(reply)">
                    回复
                  </button>
                  <button
                    v-if="isMine(reply)"
                    type="button"
                    class="comment-list__delete"
                    @click="onDelete(reply)"
                  >
                    删除
                  </button>
                </div>
              </div>
            </li>
          </ul>

          <button
            v-if="showMore(comment)"
            type="button"
            class="comment-list__more"
            :disabled="expanding === comment.id"
            @click="expandReplies(comment)"
          >
            查看全部 {{ comment.reply_count }} 条回复
          </button>
        </div>
      </li>
    </ul>

    <AppButton v-if="hasMore" variant="ghost" block :loading="loadingMore" @click="loadMore">
      加载更多评论
    </AppButton>

    <div class="comment-list__form">
      <div v-if="replyTo" class="comment-list__reply-hint">
        <span>回复 @{{ replyTo.author.nickname || '神秘人' }}</span>
        <button type="button" aria-label="取消回复" @click="cancelReply">×</button>
      </div>
      <div class="comment-list__form-row">
        <AppInput
          v-model="text"
          :placeholder="replyTo ? `回复 @${replyTo.author.nickname || '神秘人'}…` : '说点什么…'"
          :maxlength="200"
          :error="error"
          @enter="onSubmit"
        />
        <AppButton class="comment-list__submit" :loading="submitting" @click="onSubmit">
          发送
        </AppButton>
      </div>
    </div>
  </section>
</template>

<style scoped>
.comment-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}
.comment-list__title {
  margin: 0;
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
}
.comment-list__empty {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.comment-list__items {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  margin: 0;
  padding: 0;
  list-style: none;
}
.comment-list__item {
  display: flex;
  gap: var(--space-sm);
}
.comment-list__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  min-width: 0;
}
.comment-list__name {
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.comment-list__text {
  margin: 0;
  font-size: var(--text-body);
}
.comment-list__at {
  color: var(--color-text3);
}
.comment-list__actions {
  display: flex;
  gap: var(--space-md);
}
.comment-list__actions button,
.comment-list__more {
  padding: 0;
  border: none;
  background: none;
  font-size: var(--text-caption);
  color: var(--color-text2);
  cursor: pointer;
}
.comment-list__more {
  align-self: flex-start;
}
.comment-list__replies {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin: var(--space-xs) 0 0;
  padding: 0;
  list-style: none;
}
.comment-list__reply-item {
  display: flex;
  gap: var(--space-xs);
}
.comment-list__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}
.comment-list__form-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
}
.comment-list__form-row > :first-child {
  flex: 1;
}
.comment-list__submit {
  flex: none;
}
.comment-list__reply-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.comment-list__reply-hint button {
  border: none;
  background: none;
  font-size: var(--text-body);
  color: var(--color-text3);
  cursor: pointer;
}
</style>
```

- [ ] **Step 5: 改 `PostDetailPage.vue` 的计数**

`onCommentAdded` 之后追加:

```ts
function onCommentDeleted(comment: Comment) {
  if (comment.parent_id === null) {
    comments.value = comments.value.filter((item) => item.id !== comment.id)
  } else {
    comments.value = comments.value.map((item) =>
      item.id === comment.parent_id
        ? {
            ...item,
            replies: item.replies.filter((reply) => reply.id !== comment.id),
            reply_count: Math.max(0, item.reply_count - 1),
          }
        : item,
    )
  }
  if (post.value) {
    const removed = comment.parent_id === null ? 1 + comment.reply_count : 1
    post.value.comment_count = Math.max(0, post.value.comment_count - removed)
  }
}
```

模板里 `CommentList` 增加事件:

```vue
      <CommentList
        :post-id="Number(props.id)"
        :comments="comments"
        :count="post.comment_count"
        @added="onCommentAdded"
        @deleted="onCommentDeleted"
      />
```

- [ ] **Step 6: 更新 `post-detail-page.spec.ts` 的评论夹具**

把文件里的 `const comment = {...}` 替换为:

```ts
const comment = {
  id: 1,
  author: { user_id: 4, nickname: '阿哲', avatar_url: null },
  text: '不错',
  parent_id: null,
  reply_to: null,
  reply_count: 0,
  replies: [],
  created_at: '2026-10-01T11:00:00Z',
}
```

并把「发表评论后出现在列表最前」里 POST 的响应体补上同样的四个字段(`parent_id: null`、
`reply_to: null`、`reply_count: 0`、`replies: []`)。

- [ ] **Step 7: 跑测试与门禁**

```bash
cd web
npm run test:run
npm run type-check
npm run lint
npm run test:coverage
```

Expected: 全绿;覆盖率不低于 70/60/70/70。

- [ ] **Step 8: 提交**

```bash
git add web/src/api/types.ts web/src/api/feed.ts web/src/features/square/CommentList.vue web/src/features/square/PostDetailPage.vue web/tests/component/comment-list.spec.ts web/tests/component/post-detail-page.spec.ts
git commit -m "feat(web/square): 评论楼中楼、回复与删除"
```

---

### Task 11: 全量门禁与收尾回填

**Files:**
- Modify: `CLAUDE.md`、`README.md`、`docs/superpowers/specs/2026-10-20-square-comment-threads-design.md`(状态行)

**Interfaces:**
- Consumes: Task 1–10 全部产物
- Produces: 三端全绿 + 里程碑记录

- [ ] **Step 1: 跑三端全量门禁**

```bash
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test

cd ../app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test

cd ../web
npm run type-check
npm run lint
npm run test:coverage
```

Expected: 后端全绿(含 `ApiDocsCoverageTests` / `CommentCoverageTests`)、`analyze` 零告警、App 测试全绿、Web 零错误零告警且覆盖率达标。

- [ ] **Step 2: 回填 spec 状态**

`docs/superpowers/specs/2026-10-20-square-comment-threads-design.md` 第 3 行改为:

```markdown
日期:2026-10-20 · 状态:已交付(2026-10-20;三端门禁全绿)
```

- [ ] **Step 3: 回填 `CLAUDE.md`**

里程碑表末尾追加一行:

```markdown
| 2026-10-20 | 广场评论「楼中楼」交付(两级楼层 + 内嵌前 2 条回复 + 展开接口 + 回复即 @ 的 IM 灰条提醒 + 作者删评论;接口 36→38,后端 <实测数> / App <实测数> / Web <实测数> 测试绿) |
```

> `<实测数>` 用 Step 1 的实际输出替换(`manage.py test` 的 `Ran N tests`、
> `flutter test` 的 `+N`、`vitest` 的 `Tests  N passed`),不要照抄旧批次数。

「下一步」整段替换为:

```markdown
**下一步**:广场评论楼中楼已交付。P1-4 推送待真机验极光 key(P1-4b 聊天推送待备案域名 + HTTPS);已读回执待 IM 升旗舰版。上线合规轨按 `2026-09-18-launch-execution.md` 并行推进 S0/S1(主体与备案由用户线下办理,Claude 侧可执行项:T-06 软著材料、T-10 隐私政策页部署、T-12 安全评估报告、T-18 备份策略、T-19 PIPIA/未成年人保护方案)。
```

后端接口表 `/posts` 系列那行说明改为:

```markdown
| `/posts` 系列、`POST /reports`、`GET/POST/DELETE /blocks`、`GET /presence` | 广场 / 举报 / 拉黑 / 在线状态,细节见各 spec 与 pitfalls(评论支持两级楼中楼与回复提醒) |
```

- [ ] **Step 4: 回填 `README.md`**

1. 第 89 行改为:

```markdown
- 广场动态流:发布、点赞、评论(两级楼中楼 + 回复提醒)
```

2. 「可能继续做的方向」清单里删除这一条:

```markdown
- [ ] 广场动态的评论楼中楼与 @ 提醒
```

- [ ] **Step 5: 提交**

```bash
git add CLAUDE.md README.md docs/superpowers/specs/2026-10-20-square-comment-threads-design.md
git commit -m "docs: 广场评论楼中楼收尾回填(验收结果与里程碑)"
```

- [ ] **Step 6: 开 PR**

```bash
git push -u origin feat/square-comment-threads
```

然后在 GitHub 上以 `feat/square-comment-threads` → `master` 开 PR,标题
`feat: 广场评论楼中楼与回复提醒`,描述里贴三端门禁结果与手测清单(spec §10)。

---

## 自检清单(写完后逐条核对)

- [ ] 后端:模型、归一化、列表内嵌、回复列表、删除、提醒分流都有对应任务;
- [ ] App:模型/仓库/控制器、楼层、回复态、删除、Hero 都有对应任务;
- [ ] Web:类型/api、两层组件、回复态、删除、计数都有对应任务;
- [ ] 文档:5.8/5.9 改字段、5.11/5.12 新增、README 计数 36→38 都写了;
- [ ] 类型一致:`create_comment(post, author, text, parent=None)`、`visible_comments(post, viewer)`、
      `notify_comment_created(comment)` 在 Task 2/3/6 中同名同参;
      `CommentThread` 的参数在 Task 9 前后一致;
- [ ] 没有「TBD / 类似 Task N / 自行补充」类占位。
