"""accounts 应用的 AppConfig。"""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """账号与鉴权应用的配置:手机号登录、短信验证码、JWT 签发。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        """导入 OpenAPI 扩展模块,让自定义 JWT 认证类在 schema 里可见(D-5)。

        drf-spectacular 的扩展类在定义时注册,只有被导入才生效。放在 ``ready()`` 里显式
        导入,是为了避免「某个入口忘了 import 就悄悄退化成无认证方案」这种静默漂移。
        """
        from . import schema  # noqa: F401  # 导入即注册,模块名本身不需要使用
