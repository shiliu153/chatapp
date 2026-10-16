"""accounts 应用的 AppConfig。"""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """账号与鉴权应用的配置:手机号登录、短信验证码、JWT 签发。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
