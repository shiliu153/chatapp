"""notifications 应用的 AppConfig。

文件信息:
    文件名称          notifications/apps.py
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


class NotificationsConfig(AppConfig):
    """通知应用的配置:短信发送后端与通知类任务。

    参数说明:
        无构造参数;``name`` 与 ``default_auto_field`` 由本类属性给出,
        实例化由 Django 装载 ``INSTALLED_APPS`` 时完成。

    返回参数:
        配置实例;注册进 Django 的 ``apps`` 注册表供运行期查询。

    使用示例:
        ``NotificationsConfig.create("notifications")``

    备注信息:
        ``INSTALLED_APPS`` 里登记的是裸应用名 ``"notifications"``,由 Django 自行找到
        本类,因此不写 ``default_app_config``;主键类型固定 ``BigAutoField``,改它会
        与既有迁移的 ``id`` 列类型对不上。本应用没有 ``ready()`` 钩子:启动时不需要
        注册扩展类或系统检查,短信后端与推送通道都在调用点按配置现取。
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
