"""moderation 应用的 AppConfig。"""

from django.apps import AppConfig


class ModerationConfig(AppConfig):
    """合规应用的配置:举报、拉黑、封禁权限与审计。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "moderation"
