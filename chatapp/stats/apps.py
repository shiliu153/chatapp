"""stats 应用配置。"""

from django.apps import AppConfig


class StatsConfig(AppConfig):
    """个人使用报告 + 每日运营指标快照。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "stats"
