"""accounts 应用的 AppConfig。"""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """账号与鉴权应用的配置:手机号登录、短信验证码、JWT 签发。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        """导入需要在启动时完成「注册」的模块。

        两件事都靠「被导入」生效:
            1. ``schema``:drf-spectacular 的扩展类在定义时注册,不导入就会悄悄退化成
               无认证方案(D-5);
            2. ``checks``:``@register(Tags.security)`` 的系统检查要进 ``manage.py check``,
               漏导入则 ``accounts.E001`` 永远不会报(R4 M-1 的部署期门禁)。
        """
        from . import checks  # noqa: F401  # 导入即注册,模块名本身不需要使用
        from . import schema  # noqa: F401  # 导入即注册,模块名本身不需要使用
