"""推送接口与站内通知的序列化。

设计要点:
    设备用普通 ``Serializer`` 而不是 ``ModelSerializer``:接口只接收三个字段,
    用户与时间戳都由服务端决定,不给客户端越权空间。

    站内通知的响应体是「模型 + 现拼的摘要」:``actor`` 与 ``target`` 都是嵌套对象,
    而且头像要从对方的已过审照片里挑第一张,``ModelSerializer`` 表达不出来,
    所以在 :func:`notification_payload` 里拼好字典,再交给
    ``NotificationItemSerializer`` 做 schema 声明与序列化。
"""

from rest_framework import serializers

from users.models import PhotoStatus

from .models import NotificationPreference, NotificationTarget, PushPlatform


class DeviceSerializer(serializers.Serializer):
    """设备上报的入参。"""

    registration_id = serializers.CharField(max_length=128)
    platform = serializers.ChoiceField(choices=PushPlatform.choices)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True,
                                        default="")


class DeviceResponseSerializer(serializers.Serializer):
    """设备上报的回执。"""

    registration_id = serializers.CharField()
    platform = serializers.CharField()


class PushPreferenceSerializer(serializers.ModelSerializer):
    """通知偏好的读写形状(五个布尔字段,对应五类通知)。

    ``social`` 是站内通知中心(批次 H)新增的开关:动态被赞 / 被评论 / 评论被回复。
    """

    class Meta:
        model = NotificationPreference
        fields = ["likes", "matches", "messages", "system", "social"]


class NotificationActorSerializer(serializers.Serializer):
    """通知里的触发者摘要。

    ``id`` 是**账号 id**(即 IM 的 ``u{id}``),可直接拼成 ``/chat/{id}`` 跳转。
    """

    id = serializers.IntegerField()
    nickname = serializers.CharField()
    avatar = serializers.CharField(allow_null=True)


class NotificationTargetSerializer(serializers.Serializer):
    """通知点击后要跳向的目标;``kind=none`` 时 ``id`` 为 ``null``。"""

    kind = serializers.ChoiceField(choices=NotificationTarget.choices)
    id = serializers.IntegerField(allow_null=True)


class NotificationItemSerializer(serializers.Serializer):
    """站内通知列表里的一条。"""

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
    """

    ids = serializers.ListField(child=serializers.IntegerField(min_value=1),
                                required=False)
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        """校验「必须给出 ids 或 all=true」。

        Args:
            attrs: 已通过字段级校验的数据。

        Returns:
            通过校验的数据。

        Raises:
            serializers.ValidationError: 两个字段都没给(空 body 会静默成功,不能接受)。
        """
        if not attrs.get("ids") and not attrs.get("all"):
            raise serializers.ValidationError("请提供 ids 或 all=true")
        return attrs


class UnreadCountSerializer(serializers.Serializer):
    """未读数回执。"""

    unread = serializers.IntegerField()


def notification_payload(notification, request) -> dict:
    """把一条通知拼成列表项字典(含触发者摘要与头像)。

    Args:
        notification: ``InAppNotification`` 实例;调用方需已 ``select_related``
            触发者资料并 ``prefetch_related`` 触发者照片,避免 N+1。
        request: 当前请求,用于把头像拼成绝对 URL。

    Returns:
        ``{id, kind, text, is_read, created_at, actor, target}``。
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
