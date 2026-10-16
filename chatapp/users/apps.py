"""users 应用的 AppConfig。"""

from django.apps import AppConfig


class UsersConfig(AppConfig):
    """用户资料应用的配置:资料、照片、标签、择偶偏好与在线状态。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "users"
