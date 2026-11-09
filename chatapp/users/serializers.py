"""资料、照片与偏好的序列化器与入参校验。

设计要点:
    1. **对外标识用户一律用 ``user_id``**(账号表主键),``ProfileSerializer.id`` 是
       资料表主键,两者不同,前端别混用;
    2. ``PublicProfileSerializer`` 是 ``ProfileSerializer`` 的公开子集,刻意不含手机号、
       生日、偏好与缺失项;
    3. 昵称与简介在写入前统一过 ``moderation.text_check`` 的违禁词检查;
    4. 公开资料卡上的 ``shared_tags`` 与关注态三个字段都支持「批量注入 context」,
       单条场景有各自的兜底查询,不会退化成 N+1;
    5. 资料语音(批次 R)在「我的资料」与「他人公开资料」里都是 ``voice: {url,
       duration_ms} | null``,``url`` 走 ``im.media_sign`` 的限时签名,与聊天语音同机制。
"""

from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from feed.services import follow_state_for_profiles
from im.voice import ALLOWED_CONTENT_TYPES as ALLOWED_AUDIO_CONTENT_TYPES
from im.voice import base_content_type
from moderation.text_check import find_blocked_word

from .models import (Gender, Photo, PhotoStatus, Preference, Profile, ProfileVoice, Tag,
                     calculate_age)


class TagSerializer(serializers.ModelSerializer):
    """标签的对外表示。"""

    class Meta:
        model = Tag
        fields = ["id", "name", "icon"]


def shared_tags_for_profiles(profiles, viewer) -> dict[int, list[dict]]:
    """批量求「若干资料 ∩ 当前用户」的共同标签(一次 SQL,供破冰文案使用)。

    标签池只有 12 个,所以按 ``(user_id, tag_id)`` 把「我 + 所有对方」的关系一次取回,
    再在内存里求交 —— 比给每个对方单独查一次 M2M 省得多,也避免 N+1
    (``config/test_query_budget.py`` 会拦)。

    Args:
        profiles: 资料对象序列;只用到 ``user_id``,``None`` 项自动忽略。
        viewer: 当前登录用户。

    Returns:
        ``{user_id: [{"id": .., "name": .., "icon": ..}, ...]}``,标签按 id 升序;
        没有交集的人**不出现在字典里**,调用方用 ``.get(user_id, [])`` 取。
    """
    viewer_id = getattr(viewer, "id", None)
    peer_ids = [profile.user_id for profile in profiles if profile is not None]
    if viewer_id is None or not peer_ids:
        return {}
    rows = (Tag.objects
            .filter(profiles__user_id__in=[viewer_id, *peer_ids])
            .values_list("profiles__user_id", "id", "name", "icon"))
    mine: set[int] = set()
    per_user: dict[int, list[tuple[int, str, str]]] = {}
    for user_id, tag_id, name, icon in rows:
        if user_id == viewer_id:
            mine.add(tag_id)
        else:
            per_user.setdefault(user_id, []).append((tag_id, name, icon))
    if not mine:
        return {}
    return {
        user_id: [{"id": tag_id, "name": name, "icon": icon}
                  for tag_id, name, icon in sorted(items) if tag_id in mine]
        for user_id, items in per_user.items()
    }


class PhotoSerializer(serializers.ModelSerializer):
    """照片的对外表示:只暴露 URL 与审核状态,不暴露存储路径。"""

    url = serializers.ImageField(source="file", read_only=True)

    class Meta:
        model = Photo
        fields = ["id", "url", "status", "order"]


