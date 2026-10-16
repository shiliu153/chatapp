"""notifications 应用的 AppConfig。"""

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """通知应用的配置:短信发送后端与通知类任务。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
