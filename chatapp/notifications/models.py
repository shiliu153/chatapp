"""推送相关的持久化模型:设备与通知偏好。

设计要点:
    1. ``registration_id`` 全局唯一:同一台设备换账号登录时设备易主,
       旧账号自然失去这台设备(与单设备登录一致);
    2. 偏好是账号级、不预建:``NotificationPreference.for_user`` 读取时
       才落库,默认全开;注销随用户 CASCADE 删除。
"""

from django.conf import settings
from django.db import models


class PushPlatform(models.TextChoices):
    """推送设备平台。"""

    ANDROID = "android", "Android"
    IOS = "ios", "iOS"


class PushDevice(models.Model):
    """一台接收推送的设备(以极光 registration_id 标识)。"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="push_devices")
    registration_id = models.CharField("极光 registration_id", max_length=128, unique=True)
    platform = models.CharField("平台", max_length=16, choices=PushPlatform.choices)
    app_version = models.CharField("App 版本", max_length=32, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "推送设备"
        verbose_name_plural = "推送设备"

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``用户 id:平台:registration_id``。
        """
        return f"{self.user_id}:{self.platform}:{self.registration_id}"


class NotificationPreference(models.Model):
    """账号级通知偏好;三类通知默认全开。"""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="notification_preference")
    likes = models.BooleanField("新的喜欢", default=True)
    matches = models.BooleanField("配对成功", default=True)
    system = models.BooleanField("系统通知", default=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "通知偏好"
        verbose_name_plural = "通知偏好"

    @classmethod
    def for_user(cls, user):
        """取(必要时创建)用户的通知偏好。

        Args:
            user: 目标用户。

        Returns:
            该用户的 ``NotificationPreference`` 实例。
        """
        preference, _ = cls.objects.get_or_create(user=user)
        return preference

    def allows(self, kind: str) -> bool:
        """判断某一类通知是否开启。

        Args:
            kind: 通知类型,取值 ``like`` / ``match`` / ``system``。

        Returns:
            开启返回 ``True``;未知类型返回 ``False``(宁可不发)。
        """
        return {
            "like": self.likes,
            "match": self.matches,
            "system": self.system,
        }.get(kind, False)
