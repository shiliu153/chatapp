"""appconfig 应用配置。"""

from django.apps import AppConfig


class AppconfigConfig(AppConfig):
    """应用版本配置 app。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "appconfig"
