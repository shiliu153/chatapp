"""telemetry 应用配置(客户端错误上报;无数据模型)。"""

from django.apps import AppConfig


class TelemetryConfig(AppConfig):
    """遥测应用:只接收前端上报并写日志,不落库、不建表。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "telemetry"
