"""候选卡片与滑卡入参的序列化。

设计要点:
    ``CandidateSerializer`` 只暴露滑卡决策需要的信息,并**只返回已过审照片** ——
    待审核与已驳回的照片绝不能出现在候选卡上。

文件信息:
    文件名称          discovery/serializers.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from users.models import PhotoStatus, Profile, ProfileVisit
from users.serializers import PhotoSerializer, TagSerializer

from .models import Swipe, SwipeAction


class CandidateSerializer(serializers.ModelSerializer):
    """候选卡片的对外表示。

    参数说明:
        instance: 待序列化的 ``Profile`` 实例或查询集。
        many: 串行化多条时传 ``True``,默认 ``False``。
        context: 透传给嵌套序列化器的上下文(至少带 ``request``)。

    返回参数:
        无返回值;实例化后由 ``.data`` 取字典或字典列表。

    使用示例:
        ``CandidateSerializer(profile, context={"request": request}).data``

    备注信息:
        只暴露滑卡决策需要的字段;``photos`` 由 :meth:`get_photos` 过滤成已过审照片,
        客户端不能从这个响应里拿到待审或已驳回的图。
    """

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

        参数说明:
            profile: 候选人的资料。

        返回参数:
            已过审照片的序列化数据。

        使用示例:
            ``serializer.get_photos(profile)``

        备注信息:
            在 Python 侧按 ``status == PhotoStatus.APPROVED`` 过滤,过滤条件不带进 SQL,
            ``profile.user.photos.all()`` 会先取全部照片再筛选。
        """
        approved = [p for p in profile.user.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data


class DailyCandidatesSerializer(serializers.Serializer):
    """「今日精选」的响应:当天日期 + 与候选卡同构的卡片数组(批次 S)。

    ``date`` 是服务端算种子用的日期,客户端据此判断「今天已看过」;
    只用于 ``@extend_schema`` 声明响应形状,视图直接拼字典返回。

    参数说明:
        无;声明用序列化器,运行时不实例化。

    返回参数:
        无返回值;形状为 ``{"date": date, "candidates": [候选卡]}``。

    使用示例:
        ``@extend_schema(responses=DailyCandidatesSerializer)``

    备注信息:
        ``date`` 必须与服务端算种子用的日期同源,客户端自行推算会跨时区错位。
    """

    date = serializers.DateField(help_text="本次精选对应的日期(服务端时区)")
    candidates = CandidateSerializer(many=True, help_text="精选卡片,字段与候选卡一致")


class SwipeSerializer(serializers.Serializer):
    """滑卡入参:目标用户与动作。

    参数说明:
        data: 客户端提交的 ``{"target_user_id": int, "action": "like"|"pass"}``。

    返回参数:
        无返回值;校验通过后 ``.validated_data`` 给出 ``target_user_id`` 与 ``action``。

    使用示例:
        ``SwipeSerializer(data=request.data)``

    备注信息:
        ``action`` 只接受 :class:`SwipeAction` 的两个取值,其余取值校验失败返回 ``400``;
        字段本身不做存在性校验,目标账号是否存在由视图判定。
    """

    target_user_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=SwipeAction.choices)


class SwipeUndoSerializer(serializers.Serializer):
    """撤销滑卡的响应:撤销结果与被撤销的目标(批次 O)。

    只用于 ``@extend_schema`` 声明响应形状,视图直接拼字典返回。

    参数说明:
        无;声明用序列化器,运行时不实例化。

    返回参数:
        无返回值;形状为 ``{"undone": bool, "target_user_id": int}``。

    使用示例:
        ``@extend_schema(responses=SwipeUndoSerializer)``

    备注信息:
        撤销失败不进这个形状,直接由 :class:`SwipeUndoUnavailable` 抛错误信封。
    """

    undone = serializers.BooleanField(help_text="是否撤销成功;失败走错误信封")
    target_user_id = serializers.IntegerField(help_text="被撤销的那次滑卡的目标账号 ID")


class SwipeQuotaSerializer(serializers.Serializer):
    """每日喜欢额度的响应(批次 O)。

    ``like_limit = 0`` 表示不限,此时 ``likes_used`` 恒为 0、``likes_remaining`` 为 ``null``。

    参数说明:
        无;声明用序列化器,运行时不实例化。

    返回参数:
        无返回值;形状与 ``quota.quota_snapshot`` 的字典一致。

    使用示例:
        ``@extend_schema(responses=SwipeQuotaSerializer)``

    备注信息:
        字段取值全部来自 ``quota.quota_snapshot``,视图不自行计算剩余次数。
    """

    like_limit = serializers.IntegerField(help_text="每日喜欢上限,0 = 不限")
    likes_used = serializers.IntegerField(help_text="今天已用掉的喜欢次数")
    likes_remaining = serializers.IntegerField(
        allow_null=True, help_text="今天还剩多少次;不限时为 null")


class LikeReceivedSerializer(serializers.ModelSerializer):
    """「喜欢我的人」列表项:对方公开资料 + 喜欢时间。

    参数说明:
        instance: ``Swipe`` 实例或查询集(方向是「喜欢我」)。
        many: 串行化多条时传 ``True``,默认 ``False``。
        context: 透传给嵌套序列化器的上下文。

    返回参数:
        无返回值;实例化后由 ``.data`` 取字典或字典列表。

    使用示例:
        ``LikeReceivedSerializer(swipes, many=True, context={"request": request}).data``

    备注信息:
        所有资料字段都取自 ``swiper`` 一侧,``photos`` 同样只含已过审照片。
    """

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

        参数说明:
            swipe: 一条「对方喜欢我」的记录。

        返回参数:
            已过审照片的序列化数据。

        使用示例:
            ``serializer.get_photos(swipe)``

        备注信息:
            在 Python 侧按 ``status == PhotoStatus.APPROVED`` 过滤,与候选卡同口径。
        """
        approved = [p for p in swipe.swiper.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data

class VisitSerializer(serializers.ModelSerializer):
    """「谁看过我」列表项:对方公开资料 + 最近访问时间。

    参数说明:
        instance: ``ProfileVisit`` 实例或查询集。
        many: 串行化多条时传 ``True``,默认 ``False``。
        context: 透传给嵌套序列化器的上下文。

    返回参数:
        无返回值;实例化后由 ``.data`` 取字典或字典列表。

    使用示例:
        ``VisitSerializer(visits, many=True, context={"request": request}).data``

    备注信息:
        所有资料字段都取自 ``viewer`` 一侧;``visited_at`` 取 ``last_at``
        —— 同一访客多次访问只保留一行,时间由业务侧持续刷新。
    """

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

        参数说明:
            visit: 一条访客记录。

        返回参数:
            已过审照片的序列化数据。

        使用示例:
            ``serializer.get_photos(visit)``

        备注信息:
            在 Python 侧按 ``status == PhotoStatus.APPROVED`` 过滤,与候选卡同口径。
        """
        approved = [p for p in visit.viewer.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data