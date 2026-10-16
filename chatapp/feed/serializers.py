"""广场动态的序列化器与入参校验。

设计要点:
    1. 作者信息统一走 ``author_brief``:昵称取本地资料,头像取第一张**已过审**照片;
    2. 图片在入参阶段就用 ``ImageField.run_validation`` 过一遍 PIL 校验,
       避免把非图片文件写进磁盘;
    3. 正文与评论写入前统一过 ``moderation.text_check`` 的违禁词检查。
"""

from rest_framework import serializers

from moderation.models import ReportType
from moderation.text_check import find_blocked_word
from users.models import PhotoStatus

from .models import Post, PostComment


def author_brief(user, request):
    """构造动态/评论里的作者简要信息。

    Args:
        user: 作者用户实例。
        request: 当前请求,用于把头像拼成绝对 URL。

    Returns:
        ``{user_id, nickname, avatar_url}``;无资料或无已过审照片时对应字段为空。
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

    class Meta:
        model = Post
        fields = ["id", "author", "text", "images", "like_count", "comment_count",
                  "liked_by_me", "created_at"]

    def get_author(self, post):
        """取动态作者的简要信息。

        Args:
            post: 动态对象。

        Returns:
            ``author_brief`` 的结果。
        """
        return author_brief(post.author, self.context["request"])

    def get_images(self, post):
        """取全部配图的绝对 URL。

        Args:
            post: 动态对象。

        Returns:
            URL 列表,按 ``order`` 排序。
        """
        request = self.context["request"]
        return [request.build_absolute_uri(image.file.url) for image in post.images.all()]


class PostCommentSerializer(serializers.ModelSerializer):
    """评论的对外表示,作者信息与动态卡同源。"""

    author = serializers.SerializerMethodField()

    class Meta:
        model = PostComment
        fields = ["id", "author", "text", "created_at"]

    def get_author(self, comment):
        """取评论作者的简要信息。

        Args:
            comment: 评论对象。

        Returns:
            ``author_brief`` 的结果。
        """
        return author_brief(comment.author, self.context["request"])


class PostCreateSerializer(serializers.Serializer):
    """发布动态的入参:正文可选,配图从 multipart 的 ``images`` 取。"""

    text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate_text(self, value):
        """校验正文:违禁词检查 + 去首尾空白。

        Args:
            value: 提交的正文。

        Returns:
            去空白后的正文。

        Raises:
            serializers.ValidationError: 命中违禁词。
        """
        if value and find_blocked_word(value):
            raise serializers.ValidationError("内容包含违规内容,请修改")
        return value.strip()

    def validate(self, attrs):
        """校验图文整体约束。

        Args:
            attrs: 已通过字段级校验的数据。

        Returns:
            通过校验的数据。

        Raises:
            serializers.ValidationError: 图文全空、图片超过 9 张、单张超过 5MB,
                或文件不是有效图片。
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
    """发表评论的入参。"""

    text = serializers.CharField(max_length=200)

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


class PostReportCreateSerializer(serializers.Serializer):
    """举报动态的入参。"""

    type = serializers.ChoiceField(choices=ReportType.choices)
    detail = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
