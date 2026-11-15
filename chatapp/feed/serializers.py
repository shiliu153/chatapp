"""广场动态的序列化器与入参校验。

设计要点:
    1. 作者信息统一走 ``author_brief``:昵称取本地资料,头像取第一张**已过审**照片;
    2. 图片在入参阶段就用 ``ImageField.run_validation`` 过一遍 PIL 校验,
       避免把非图片文件写进磁盘;
    3. 正文与评论写入前统一过 ``moderation.text_check`` 的违禁词检查;
    4. ``liked_by_me`` / ``is_favorited`` 只读查询集上的**注解值**,序列化器里
       不做任何逐条查询(否则广场一页 20 条 = 20 次 SQL,查询预算会红)。
"""

from drf_spectacular.utils import extend_schema_field, inline_serializer
from rest_framework import serializers

from moderation.models import ReportType
from moderation.text_check import find_blocked_word
from users.models import PhotoStatus

from .models import Post, PostComment

# 作者摘要与被回复者摘要是纯字典,给 schema 用的内联序列化器
AUTHOR_BRIEF_SCHEMA = inline_serializer("AuthorBrief", fields={
    "user_id": serializers.IntegerField(),
    "nickname": serializers.CharField(),
    "avatar_url": serializers.CharField(allow_null=True),
})
REPLY_TO_SCHEMA = inline_serializer("ReplyTo", fields={
    "user_id": serializers.IntegerField(),
    "nickname": serializers.CharField(),
})
# 点赞列表 ``results[]`` 的元素。组件名 ``PostLiker`` 是**跨栈契约**:
# App / Web 的手写类型拿它做字段名断言,改名会让那两单的 CI 直接红。
POST_LIKER_SCHEMA = inline_serializer("PostLiker", fields={
    "user_id": serializers.IntegerField(),
    "nickname": serializers.CharField(),
    "avatar_url": serializers.CharField(allow_null=True),
    "liked_at": serializers.DateTimeField(),
})


def author_brief(user, request):
    """构造动态/评论里的作者简要信息。

    参数说明:
        user: 作者用户实例。
        request: 当前请求,用于把头像拼成绝对 URL。

    返回参数:
        ``{user_id, nickname, avatar_url}``;无资料或无已过审照片时对应字段为空。

    使用示例:
        ``brief = author_brief(like.user, request)``(见 ``feed/views.py`` 的 ``post_likes``)

    备注信息:
        昵称取本地资料,资料缺失时为空串;头像只认第一张**已过审**照片,
        未过审的图片不会出现在任何列表里。
    """
    profile = getattr(user, "profile", None)
    avatar_url = None
    for photo in user.photos.all():
        if photo.status == PhotoStatus.APPROVED:
            avatar_url = request.build_absolute_uri(photo.file.url)
            break
    return {"user_id": user.id, "nickname": profile.nickname if profile else "",
            "avatar_url": avatar_url}


