"""候选卡片与滑卡入参的序列化。

设计要点:
    ``CandidateSerializer`` 只暴露滑卡决策需要的信息,并**只返回已过审照片** ——
    待审核与已驳回的照片绝不能出现在候选卡上。
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from users.models import PhotoStatus, Profile, ProfileVisit
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

    @extend_schema_field(PhotoSerializer(many=True))
    def get_photos(self, profile):
        """只返回已过审的照片。

        Args:
            profile: 候选人的资料。

        Returns:
            已过审照片的序列化数据。
        """
        approved = [p for p in profile.user.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data


class DailyCandidatesSerializer(serializers.Serializer):
    """「今日精选」的响应:当天日期 + 与候选卡同构的卡片数组(批次 S)。

    ``date`` 是服务端算种子用的日期,客户端据此判断「今天已看过」;
    只用于 ``@extend_schema`` 声明响应形状,视图直接拼字典返回。
    """

    date = serializers.DateField(help_text="本次精选对应的日期(服务端时区)")
    candidates = CandidateSerializer(many=True, help_text="精选卡片,字段与候选卡一致")


class SwipeSerializer(serializers.Serializer):
    """滑卡入参:目标用户与动作。"""

    target_user_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=SwipeAction.choices)


class SwipeUndoSerializer(serializers.Serializer):
    """撤销滑卡的响应:撤销结果与被撤销的目标(批次 O)。

    只用于 ``@extend_schema`` 声明响应形状,视图直接拼字典返回。
    """

    undone = serializers.BooleanField(help_text="是否撤销成功;失败走错误信封")
    target_user_id = serializers.IntegerField(help_text="被撤销的那次滑卡的目标账号 ID")


class SwipeQuotaSerializer(serializers.Serializer):
    """每日喜欢额度的响应(批次 O)。

    ``like_limit = 0`` 表示不限,此时 ``likes_used`` 恒为 0、``likes_remaining`` 为 ``null``。
    """

    like_limit = serializers.IntegerField(help_text="每日喜欢上限,0 = 不限")
    likes_used = serializers.IntegerField(help_text="今天已用掉的喜欢次数")
    likes_remaining = serializers.IntegerField(
        allow_null=True, help_text="今天还剩多少次;不限时为 null")


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

    @extend_schema_field(PhotoSerializer(many=True))
    def get_photos(self, swipe):
        """只返回已过审照片。

        Args:
            swipe: 一条「对方喜欢我」的记录。

        Returns:
            已过审照片的序列化数据。
        """
        approved = [p for p in swipe.swiper.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data

class VisitSerializer(serializers.ModelSerializer):
    """「谁看过我」列表项:对方公开资料 + 最近访问时间。"""

    user_id = serializers.IntegerField(source="viewer.id", read_only=True)
    im_user_id = serializers.CharField(source="viewer.im_user_id", read_only=True)
    nickname = serializers.CharField(source="viewer.profile.nickname", read_only=True)
    gender = serializers.CharField(source="viewer.profile.gender", read_only=True)
    age = serializers.IntegerField(source="viewer.profile.age", read_only=True, allow_null=True)
    city = serializers.CharField(source="viewer.profile.city", read_only=True)
    bio = serializers.CharField(source="viewer.profile.bio", read_only=True)
    tags = TagSerializer(source="viewer.profile.tags", many=True, read_only=True)
    photos = serializers.SerializerMethodField()
    visited_at = serializers.DateTimeField(source="last_at", read_only=True)

    class Meta:
        model = ProfileVisit
        fields = ["user_id", "im_user_id", "nickname", "gender", "age", "city", "bio",
                  "tags", "photos", "visited_at"]

    @extend_schema_field(PhotoSerializer(many=True))
    def get_photos(self, visit):
        """只返回已过审照片。

        Args:
            visit: 一条访客记录。

        Returns:
            已过审照片的序列化数据。
        """
        approved = [p for p in visit.viewer.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data