class PreferenceSerializer(serializers.ModelSerializer):
    """择偶偏好的读写表示。"""

    class Meta:
        model = Preference
        fields = ["target_gender", "age_min", "age_max", "city"]

    def validate_age_min(self, value):
        """校验最小年龄下限。

        Args:
            value: 提交的最小年龄。

        Returns:
            通过校验的最小年龄。

        Raises:
            serializers.ValidationError: 小于 18 岁(合规下限)。
        """
        if value < 18:
            raise serializers.ValidationError("最小年龄不能小于 18")
        return value

    def validate(self, attrs):
        """校验年龄区间的上下界关系。

        Args:
            attrs: 已通过字段级校验的数据。

        Returns:
            通过校验的数据。

        Raises:
            serializers.ValidationError: 最小年龄大于最大年龄。
        """
        age_min = attrs.get("age_min", getattr(self.instance, "age_min", 18))
        age_max = attrs.get("age_max", getattr(self.instance, "age_max", 99))
        if age_min > age_max:
            raise serializers.ValidationError("最小年龄不能大于最大年龄")
        return attrs


def voice_payload(profile) -> dict | None:
    """把资料语音序列化成对外载荷 ``{url, duration_ms}``。

    没有语音的人返回 ``None``(API 里是 JSON ``null``),客户端据此隐藏播放器。

    Args:
        profile: 资料对象;``voice`` 反向一对一不存在时按「没录过」处理。

    Returns:
        ``{"url": 绝对签名地址, "duration_ms": 实测毫秒}``;没有语音时为 ``None``。
    """
    record = getattr(profile, "voice", None)
    if record is None:
        return None
    return {"url": record.signed_url, "duration_ms": record.duration_ms}


class ProfileVoiceSerializer(serializers.ModelSerializer):
    """资料语音的只读表示(嵌套在资料里,同时也是上传接口的响应体)。"""

    url = serializers.SerializerMethodField()

    class Meta:
        model = ProfileVoice
        fields = ["url", "duration_ms"]

    @extend_schema_field(serializers.CharField())
    def get_url(self, record):
        """播放地址:``MEDIA_BASE_URL`` + 文件路径,并附限时签名。

        Args:
            record: 资料语音行。

        Returns:
            完整的带签名绝对 URL。
        """
        return record.signed_url


