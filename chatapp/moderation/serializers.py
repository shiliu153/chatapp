"""举报与拉黑的序列化器。

设计要点:
    ``BlockSerializer`` 会为每条黑名单记录附带对方的昵称与头像(取第一张已过审照片),
    以便前端直接渲染黑名单列表,不需要再逐条查资料。
"""

from rest_framework import serializers

from users.models import PhotoStatus

from .models import Block, Report, ReportType


class ReportCreateSerializer(serializers.Serializer):
    """举报入参。"""

    target_user_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=ReportType.choices)
    detail = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ReportSerializer(serializers.ModelSerializer):
    """举报的对外表示(只回执最必要的三项)。"""

    class Meta:
        model = Report
        fields = ["id", "type", "status"]


class BlockCreateSerializer(serializers.Serializer):
    """拉黑入参。"""

    target_user_id = serializers.IntegerField()


class BlockSerializer(serializers.ModelSerializer):
    """黑名单条目的对外表示,已内联对方的昵称与头像。"""

    user_id = serializers.IntegerField(source="blocked.id", read_only=True)
    blocked_at = serializers.DateTimeField(source="created_at", read_only=True)
    nickname = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = Block
        fields = ["user_id", "nickname", "avatar_url", "blocked_at"]

    def get_nickname(self, block) -> str:
        """取被拉黑方的昵称。

        参数说明:
            block: 拉黑记录。

        返回参数:
            昵称;对方没有资料行时返回空串。

        使用示例:
            ``BlockSerializer(block, context={"request": request}).data["nickname"]``(见
            ``moderation/views.py`` 的 ``blocks``)

        备注信息:
            对方账号可能存在但没有资料行,此时返回空串而不是抛异常,前端按空昵称渲染。
        """
        profile = getattr(block.blocked, "profile", None)
        return profile.nickname if profile else ""

    def get_avatar_url(self, block) -> str | None:
        """取被拉黑方第一张已过审照片的绝对 URL。

        参数说明:
            block: 拉黑记录。

        返回参数:
            头像绝对 URL;没有已过审照片时返回 ``None``。

        使用示例:
            ``BlockSerializer(block, context={"request": request}).data["avatar_url"]``(见
            ``moderation/views.py`` 的 ``blocks``)

        备注信息:
            按 ``photos`` 的默认顺序取第一张 ``PhotoStatus.APPROVED``,未过审的一律跳过;
            用 ``self.context["request"].build_absolute_uri`` 拼绝对地址,因此序列化时必须
            传 ``context={"request": request}``。
        """
        for photo in block.blocked.photos.all():
            if photo.status == PhotoStatus.APPROVED:
                return self.context["request"].build_absolute_uri(photo.file.url)
        return None
