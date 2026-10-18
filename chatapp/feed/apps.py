"""feed 应用的 AppConfig。"""

from django.apps import AppConfig


class FeedConfig(AppConfig):
    """广场应用的配置:动态、配图、点赞、评论与动态举报。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "feed"