class ProfileSerializer(serializers.ModelSerializer):
    """「我的资料」的完整表示,含隐私字段与完善度提示。"""

    # id 是 profile 表主键;对外标识用户一律用 user_id(与公开资料卡的 user_id 同源)
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    age = serializers.IntegerField(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    photos = PhotoSerializer(source="user.photos", many=True, read_only=True)
    preference = PreferenceSerializer(read_only=True)
    missing_fields = serializers.ListField(child=serializers.CharField(), read_only=True)
    voice = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = ["id", "user_id", "phone", "nickname", "gender", "birthday", "age", "city", "bio",
                  "status", "ban_reason", "missing_fields", "tags", "photos", "preference",
                  "visits_hidden", "voice"]

    @extend_schema_field(ProfileVoiceSerializer(allow_null=True))
    def get_voice(self, profile):
        """资料语音自我介绍,没录过为 ``null``。

        Args:
            profile: 当前用户的资料。

        Returns:
            ``{"url", "duration_ms"}`` 或 ``None``。
        """
        return voice_payload(profile)


class PublicProfileSerializer(serializers.ModelSerializer):
    """对方资料卡:只比 ProfileSerializer 少了隐私字段(手机号/生日/偏好/缺项)。

    ``shared_tags`` 是「对方标签 ∩ 我的标签」,给配对那一刻的破冰文案用;
    列表场景若已批量算好,可从 ``context["shared_tags_map"]`` 直接注入,避免逐项查询。

    ``is_followed`` / ``follower_count`` / ``following_count`` 是批次 I 的关注态:
    同样支持 ``context["follow_state_map"]`` 批量注入(见 ``feed.services.follow_state_for_profiles``),
    单条资料卡场景默认只多**一条**聚合 SQL。
    """

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    age = serializers.IntegerField(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    shared_tags = serializers.SerializerMethodField()
    photos = serializers.SerializerMethodField()
    voice = serializers.SerializerMethodField()
    is_followed = serializers.SerializerMethodField()
    follower_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = ["user_id", "nickname", "gender", "age", "city", "bio", "tags",
                  "shared_tags", "photos", "voice", "is_followed", "follower_count",
                  "following_count"]

    def _follow_state(self, profile) -> dict:
        """取某条资料的关注态(优先用调用方注入的批量结果)。

        Args:
            profile: 被查看的资料。

        Returns:
            ``{"is_followed": bool, "follower_count": int, "following_count": int}``;
            取不到时返回空字典(三个字段各自兜底成 ``False`` / ``0``)。
        """
        state_map = self.context.get("follow_state_map")
        if state_map is not None:
            return state_map.get(profile.user_id, {})
        memo = getattr(self, "_follow_state_memo", None)
        if memo is None:
            memo = {}
            self._follow_state_memo = memo
        if profile.user_id not in memo:
            request = self.context.get("request")
            viewer = getattr(request, "user", None)
            memo.update(follow_state_for_profiles([profile], viewer))
        return memo.get(profile.user_id, {})

    @extend_schema_field(serializers.BooleanField())
    def get_is_followed(self, profile):
        """当前用户是否关注了对方。

        Args:
            profile: 被查看的资料。

        Returns:
            已关注为 ``True``;未登录或没关注过为 ``False``。
        """
        return bool(self._follow_state(profile).get("is_followed", False))

    @extend_schema_field(serializers.IntegerField())
    def get_follower_count(self, profile):
        """对方的粉丝数(多少人关注了对方)。

        Args:
            profile: 被查看的资料。

        Returns:
            粉丝数;没有记录时为 0。
        """
        return int(self._follow_state(profile).get("follower_count", 0))

    @extend_schema_field(serializers.IntegerField())
    def get_following_count(self, profile):
        """对方的关注数(对方关注了多少人)。

        Args:
            profile: 被查看的资料。

        Returns:
            关注数;没有记录时为 0。
        """
        return int(self._follow_state(profile).get("following_count", 0))

    @extend_schema_field(TagSerializer(many=True))
    def get_shared_tags(self, profile):
        """返回当前用户与对方的共同标签。

        单条资料卡场景每次只多一条 M2M 查询;列表场景请由调用方批量算好后从
        ``context["shared_tags_map"]`` 注入(否则每个对象一条查询)。

        Args:
            profile: 被查看的资料。

        Returns:
            共同标签数组(``{id, name, icon}``);未登录或没有交集时为空数组。
        """
        shared_map = self.context.get("shared_tags_map")
        if shared_map is not None:
            return shared_map.get(profile.user_id, [])
        memo = getattr(self, "_shared_tags_memo", None)
        if memo is None:
            memo = {}
            self._shared_tags_memo = memo
        if profile.user_id not in memo:
            request = self.context.get("request")
            viewer = getattr(request, "user", None)
            found = ({} if viewer is None or not viewer.is_authenticated
                     else shared_tags_for_profiles([profile], viewer))
            memo.update(found)
        return memo.get(profile.user_id, [])

    @extend_schema_field(ProfileVoiceSerializer(allow_null=True))
    def get_voice(self, profile):
        """对方的资料语音;没录过为 ``null``。

        语音是**公开**的:任何能看这条资料卡的人都能听到(与照片同口径,不做
        「仅配对后可听」)。可见性由 ``public_profile`` 视图保证,这里不再过滤。

        Args:
            profile: 被查看的资料。

        Returns:
            ``{"url", "duration_ms"}`` 或 ``None``。
        """
        return voice_payload(profile)

    @extend_schema_field(PhotoSerializer(many=True))
    def get_photos(self, profile):
        """只返回已过审的照片。

        Args:
            profile: 被查看的资料。

        Returns:
            已过审照片的序列化数据;待审核与已驳回的一律不出现。
        """
        approved = [p for p in profile.user.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data


class ProfileUpdateSerializer(serializers.Serializer):
    """编辑资料的入参;所有字段可选,只校验提交上来的那些。"""

    nickname = serializers.CharField(max_length=20, required=False)
    gender = serializers.ChoiceField(choices=Gender.choices, required=False)
    birthday = serializers.DateField(required=False)
    city = serializers.CharField(max_length=50, required=False)
    bio = serializers.CharField(max_length=200, required=False)
    tag_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)
    visits_hidden = serializers.BooleanField(required=False)

    def validate_nickname(self, value):
        """校验昵称:违禁词检查 + 去首尾空白。

        Args:
            value: 提交的昵称。

        Returns:
            去空白后的昵称。

        Raises:
            serializers.ValidationError: 命中违禁词。
        """
        if find_blocked_word(value):
            raise serializers.ValidationError("昵称包含违规内容,请修改")
        return value.strip()

    def validate_bio(self, value):
        """校验简介:违禁词检查 + 去首尾空白。

        Args:
            value: 提交的简介。

        Returns:
            去空白后的简介。

        Raises:
            serializers.ValidationError: 命中违禁词。
        """
        if find_blocked_word(value):
            raise serializers.ValidationError("简介包含违规内容,请修改")
        return value.strip()

    def validate_birthday(self, value):
        """校验生日:未满 18 周岁不允许使用本应用。

        Args:
            value: 提交的生日。

        Returns:
            通过校验的生日。

        Raises:
            serializers.ValidationError: 按该生日算出的年龄小于 18。
        """
        if calculate_age(value) < 18:
            raise serializers.ValidationError("未满 18 周岁,无法使用本应用")
        return value

    def validate_tag_ids(self, value):
        """校验标签主键都真实存在。

        Args:
            value: 提交的标签主键列表。

        Returns:
            通过校验的标签主键列表。

        Raises:
            serializers.ValidationError: 存在库里没有的标签主键。
        """
        unique_ids = set(value)
        if Tag.objects.filter(id__in=unique_ids).count() != len(unique_ids):
            raise serializers.ValidationError("存在无效的标签")
        return value


class PhotoUploadSerializer(serializers.Serializer):
    """照片上传入参(multipart 字段 ``file``)。"""

    file = serializers.ImageField()

    def validate_file(self, value):
        """校验图片大小。

        Args:
            value: 上传的图片文件。

        Returns:
            通过校验的图片文件。

        Raises:
            serializers.ValidationError: 超过 ``settings.PHOTO_MAX_BYTES``。
        """
        if value.size > settings.PHOTO_MAX_BYTES:
            raise serializers.ValidationError("图片不能超过 5MB")
        return value


class ProfileVoiceUploadSerializer(serializers.Serializer):
    """资料语音上传入参(multipart 字段 ``file``)。

    时长不靠客户端声明:服务端用 ``ffprobe`` 实测(见 ``users.views.my_voice``),
    所以这里只校验大小与容器格式。
    """

    file = serializers.FileField()

    def validate_file(self, value):
        """校验语音大小与 MIME 白名单。

        Args:
            value: 上传的文件对象。

        Returns:
            通过校验的文件对象。

        Raises:
            serializers.ValidationError: 超过大小上限,或格式不在音频白名单。
        """
        if value.size > settings.PROFILE_VOICE_MAX_BYTES:
            raise serializers.ValidationError("语音不能超过 5MB")
        if base_content_type(value.content_type) not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise serializers.ValidationError("只支持 M4A/AAC/WebM/OGG 音频")
        return value


class DeleteAccountSerializer(serializers.Serializer):
    """注销账号:要求输入完整手机号做二次确认(不可恢复操作)。"""

    phone = serializers.CharField(max_length=20)

    def validate_phone(self, value):
        """校验输入手机号与当前账号一致。

        Args:
            value: 用户输入的手机号。

        Returns:
            去空白后的手机号。

        Raises:
            serializers.ValidationError: 与当前账号手机号不一致,或缺少请求上下文。
        """
        request = self.context.get("request")
        if request is None or value.strip() != request.user.phone:
            raise serializers.ValidationError("手机号与当前账号不一致")
        return value.strip()
