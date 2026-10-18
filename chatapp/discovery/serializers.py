"""候选卡片与滑卡入参的序列化。

设计要点:
    ``CandidateSerializer`` 只暴露滑卡决策需要的信息,并**只返回已过审照片** ——
    待审核与已驳回的照片绝不能出现在候选卡上。
"""

from rest_framework import serializers

from users.models import PhotoStatus, Profile
from users.serializers import PhotoSerializer, TagSerializer

from .models import SwipeAction


class CandidateSerializer(serializers.ModelSerializer):
    """候选卡片的对外表示。"""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    age = serializers.IntegerField(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    photos = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = ["user_id", "nickname", "gender", "age", "city", "bio", "tags", "photos"]

    def get_photos(self, profile):
        """只返回已过审的照片。

        Args:
            profile: 候选人的资料。

        Returns:
            已过审照片的序列化数据。
        """
        approved = [p for p in profile.user.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data


class SwipeSerializer(serializers.Serializer):
    """滑卡入参:目标用户与动作。"""

    target_user_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=SwipeAction.choices)
