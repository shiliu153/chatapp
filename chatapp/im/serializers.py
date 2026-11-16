"""IM 接口的入参校验与响应序列化:聊天图片、语音上传与语音转码状态。"""

from django.conf import settings
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers

from .voice import base_content_type

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/mp4", "audio/m4a", "audio/x-m4a", "audio/aac", "audio/webm", "audio/ogg",
}


class ChatImageUploadSerializer(serializers.Serializer):
    """聊天图片上传入参(multipart 字段 ``file``)。"""

    file = serializers.ImageField()

    def validate_file(self, value):
        """校验大小与格式。

        参数说明:
            value: 上传的图片文件(DRF 已用 Pillow 校验过是真实图片)。

        返回参数:
            通过校验的文件对象。

        使用示例:
            ``serializer.is_valid(raise_exception=True)``(见 ``im/views.py`` 的 ``upload_image``)

        备注信息:
            超过大小上限,或格式不在白名单时抛 ``serializers.ValidationError``,由 DRF 转成 400。
        """
        if value.size > settings.CHAT_IMAGE_MAX_BYTES:
            raise serializers.ValidationError("图片不能超过 5MB")
        if value.content_type not in ALLOWED_CONTENT_TYPES:
            raise serializers.ValidationError("只支持 JPG/PNG/WebP")
        return value


class ChatVoiceUploadSerializer(serializers.Serializer):
    """聊天语音上传入参(multipart 字段 ``file`` + ``duration_ms``)。"""

    file = serializers.FileField()
    duration_ms = serializers.IntegerField(min_value=1000, max_value=60000)

    def validate_file(self, value):
        """校验大小与 MIME。

        参数说明:
            value: 上传的文件对象。

        返回参数:
            通过校验的文件对象。

        使用示例:
            ``serializer.is_valid(raise_exception=True)``(见 ``im/views.py`` 的 ``upload_voice``)

        备注信息:
            超过大小上限或类型不在白名单时抛 ``serializers.ValidationError``,由 DRF 转成 400;
            MIME 先经 ``base_content_type`` 去掉 ``;codecs=...`` 再比对。
        """
        if value.size > settings.CHAT_VOICE_MAX_BYTES:
            raise serializers.ValidationError("语音不能超过 5MB")
        if base_content_type(value.content_type) not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise serializers.ValidationError("只支持 M4A/AAC/WebM/OGG 音频")
        return value


class VoiceStatusSerializer(serializers.Serializer):
    """语音转码状态的响应体:聊天语音与资料语音两个轮询接口同形状(M-3)。

    ``pending`` 时 ``url`` / ``duration_ms`` / ``size`` 都是 ``null``(还没有正式文件);
    ``failed`` 时同样为空,失败原因走 ``code``(业务码,如 ``41301``)或 ``message``
    (短文案)。``ready`` 时 ``code`` / ``message`` 为 ``null``。
    """

    id = serializers.IntegerField()
    status = serializers.CharField()
    url = serializers.CharField(allow_null=True)
    duration_ms = serializers.IntegerField(allow_null=True)
    size = serializers.IntegerField(allow_null=True)
    code = serializers.CharField(allow_null=True)
    message = serializers.CharField(allow_null=True)


# 202 的响应体:上传已受理、正在排队转码(不带 url —— 还没有正式文件)。
# 两个上传入口共用同一个组件名与同一份字段,drf-spectacular 不会当成两个 schema。
VOICE_QUEUED_RESPONSE = inline_serializer("VoiceQueued", fields={
    "id": serializers.IntegerField(),
    "status": serializers.CharField(),
    "retry_after": serializers.IntegerField(),
})