class PostSerializer(serializers.ModelSerializer):
    """动态的对外表示,含作者、配图与互动计数。"""

    author = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    like_count = serializers.IntegerField(read_only=True, default=0)
    comment_count = serializers.IntegerField(read_only=True, default=0)
    liked_by_me = serializers.BooleanField(read_only=True, default=False)
    is_favorited = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Post
        fields = ["id", "author", "text", "images", "like_count", "comment_count",
                  "liked_by_me", "is_favorited", "created_at"]

    @extend_schema_field(AUTHOR_BRIEF_SCHEMA)
    def get_author(self, post):
        """取动态作者的简要信息。

        参数说明:
            post: 动态对象。

        返回参数:
            ``author_brief`` 的结果。

        使用示例:
            ``PostSerializer(post, context={"request": request}).data["author"]``(见 ``feed/views.py`` 的 ``post_detail``)

        备注信息:
            走 ``author_brief``;``request`` 从 ``self.context`` 取,序列化时必须带 context,
            否则取不到请求、拼不出绝对头像 URL。
        """
        return author_brief(post.author, self.context["request"])

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_images(self, post):
        """取全部配图的绝对 URL。

        参数说明:
            post: 动态对象。

        返回参数:
            URL 列表,按 ``order`` 排序。

        使用示例:
            ``PostSerializer(post, context={"request": request}).data["images"]``(见 ``feed/views.py`` 的 ``post_detail``)

        备注信息:
            顺序由模型的 ``ordering`` 决定,视图侧用 ``prefetch_related("images")``
            预取,这里不再逐条查库。
        """
        request = self.context["request"]
        return [request.build_absolute_uri(image.file.url) for image in post.images.all()]


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

    @extend_schema_field(AUTHOR_BRIEF_SCHEMA)
    def get_author(self, comment):
        """取评论作者的简要信息。

        参数说明:
            comment: 评论对象。

        返回参数:
            ``author_brief`` 的结果。

        使用示例:
            ``PostCommentSerializer(comment, context={"request": request}).data["author"]``(见 ``feed/views.py`` 的 ``post_comments``)

        备注信息:
            与动态作者同一套摘要口径(见 ``author_brief``);作者已注销时昵称为空串。
        """
        return author_brief(comment.author, self.context["request"])

    def _visible_replies(self, comment):
        """取该评论下的可见回复(优先用视图预取的结果)。

        参数说明:
            comment: 顶级评论。

        返回参数:
            按时间正序的回复列表;结果会缓存在实例上,避免重复查询。

        使用示例:
            ``replies = self._visible_replies(comment)[:2]``(见本文件 ``get_replies``)

        备注信息:
            优先用视图 ``Prefetch(..., to_attr="visible_replies")`` 的结果;没有预取时现查
            并写回 ``comment.visible_replies``,同一实例多次序列化不会重复查库。
        """
        cached = getattr(comment, "visible_replies", None)
        if cached is not None:
            return cached
        cached = list(comment.replies.select_related("author__profile", "reply_to__profile")
                      .prefetch_related("author__photos"))
        comment.visible_replies = cached
        return cached

    @extend_schema_field(REPLY_TO_SCHEMA)
    def get_reply_to(self, comment):
        """取被回复者的简要信息。

        参数说明:
            comment: 评论对象。

        返回参数:
            ``{user_id, nickname}``;顶级评论或被回复者已注销时为 ``None``。

        使用示例:
            ``PostCommentSerializer(comment, context={"request": request}).data["reply_to"]``(见 ``feed/views.py`` 的 ``post_comments``)

        备注信息:
            只读 ``comment.reply_to``,不额外查库;该外键在作者注销时置空。
        """
        user = comment.reply_to
        if user is None:
            return None
        profile = getattr(user, "profile", None)
        return {"user_id": user.id, "nickname": profile.nickname if profile else ""}

    def get_reply_count(self, comment) -> int:
        """取该楼层可见回复的总数(回复对象恒为 0)。

        参数说明:
            comment: 评论对象。

        返回参数:
            可见回复条数。

        使用示例:
            ``PostCommentSerializer(comment, context={"request": request}).data["reply_count"]``(见 ``feed/views.py`` 的 ``post_comments``)

        备注信息:
            层级只有两级,所以回复对象本身恒为 0;顶层评论的计数已剔除被拉黑 / 被重封禁的回复者。
        """
        if comment.parent_id is not None:
            return 0
        return len(self._visible_replies(comment))

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_replies(self, comment):
        """取该楼层内嵌的前两条回复(回复对象恒为空)。

        参数说明:
            comment: 评论对象。

        返回参数:
            回复对象列表,最多 2 条。

        使用示例:
            ``PostCommentSerializer(comment, context={"request": request}).data["replies"]``(见 ``feed/views.py`` 的 ``post_comments``)

        备注信息:
            只内嵌前两条,完整回复列表走 ``GET .../comments/{id}/replies``;回复对象内
            ``replies`` 恒为空、``reply_count`` 恒为 0,避免响应随层级膨胀。
        """
        if comment.parent_id is not None:
            return []
        replies = self._visible_replies(comment)[:2]
        return PostCommentSerializer(replies, many=True, context=self.context).data


class PostCreateSerializer(serializers.Serializer):
    """发布动态的入参:正文可选,配图从 multipart 的 ``images`` 取。"""

    text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate_text(self, value):
        """校验正文:违禁词检查 + 去首尾空白。

        参数说明:
            value: 提交的正文。

        返回参数:
            去空白后的正文。

        使用示例:
            ``serializer = PostCreateSerializer(data=request.data, context={"request": request}); serializer.is_valid(raise_exception=True)``(见 ``feed/views.py`` 的 ``_create_post``)

        备注信息:
            命中违禁词时主动抛 ``serializers.ValidationError``(400);空串放行,
            「图文全空」由 ``validate`` 整体判定。
        """
        if value and find_blocked_word(value):
            raise serializers.ValidationError("内容包含违规内容,请修改")
        return value.strip()

    def validate(self, attrs):
        """校验图文整体约束。

        参数说明:
            attrs: 已通过字段级校验的数据。

        返回参数:
            通过校验的数据。

        使用示例:
            ``serializer.is_valid(raise_exception=True)``(见 ``feed/views.py`` 的 ``_create_post``)

        备注信息:
            图片从 ``self.context["request"].FILES`` 取,所以实例化时必须带 context。
            图文全空、图片超过 9 张、单张超过 5MB,或文件不是有效图片时
            主动抛 ``serializers.ValidationError``(400)。
        """
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


class PostCommentCreateSerializer(serializers.Serializer):
    """发表评论的入参;``parent_id`` 非空表示这是一条回复。"""

    text = serializers.CharField(max_length=200)
    parent_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_text(self, value):
        """校验评论内容:违禁词检查、去空白、非空。

        参数说明:
            value: 提交的评论内容。

        返回参数:
            去空白后的评论内容。

        使用示例:
            ``serializer = PostCommentCreateSerializer(data=request.data); serializer.is_valid(raise_exception=True)``(见 ``feed/views.py`` 的 ``post_comments``)

        备注信息:
            命中违禁词或去空白后为空时主动抛 ``serializers.ValidationError``(400)。
        """
        if find_blocked_word(value):
            raise serializers.ValidationError("评论包含违规内容,请修改")
        text = value.strip()
        if not text:
            raise serializers.ValidationError("评论不能为空")
        return text


class PostReportCreateSerializer(serializers.Serializer):
    """举报动态的入参。"""

    type = serializers.ChoiceField(choices=ReportType.choices)
    detail = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
