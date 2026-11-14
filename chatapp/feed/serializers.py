"""广场动态的序列化器与入参校验。

设计要点:
    1. 作者信息统一走 ``author_brief``:昵称取本地资料,头像取第一张**已过审**照片;
    2. 图片在入参阶段就用 ``ImageField.run_validation`` 过一遍 PIL 校验,
       避免把非图片文件写进磁盘;
    3. 正文与评论写入前统一过 ``moderation.text_check`` 的违禁词检查;
    4. ``liked_by_me`` / ``is_favorited`` 只读查询集上的**注解值**,序列化器里
       不做任何逐条查询(否则广场一页 20 条 = 20 次 SQL,查询预算会红)。

文件信息:
    文件名称          feed/serializers.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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
        ``author_brief(comment.author, request)``

    备注信息:
        昵称取 ``Profile.nickname``(无资料时为空串),头像取 ``photos`` 里第一张
        ``PhotoStatus.APPROVED`` 的照片;两者都没命中就是 ``None``,客户端按占位图渲染。
        ``user.photos`` 的预取由调用方的查询集负责,本函数不额外查库。
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
    """动态的对外表示,含作者、配图与互动计数。

    参数说明:
        instance: 待序列化的 ``Post``(或查询集,配合 ``many=True``)。
        many: 是否批量序列化,默认 ``False``。
        context: 必须带 ``request`` —— 作者头像与配图都要拼绝对 URL。

    返回参数:
        ``data`` 为 ``{id, author, text, images, like_count, comment_count,
        liked_by_me, is_favorited, created_at}``。

    使用示例:
        ``PostSerializer(page.rows, many=True, context={"request": request}).data``

    备注信息:
        四个计数/状态字段都是 ``read_only``,值全部来自查询集注解(``like_count`` /
        ``comment_count`` / ``liked_by_me`` / ``is_favorited``);查询集没注解时
        回落到默认值 0 / ``False``,不会退化成逐条查库。
    """

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
            ``author_brief`` 的结果:``{user_id, nickname, avatar_url}``。

        使用示例:
            ``serializer.get_author(post)``

        备注信息:
            依赖 ``context["request"]`` 拼绝对 URL;查询集已 ``select_related``
            作者与资料、``prefetch_related`` 照片,因此这里不产生额外 SQL。
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
            ``serializer.get_images(post)``

        备注信息:
            排序由 ``PostImage.Meta.ordering`` 保证;``images`` 必须已被预取
            (``visible_posts`` 会预取),否则每条动态多一次查询。
        """
        request = self.context["request"]
        return [request.build_absolute_uri(image.file.url) for image in post.images.all()]


class PostCommentSerializer(serializers.ModelSerializer):
    """评论的对外表示:作者摘要、被回复者、回复数与内嵌前两条回复。

    回复不再递归:回复对象的 ``replies`` 恒为空、``reply_count`` 恒为 0,
    避免响应随层级膨胀。

    参数说明:
        instance: 待序列化的 ``PostComment``(或查询集,配合 ``many=True``)。
        many: 是否批量序列化,默认 ``False``。
        context: 必须带 ``request``,用于拼作者头像的绝对 URL。

    返回参数:
        ``data`` 为 ``{id, author, text, parent_id, reply_to, reply_count,
        replies, created_at}``。

    使用示例:
        ``PostCommentSerializer(comment, context={"request": request}).data``

    备注信息:
        回复列表要靠调用方 ``prefetch_related(Prefetch("replies", ...,
        to_attr="visible_replies"))`` 预取,``_visible_replies`` 优先读这个属性;
        没有预取时才回落到自行查询。
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
            ``author_brief`` 的结果:``{user_id, nickname, avatar_url}``。

        使用示例:
            ``serializer.get_author(comment)``

        备注信息:
            ``author`` 与 ``author__photos`` 由 ``visible_comments`` 预取,
            本方法不额外查库。
        """
        return author_brief(comment.author, self.context["request"])

    def _visible_replies(self, comment):
        """取该评论下的可见回复(优先用视图预取的结果)。

        备注信息:
            视图用 ``Prefetch(..., to_attr="visible_replies")`` 预取时直接用那批对象;
            没有预取才回落到一次带 ``select_related`` / ``prefetch_related`` 的查询。
            结果缓存在实例的 ``visible_replies`` 上,``reply_count`` 与 ``replies``
            两个字段因此只查一次库。按 ``created_at, id`` 正序返回。
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
            ``serializer.get_reply_to(comment)``

        备注信息:
            ``reply_to`` 用 ``SET_NULL``,对方注销后这里自然返回 ``None``,
            客户端按「已注销」渲染,不要拿空对象兜。
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
            可见回复条数;评论本身就是回复时恒为 0。

        使用示例:
            ``serializer.get_reply_count(comment)``

        备注信息:
            计的是**过滤后**的可见回复数(排除双向拉黑与重封禁作者),
            因此可能小于数据库里的 ``replies`` 行数;计数复用 ``_visible_replies``
            的缓存,不额外查库。
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
            回复对象列表,最多 2 条;评论本身就是回复时为空列表。

        使用示例:
            ``serializer.get_replies(comment)``

        备注信息:
            只嵌前两条用于预览,更多回复走
            ``GET /api/v1/posts/{post_id}/comments/{comment_id}/replies``;
            内嵌对象递归序列化时同样带 ``context``,否则头像 URL 拼不出来。
        """
        if comment.parent_id is not None:
            return []
        replies = self._visible_replies(comment)[:2]
        return PostCommentSerializer(replies, many=True, context=self.context).data


