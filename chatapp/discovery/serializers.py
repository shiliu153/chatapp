"""候选卡片与滑卡入参的序列化。

设计要点:
    ``CandidateSerializer`` 只暴露滑卡决策需要的信息,并**只返回已过审照片** ——
    待审核与已驳回的照片绝不能出现在候选卡上。
"""

from rest_framework import serializers

from users.models import PhotoStatus, Profile
from users.serializers import PhotoSerializer, TagSerializer

from .models import Swipe, SwipeAction


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


class LikeReceivedSerializer(serializers.ModelSerializer):
    """「喜欢我的人」列表项:对方公开资料 + 喜欢时间。"""

    user_id = serializers.IntegerField(source="swiper.id", read_only=True)
    im_user_id = serializers.CharField(source="swiper.im_user_id", read_only=True)
    nickname = serializers.CharField(source="swiper.profile.nickname", read_only=True)
    gender = serializers.CharField(source="swiper.profile.gender", read_only=True)
    age = serializers.IntegerField(source="swiper.profile.age", read_only=True, allow_null=True)
    city = serializers.CharField(source="swiper.profile.city", read_only=True)
    bio = serializers.CharField(source="swiper.profile.bio", read_only=True)
    tags = TagSerializer(source="swiper.profile.tags", many=True, read_only=True)
    photos = serializers.SerializerMethodField()
    liked_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Swipe
        fields = ["user_id", "im_user_id", "nickname", "gender", "age", "city", "bio",
                  "tags", "photos", "liked_at"]

    def get_photos(self, swipe):
        """只返回已过审照片。

        Args:
            swipe: 一条「对方喜欢我」的记录。

        Returns:
            已过审照片的序列化数据。
        """
        approved = [p for p in swipe.swiper.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data
