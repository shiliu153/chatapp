"""accounts 应用的 AppConfig。

文件信息:
    文件名称          accounts/apps.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """账号与鉴权应用的配置:手机号登录、短信验证码、JWT 签发。

    参数说明:
        无构造参数;``name`` 与 ``default_auto_field`` 由本类属性给出,
        实例化由 Django 装载 ``INSTALLED_APPS`` 时完成。

    返回参数:
        配置实例;注册进 Django 的 ``apps`` 注册表供运行期查询。

    使用示例:
        ``AccountsConfig.create("accounts")``

    备注信息:
        主键类型固定为 ``BigAutoField``;``name`` 必须与包目录名 ``accounts``
        一致,否则模型与迁移的 ``app_label`` 会对不上。
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        """导入需要在启动时完成「注册」的模块。

        两件事都靠「被导入」生效:
            1. ``schema``:drf-spectacular 的扩展类在定义时注册,不导入就会悄悄退化成
               无认证方案(D-5);
            2. ``checks``:``@register(Tags.security)`` 的系统检查要进 ``manage.py check``,
               漏导入则 ``accounts.E001`` 永远不会报(R4 M-1 的部署期门禁)。

        参数说明:
            无。

        返回参数:
            无返回值;副作用是完成扩展类与系统检查的注册。

        使用示例:
            ``AccountsConfig("accounts", "accounts").ready()``

        备注信息:
            两行导入都带 ``noqa: F401`` —— 模块名本身不使用,被导入即完成注册;
            漏掉任何一个都会让对应门禁静默失效,不报错也不告警。
        """
        from . import checks  # noqa: F401  # 导入即注册,模块名本身不需要使用
        from . import schema  # noqa: F401  # 导入即注册,模块名本身不需要使用
