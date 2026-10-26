"""IM 应用的本地数据模型:聊天图片元数据。

消息本身仍存在自建 imserver 的库(或腾讯云侧),Django 这边只落**图片文件**
的元数据,用于运营抽审、删除审计与注销清理。

设计要点:
    1. 文件名带随机 uuid(由视图生成),不用自增主键 —— 防止顺着 URL 遍历别人的私聊图;
    2. 运营删除只改 ``status`` 并留 ``deleted_by/deleted_at``,不删行 —— 审计可查;
    3. ``width/height`` 存的是**显示尺寸**(已按 EXIF 方向校正),不是文件原始像素。
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

    Attributes:
        deleted_by: 执行删除的运营账号;未删除时为 ``None``。
        deleted_at: 删除时间;未删除时为 ``None``。
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

        Returns:
            ``MEDIA_BASE_URL + 文件路径`` 并附签名 query。
        """
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.file.url}")

    @property
    def signed_thumb_url(self) -> str:
        """运营台预览用:带签名的缩略图绝对地址。

        Returns:
            ``MEDIA_BASE_URL + 缩略图路径`` 并附签名 query。
        """
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.thumb.url}")

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``chat_image#主键(owner=发送者 id)``。
        """
        return f"chat_image#{self.pk}(owner={self.owner_id})"
