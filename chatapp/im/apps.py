"""im 应用的 AppConfig。"""

from django.apps import AppConfig


class ImConfig(AppConfig):
    """腾讯云 IM 集成应用的配置:userSig 签发与 IM 副作用任务。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "im"
