from rest_framework import serializers

from users.models import PhotoStatus

from .models import Block, Report, ReportType


class ReportCreateSerializer(serializers.Serializer):
    target_user_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=ReportType.choices)
    detail = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ["id", "type", "status"]


class BlockCreateSerializer(serializers.Serializer):
    target_user_id = serializers.IntegerField()


class BlockSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="blocked.id", read_only=True)
    blocked_at = serializers.DateTimeField(source="created_at", read_only=True)
    nickname = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = Block
        fields = ["user_id", "nickname", "avatar_url", "blocked_at"]

    def get_nickname(self, block):
        profile = getattr(block.blocked, "profile", None)
        return profile.nickname if profile else ""

    def get_avatar_url(self, block):
        for photo in block.blocked.photos.all():
            if photo.status == PhotoStatus.APPROVED:
                return self.context["request"].build_absolute_uri(photo.file.url)
        return None
