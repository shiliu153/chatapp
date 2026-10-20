"""feedback 应用配置。"""

from django.apps import AppConfig


class FeedbackConfig(AppConfig):
    """意见反馈应用。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "feedback"
