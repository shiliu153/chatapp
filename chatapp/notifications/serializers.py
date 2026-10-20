"""推送接口的序列化:设备上报与通知偏好。

设计要点:
    设备用普通 ``Serializer`` 而不是 ``ModelSerializer``:接口只接收三个字段,
    用户与时间戳都由服务端决定,不给客户端越权空间。
"""

from rest_framework import serializers

from .models import NotificationPreference, PushPlatform


class DeviceSerializer(serializers.Serializer):
    """设备上报的入参。"""

    registration_id = serializers.CharField(max_length=128)
    platform = serializers.ChoiceField(choices=PushPlatform.choices)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True,
                                        default="")


class PreferenceSerializer(serializers.ModelSerializer):
    """通知偏好的读写形状(三个布尔字段)。"""

    class Meta:
        model = NotificationPreference
        fields = ["likes", "matches", "system"]
