"""举报与拉黑的序列化器。

设计要点:
    ``BlockSerializer`` 会为每条黑名单记录附带对方的昵称与头像(取第一张已过审照片),
    以便前端直接渲染黑名单列表,不需要再逐条查资料。

文件信息:
    文件名称          moderation/serializers.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework import serializers

from users.models import PhotoStatus

from .models import Block, Report, ReportType


class ReportCreateSerializer(serializers.Serializer):
    """举报入参。

    参数说明:
        data: 请求体字典;``target_user_id`` 必填,``type`` 必填,``detail`` 可选。
        context: 本入参序列化器不使用。

    返回参数:
        ``is_valid()`` 通过后 ``validated_data`` 为
        ``{target_user_id, type, detail}``,``detail`` 缺省为空串。

    使用示例:
        ``ReportCreateSerializer(data=request.data).is_valid(raise_exception=True)``

    备注信息:
        只校验字段形态,不校验业务规则 —— 「不能举报自己」与「被举报人必须存在」
        由 ``views.create_report`` 判断(分别回 400 / 404)。
        ``type`` 取值来自 ``ReportType``(harassment / porn / fraud / other),非法值 400。
    """

    target_user_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=ReportType.choices)
    detail = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ReportSerializer(serializers.ModelSerializer):
    """举报的对外表示(只回执最必要的三项)。

    参数说明:
        instance: 待序列化的 ``Report``(或查询集,配合 ``many=True``)。
        many: 是否批量序列化,默认 ``False``。
        context: 本序列化器不使用。

    返回参数:
        ``data`` 为 ``{id, type, status}``;``status`` 是 ``pending`` / ``handled``。

    使用示例:
        ``ReportSerializer(report).data``

    备注信息:
        故意只回三项:客户端只需要拿到举报 id 与状态,不暴露处理人、备注与时间;
        处理结果通过通知推送,不在本响应里。
    """

    class Meta:
        model = Report
        fields = ["id", "type", "status"]


class BlockCreateSerializer(serializers.Serializer):
    """拉黑入参。

    参数说明:
        data: 请求体字典,只认 ``target_user_id``。
        context: 本入参序列化器不使用。

    返回参数:
        ``is_valid()`` 通过后 ``validated_data`` 为 ``{target_user_id}``。

    使用示例:
        ``BlockCreateSerializer(data=request.data).is_valid(raise_exception=True)``

    备注信息:
        「不能拉黑自己」与「目标用户必须存在」由 ``views.blocks`` 判断
        (分别回 400 / 404),本序列化器只管字段类型与必填。
    """

    target_user_id = serializers.IntegerField()


class BlockSerializer(serializers.ModelSerializer):
    """黑名单条目的对外表示,已内联对方的昵称与头像。

    参数说明:
        instance: 待序列化的 ``Block``(或查询集,配合 ``many=True``)。
        many: 是否批量序列化,默认 ``False``。
        context: 必须带 ``request`` —— 头像要拼成绝对 URL。

    返回参数:
        ``data`` 为 ``{user_id, nickname, avatar_url, blocked_at}``;
        ``user_id`` 是被拉黑方的账号 id,``blocked_at`` 取 ``created_at``。

    使用示例:
        ``BlockSerializer(block, context={"request": request}).data``

    备注信息:
        ``user_id`` 用 ``source="blocked.id"`` 映射,``blocked_at`` 用
        ``source="created_at"`` 映射,两者都只读;昵称与头像走 ``SerializerMethodField``,
        逐条读已预取的 ``blocked.profile`` 与 ``blocked.photos``,所以视图侧必须
        ``select_related("blocked__profile")`` + ``prefetch_related("blocked__photos")``。
    """

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
            ``serializer.get_nickname(block)``

        备注信息:
            用 ``getattr(block.blocked, "profile", None)`` 取资料,资料不存在的账号
            (资料行还没建)返回空串而不是抛异常;视图侧已 ``select_related`` 过,
            这里不会额外查库。
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
            ``serializer.get_avatar_url(block)``

        备注信息:
            只认 ``PhotoStatus.APPROVED``:待审/驳回的照片不展示,扫完整个
            ``blocked.photos`` 都没命中就返回 ``None``(前端按占位图渲染)。
            绝对 URL 依赖 ``context["request"]``,脱离请求上下文调用会 ``KeyError``。
        """
        for photo in block.blocked.photos.all():
            if photo.status == PhotoStatus.APPROVED:
                return self.context["request"].build_absolute_uri(photo.file.url)
        return None