class PostCreateSerializer(serializers.Serializer):
    """发布动态的入参:正文可选,配图从 multipart 的 ``images`` 取。

    参数说明:
        data: 已解包的请求 data;``images`` 由 ``validate`` 直接从
            ``request.FILES`` 取,不经过本序列化器的字段。
        context: 必须带 ``request``,``validate`` 要用它拿图片文件。

    返回参数:
        ``validated_data`` 为 ``{"text": <去空白后的正文>}``。

    使用示例:
        ``PostCreateSerializer(data=request.data, context={"request": request})``

    备注信息:
        图片字段不声明在本类里 —— DRF 的 ``ImageField`` 会先跑一遍校验并抛字段级错误,
        而这里需要「单张 ≤ 5MB」在前、「PIL 校验」在后,且失败要返回整体错误,
        因此统一挪到 ``validate`` 处理。
    """

    text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate_text(self, value):
        """校验正文:违禁词检查 + 去首尾空白。

        参数说明:
            value: 提交的正文。

        返回参数:
            去空白后的正文。

        使用示例:
            ``serializer.validate_text("  今天出太阳  ")``

        备注信息:
            空串直接放行(纯图动态);命中违禁词抛 ``ValidationError``,
            响应仍是标准的 ``{"code","message","request_id"}`` 错误体。
        """
        if value and find_blocked_word(value):
            raise serializers.ValidationError("内容包含违规内容,请修改")
        return value.strip()

    def validate(self, attrs):
        """校验图文整体约束。

        参数说明:
            attrs: 已通过字段级校验的数据。

        返回参数:
            通过校验的数据(原样返回 ``attrs``)。

        使用示例:
            ``serializer.is_valid(raise_exception=True)``

        备注信息:
            四类拦截:图文全空、图片超过 9 张、单张超过 5MB、文件不是有效图片。
            图片文件从 ``request.FILES.getlist("images")`` 取,本序列化器不声明该字段;
            这里只做校验,真正的重编码与配额检查在 ``views._create_post``。
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
    """发表评论的入参;``parent_id`` 非空表示这是一条回复。

    参数说明:
        data: 请求 data,需带 ``text``,可选 ``parent_id``。
        context: 本类不读 ``context``,可省略。

    返回参数:
        ``validated_data`` 为 ``{"text": <去空白后的内容>, "parent_id": <顶级评论 id 或 None>}``。

    使用示例:
        ``PostCommentCreateSerializer(data=request.data)``

    备注信息:
        ``parent_id`` 只校验「是正整数」;它是否属于该动态、是否本身是回复,
        由视图用 ``visible_comments`` 取对象时判定(取不到即 404)。
    """

    text = serializers.CharField(max_length=200)
    parent_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_text(self, value):
        """校验评论内容:违禁词检查、去空白、非空。

        参数说明:
            value: 提交的评论内容。

        返回参数:
            去空白后的评论内容。

        使用示例:
            ``serializer.validate_text("  说得对  ")``

        备注信息:
            ``CharField`` 只拦纯空白以外的长度问题;去空白后为空要在这里补一条,
            否则会落一条空评论进库。
        """
        if find_blocked_word(value):
            raise serializers.ValidationError("评论包含违规内容,请修改")
        text = value.strip()
        if not text:
            raise serializers.ValidationError("评论不能为空")
        return text


class PostReportCreateSerializer(serializers.Serializer):
    """举报动态的入参。

    参数说明:
        data: 请求 data,需带 ``type``,可选 ``detail``。
        context: 本类不读 ``context``,可省略。

    返回参数:
        ``validated_data`` 为 ``{"type": <举报类型>, "detail": <补充说明>}``。

    使用示例:
        ``PostReportCreateSerializer(data=request.data)``

    备注信息:
        ``type`` 的取值来自 ``moderation.models.ReportType.choices``,与运营审核台同一套;
        「不能举报自己的动态」与重复举报的幂等由 ``views.post_report`` 处理。
    """

    type = serializers.ChoiceField(choices=ReportType.choices)
    detail = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
