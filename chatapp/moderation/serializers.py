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

    def get_nickname(self, block):
        """取被拉黑方的昵称。

        Args:
            block: 拉黑记录。

        Returns:
            昵称;对方没有资料行时返回空串。
        """
        profile = getattr(block.blocked, "profile", None)
        return profile.nickname if profile else ""

    def get_avatar_url(self, block):
        """取被拉黑方第一张已过审照片的绝对 URL。

        Args:
            block: 拉黑记录。

        Returns:
            头像绝对 URL;没有已过审照片时返回 ``None``。
        """
        for photo in block.blocked.photos.all():
            if photo.status == PhotoStatus.APPROVED:
                return self.context["request"].build_absolute_uri(photo.file.url)
        return None
