"""IM 接口的入参校验:聊天图片与语音上传。"""

from django.conf import settings
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

        Args:
            value: 上传的图片文件(DRF 已用 Pillow 校验过是真实图片)。

        Returns:
            通过校验的文件对象。

        Raises:
            serializers.ValidationError: 超过大小上限,或格式不在白名单。
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

        Args:
            value: 上传的文件对象。

        Returns:
            通过校验的文件对象。

        Raises:
            serializers.ValidationError: 超过大小上限或类型不在白名单。
        """
        if value.size > settings.CHAT_VOICE_MAX_BYTES:
            raise serializers.ValidationError("语音不能超过 5MB")
        if base_content_type(value.content_type) not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise serializers.ValidationError("只支持 M4A/AAC/WebM/OGG 音频")
        return value
