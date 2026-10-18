"""discovery 应用的 AppConfig。"""

from django.apps import AppConfig


class DiscoveryConfig(AppConfig):
    """发现页应用的配置:候选卡片、滑卡与配对。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "discovery"
