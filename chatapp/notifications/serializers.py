"""推送接口与站内通知的序列化。

设计要点:
    设备用普通 ``Serializer`` 而不是 ``ModelSerializer``:接口只接收三个字段,
    用户与时间戳都由服务端决定,不给客户端越权空间。

    站内通知的响应体是「模型 + 现拼的摘要」:``actor`` 与 ``target`` 都是嵌套对象,
    而且头像要从对方的已过审照片里挑第一张,``ModelSerializer`` 表达不出来,
    所以在 :func:`notification_payload` 里拼好字典,再交给
    ``NotificationItemSerializer`` 做 schema 声明与序列化。

文件信息:
    文件名称          notifications/serializers.py
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

from .models import NotificationPreference, NotificationTarget, PushPlatform


class DeviceSerializer(serializers.Serializer):
    """设备上报的入参。

    参数说明:
        registration_id: 极光 registration_id,最长 128 字符,必填。
        platform: 平台,只接受 ``android`` / ``ios``(取自 ``PushPlatform``)。
        app_version: App 版本,最长 32 字符,可不传,缺省空串。

    返回参数:
        校验后的 ``validated_data`` 字典。

    使用示例:
        ``DeviceSerializer(data=request.data)``

    备注信息:
        只声明客户端有权决定的三个字段;设备归属账号与时间戳由视图按登录态补齐,
        因此本序列化器**不**接收 ``user``。
    """

    registration_id = serializers.CharField(max_length=128)
    platform = serializers.ChoiceField(choices=PushPlatform.choices)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True,
                                        default="")


class DeviceResponseSerializer(serializers.Serializer):
    """设备上报的回执。

    参数说明:
        registration_id: 原样回显上报的 registration_id。
        platform: 原样回显平台。

    返回参数:
        序列化后的 ``{"registration_id": str, "platform": str}``。

    使用示例:
        ``DeviceResponseSerializer({"registration_id": "reg", "platform": "android"}).data``

    备注信息:
        只用于 ``@extend_schema`` 的响应声明与实际回显;回执不带设备主键,
        客户端不需要(它只用 registration_id 做解绑)。
    """

    registration_id = serializers.CharField()
    platform = serializers.CharField()


class PushPreferenceSerializer(serializers.ModelSerializer):
    """通知偏好的读写形状(五个布尔字段,对应五类通知)。

    ``social`` 是站内通知中心(批次 H)新增的开关:动态被赞 / 被评论 / 评论被回复。

    参数说明:
        likes: 是否接收「新的喜欢」。
        matches: 是否接收「配对成功」。
        messages: 是否接收「新消息」。
        system: 是否接收系统通知。
        social: 是否接收动态互动站内通知。

    返回参数:
        序列化后的五个布尔字段;PATCH 后回显更新结果。

    使用示例:
        ``PushPreferenceSerializer(preference, data=request.data, partial=True)``

    备注信息:
        直接绑 ``NotificationPreference`` 模型,但只暴露这五个开关 —— ``user`` 与
        ``updated_at`` 不进响应;PATCH 走 ``partial=True``,未传字段保持原值。
    """

    class Meta:
        model = NotificationPreference
        fields = ["likes", "matches", "messages", "system", "social"]


class NotificationActorSerializer(serializers.Serializer):
    """通知里的触发者摘要。

    ``id`` 是**账号 id**(即 IM 的 ``u{id}``),可直接拼成 ``/chat/{id}`` 跳转。

    参数说明:
        id: 触发者账号 id。
        nickname: 触发者昵称;资料未填时为空串。
        avatar: 触发者头像的绝对 URL;没有已过审照片时为 ``null``。

    返回参数:
        序列化后的触发者摘要字典。

    使用示例:
        ``NotificationActorSerializer(actor_dict).data``

    备注信息:
        形状与 ``notification_payload`` 拼出来的 ``actor`` 一致,两处改字段要同改;
        头像取的是触发者**已过审**照片里的第一张(见 ``PhotoStatus.APPROVED``)。
    """

    id = serializers.IntegerField()
    nickname = serializers.CharField()
    avatar = serializers.CharField(allow_null=True)


class NotificationTargetSerializer(serializers.Serializer):
    """通知点击后要跳向的目标;``kind=none`` 时 ``id`` 为 ``null``。

    参数说明:
        kind: 目标类型,取值 ``post`` / ``user`` / ``none``(取自 ``NotificationTarget``)。
        id: 目标主键;``kind=none`` 时为 ``null``。

    返回参数:
        序列化后的目标字典。

    使用示例:
        ``NotificationTargetSerializer({"kind": "post", "id": 12}).data``

    备注信息:
        ``id`` 不做存在性校验:帖子被删后通知仍要能返回(留痕语义见
        ``notifications/models.py``),点击时目标不存在按「只标已读」处理。
    """

    kind = serializers.ChoiceField(choices=NotificationTarget.choices)
    id = serializers.IntegerField(allow_null=True)


class NotificationItemSerializer(serializers.Serializer):
    """站内通知列表里的一条。

    参数说明:
        id: 通知主键。
        kind: 事件类型(``NotificationKind`` 取值)。
        text: 服务端生成的正文。
        is_read: 是否已读。
        created_at: 创建时间,ISO 8601 字符串。
        actor: 触发者摘要;系统消息为 ``null``。
        target: 跳转目标 ``{kind, id}``。

    返回参数:
        序列化后的一条通知字典。

    使用示例:
        ``NotificationItemSerializer(payloads, many=True).data``

    备注信息:
        入参是 ``notification_payload`` 拼好的字典,不是模型实例 —— 头像与昵称要跨表
        取,``ModelSerializer`` 表达不了;本类只负责字段声明与 schema 输出。
    """

    id = serializers.IntegerField()
    kind = serializers.CharField()
    text = serializers.CharField()
    is_read = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    actor = NotificationActorSerializer(allow_null=True)
    target = NotificationTargetSerializer()


class NotificationReadSerializer(serializers.Serializer):
    """标记已读的入参:``ids`` 与 ``all`` 二选一。

    ``all`` 是 Python 关键字之外的普通字段名,DRF 与 OpenAPI 都按 ``all`` 输出。

    参数说明:
        ids: 要标记的通知主键列表,每项 ≥ 1;与 ``all`` 二选一。
        all: 是否标记全部未读,默认 ``False``;与 ``ids`` 二选一。

    返回参数:
        校验后的 ``validated_data`` 字典。

    使用示例:
        ``NotificationReadSerializer(data=request.data)``

    备注信息:
        两个字段都可单传,但不能都不传 —— 空 body 会被 ``validate`` 拦成 400,
        否则「什么都没给」会静默成功,客户端以为标完了。
    """

    ids = serializers.ListField(child=serializers.IntegerField(min_value=1),
                                required=False)
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        """校验「必须给出 ids 或 all=true」。

        参数说明:
            attrs: 已通过字段级校验的数据。

        返回参数:
            通过校验的数据。

        使用示例:
            ``NotificationReadSerializer(data={"all": True}).is_valid()``

        备注信息:
            两个字段都没给时抛 ``serializers.ValidationError`` —— 空 body 会静默成功,
            不能接受;传了 ``ids=[]``(空列表)同样算「没给」。
        """
        if not attrs.get("ids") and not attrs.get("all"):
            raise serializers.ValidationError("请提供 ids 或 all=true")
        return attrs


class UnreadCountSerializer(serializers.Serializer):
    """未读数回执。

    参数说明:
        unread: 未读通知条数(自己的、90 天内的)。

    返回参数:
        序列化后的 ``{"unread": int}``。

    使用示例:
        ``UnreadCountSerializer({"unread": 3}).data``

    备注信息:
        只用于 ``@extend_schema`` 的响应声明;口径与列表接口共用
        ``notifications.views._visible_notifications``,不能单独改窗口。
    """

    unread = serializers.IntegerField()


def notification_payload(notification, request) -> dict:
    """把一条通知拼成列表项字典(含触发者摘要与头像)。

    参数说明:
        notification: ``InAppNotification`` 实例;调用方需已 ``select_related``
            触发者资料并 ``prefetch_related`` 触发者照片,避免 N+1。
        request: 当前请求,用于把头像拼成绝对 URL。

    返回参数:
        ``{id, kind, text, is_read, created_at, actor, target}``。

    使用示例:
        ``notification_payload(row, request)``

    备注信息:
        头像取触发者**已过审**照片里的第一张(按模型默认排序),没有则 ``avatar`` 为
        ``None``;触发者已注销(``actor_id`` 为空)时整个 ``actor`` 为 ``None``,
        不做任何查询。
    """
    actor = None
    if notification.actor_id:
        profile = getattr(notification.actor, "profile", None)
        avatar = None
        for photo in notification.actor.photos.all():
            if photo.status == PhotoStatus.APPROVED:
                avatar = request.build_absolute_uri(photo.file.url)
                break
        actor = {"id": notification.actor_id,
                 "nickname": profile.nickname if profile else "",
                 "avatar": avatar}
    return {
        "id": notification.id,
        "kind": notification.kind,
        "text": notification.text,
        "is_read": notification.is_read,
        "created_at": notification.created_at,
        "actor": actor,
        "target": {"kind": notification.target_kind, "id": notification.target_id},
    }
