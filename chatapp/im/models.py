"""IM 应用的本地数据模型:聊天图片与语音的元数据。

消息本身存在自建 imserver 的库,Django 这边只落**媒体文件**
的元数据,用于运营抽审、删除审计与注销清理。

设计要点:
    1. 文件名带随机 uuid(由视图生成),不用自增主键 —— 防止顺着 URL 遍历别人的私聊图;
    2. 运营删除只改 ``status`` 并留 ``deleted_by/deleted_at``,不删行 —— 审计可查;
    3. ``width/height`` 存的是**显示尺寸**(已按 EXIF 方向校正),不是文件原始像素。

文件信息:
    文件名称          im/models.py
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
from django.db import models

from . import media_sign


class ChatImageStatus(models.TextChoices):
    """聊天图片的状态。"""

    VISIBLE = "visible", "正常"
    DELETED = "deleted", "已删除"
    EXPIRED = "expired", "已过期清理"


class ChatImage(models.Model):
    """一张聊天图片的文件元数据。

    参数说明:
        无(构造参数由 Django 模型字段决定,``owner`` / ``file`` / ``thumb`` 为必填)。

    返回参数:
        模型实例。

    使用示例:
        ``ChatImage.objects.create(owner=user, file=f, thumb=t, width=1080, height=1440, bytes=204800)``

    备注信息:
        ``status`` 默认 ``visible``;删除只改状态并写 ``deleted_by/deleted_at``,行本身
        保留供审计。``deleted_by`` 是执行删除的运营账号,未删除时为 ``None``;
        ``deleted_at`` 是删除时间,未删除时为 ``None``。``width/height`` 是 EXIF
        校正后的显示尺寸,不是文件原始像素。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="chat_images", verbose_name="发送者")
    file = models.ImageField("原图", upload_to="chat/%Y/%m/")
    thumb = models.ImageField("缩略图", upload_to="chat/%Y/%m/")
    width = models.PositiveIntegerField("宽")
    height = models.PositiveIntegerField("高")
    bytes = models.PositiveIntegerField("字节数")
    status = models.CharField("状态", max_length=10, choices=ChatImageStatus.choices,
                              default=ChatImageStatus.VISIBLE)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    deleted_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField("过期清理时间", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def signed_file_url(self) -> str:
        """运营台预览用:带签名的原图绝对地址。

        参数说明:
            无。

        返回参数:
            ``MEDIA_BASE_URL + 文件路径`` 并附签名 query。

        使用示例:
            ``image.signed_file_url``

        备注信息:
            签名由 ``im/media_sign.sign_url`` 生成,TTL 与生产必填的
            ``IM_MEDIA_SIGN_SECRET`` 相关;前端拿到的地址不可长期缓存。
        """
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.file.url}")

    @property
    def signed_thumb_url(self) -> str:
        """运营台预览用:带签名的缩略图绝对地址。

        参数说明:
            无。

        返回参数:
            ``MEDIA_BASE_URL + 缩略图路径`` 并附签名 query。

        使用示例:
            ``image.signed_thumb_url``

        备注信息:
            与 ``signed_file_url`` 同一套签名逻辑,只是换成 ``thumb`` 字段。
        """
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.thumb.url}")

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``chat_image#主键(owner=发送者 id)``。

        使用示例:
            ``str(image)``

        备注信息:
            只读 ``owner_id``,不触发 ``owner`` 关联查询。
        """
        return f"chat_image#{self.pk}(owner={self.owner_id})"


class ChatVoiceStatus(models.TextChoices):
    """聊天语音的状态。"""

    VISIBLE = "visible", "正常"
    DELETED = "deleted", "已删除"
    EXPIRED = "expired", "已过期清理"


class ChatVoice(models.Model):
    """一段聊天语音的文件元数据(统一转码为 m4a)。

    参数说明:
        无(构造参数由 Django 模型字段决定,``owner`` / ``file`` / ``duration_ms`` /
        ``bytes`` 为必填)。

    返回参数:
        模型实例。

    使用示例:
        ``ChatVoice.objects.create(owner=user, file=f, duration_ms=3200, bytes=40960)``

    备注信息:
        服务端统一转码为 m4a,``mime`` 默认 ``audio/mp4``;落库的 ``duration_ms`` 是
        ffprobe 读出的真实时长,客户端上报值只在 ``im/voice.normalize`` 里做一致性比对。
        删除同样只改 ``status`` 并留审计字段:``deleted_by`` 是执行删除的运营账号,
        未删除时为 ``None``;``deleted_at`` 是删除时间,未删除时为 ``None``。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="chat_voices", verbose_name="发送者")
    file = models.FileField("语音", upload_to="chat/voices/%Y/%m/")
    duration_ms = models.PositiveIntegerField("时长(毫秒)")
    bytes = models.PositiveIntegerField("字节数")
    mime = models.CharField("MIME", max_length=32, default="audio/mp4")
    status = models.CharField("状态", max_length=10, choices=ChatVoiceStatus.choices,
                              default=ChatVoiceStatus.VISIBLE)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    deleted_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField("过期清理时间", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def signed_file_url(self) -> str:
        """运营台播放用:带签名的语音绝对地址。

        参数说明:
            无。

        返回参数:
            ``MEDIA_BASE_URL + 文件路径`` 并附签名 query。

        使用示例:
            ``voice.signed_file_url``

        备注信息:
            地址用于运营台 ``<audio>`` 播放;签名 TTL 过期后需要重新取。
        """
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.file.url}")

    @property
    def duration_seconds(self) -> int:
        """时长(秒,四舍五入),运营台展示用。

        参数说明:
            无。

        返回参数:
            至少为 1 的整秒数。

        使用示例:
            ``voice.duration_seconds``

        备注信息:
            下限钳到 1 秒,避免极短语音在展示层出现 ``0`` 秒。
        """
        return max(1, round(self.duration_ms / 1000))

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``chat_voice#主键(owner=发送者 id)``。

        使用示例:
            ``str(voice)``

        备注信息:
            只读 ``owner_id``,不触发 ``owner`` 关联查询。
        """
        return f"chat_voice#{self.pk}(owner={self.owner_id})"
