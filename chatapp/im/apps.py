"""im 应用的 AppConfig。

文件信息:
    文件名称          im/apps.py
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


class ImConfig(AppConfig):
    """IM 集成应用的配置:凭证签发与 IM 副作用任务。

    参数说明:
        无构造参数;``name`` 与 ``default_auto_field`` 由本类属性给出,
        实例化由 Django 装载 ``INSTALLED_APPS`` 时完成。

    返回参数:
        配置实例;注册进 Django 的 ``apps`` 注册表供运行期查询。

    使用示例:
        ``ImConfig.create("im")``

    备注信息:
        ``INSTALLED_APPS`` 里登记的是裸应用名 ``"im"``,由 Django 自行找到本类,
        因此不写 ``default_app_config``。主键类型固定为 ``BigAutoField``;``name``
        必须与包目录名 ``im`` 一致,否则模型与迁移的 ``app_label`` 会对不上。
        与 accounts 不同,本应用没有 ``ready()`` 钩子:启动时不需要注册扩展类或系统检查。
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "im"
