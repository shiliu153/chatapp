"""IM 接口的入参校验:聊天图片与语音上传。

文件信息:
    文件名称          im/serializers.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.conf import settings
from rest_framework import serializers

from .voice import base_content_type

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/mp4", "audio/m4a", "audio/x-m4a", "audio/aac", "audio/webm", "audio/ogg",
}


class ChatImageUploadSerializer(serializers.Serializer):
    """聊天图片上传入参(multipart 字段 ``file``)。

    参数说明:
        file: 图片文件,由 DRF ``ImageField`` 接管(Pillow 已验过是真实图片)。

    返回参数:
        校验后的 ``validated_data`` 字典。

    使用示例:
        ``ChatImageUploadSerializer(data=request.data)``

    备注信息:
        只做入参形状与格式/大小校验;落盘、EXIF 清洗与配额检查在 ``im/views.py`` 与
        ``config/images.py`` 里做。
    """

    file = serializers.ImageField()

    def validate_file(self, value):
        """校验大小与格式。

        参数说明:
            value: 上传的图片文件(DRF 已用 Pillow 校验过是真实图片)。

        返回参数:
            通过校验的文件对象。

        使用示例:
            ``ChatImageUploadSerializer().validate_file(file)``

        备注信息:
            超过 ``CHAT_IMAGE_MAX_BYTES`` 或 ``content_type`` 不在
            ``ALLOWED_CONTENT_TYPES``(jpg/png/webp)时抛
            ``serializers.ValidationError``;``content_type`` 取客户端声明的值。
        """
        if value.size > settings.CHAT_IMAGE_MAX_BYTES:
            raise serializers.ValidationError("图片不能超过 5MB")
        if value.content_type not in ALLOWED_CONTENT_TYPES:
            raise serializers.ValidationError("只支持 JPG/PNG/WebP")
        return value


class ChatVoiceUploadSerializer(serializers.Serializer):
    """聊天语音上传入参(multipart 字段 ``file`` + ``duration_ms``)。

    参数说明:
        file: 语音文件,DRF ``FileField``(不校验真实音频格式,靠 ffprobe 兜底)。
        duration_ms: 客户端声明的时长,限 1000–60000 毫秒。

    返回参数:
        校验后的 ``validated_data`` 字典。

    使用示例:
        ``ChatVoiceUploadSerializer(data=request.data)``

    备注信息:
        ``duration_ms`` 只是声明值,落库用的是 ffprobe 读出的真实时长;两者超出
        ``CHAT_VOICE_DURATION_TOLERANCE_MS`` 时由 ``im/voice.normalize`` 拒绝。
    """

    file = serializers.FileField()
    duration_ms = serializers.IntegerField(min_value=1000, max_value=60000)

    def validate_file(self, value):
        """校验大小与 MIME。

        参数说明:
            value: 上传的文件对象。

        返回参数:
            通过校验的文件对象。

        使用示例:
            ``ChatVoiceUploadSerializer().validate_file(file)``

        备注信息:
            超过 ``CHAT_VOICE_MAX_BYTES`` 或 ``base_content_type(value.content_type)``
            不在 ``ALLOWED_AUDIO_CONTENT_TYPES`` 时抛 ``serializers.ValidationError``;
            先剥掉 ``;codecs=`` 之类参数再比对,所以 ``audio/webm; codecs=opus`` 也能过。
        """
        if value.size > settings.CHAT_VOICE_MAX_BYTES:
            raise serializers.ValidationError("语音不能超过 5MB")
        if base_content_type(value.content_type) not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise serializers.ValidationError("只支持 M4A/AAC/WebM/OGG 音频")
        return value
