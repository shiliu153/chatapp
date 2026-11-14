"""stats 应用配置。

本应用包含两块:个人使用报告接口(``/api/v1/stats/me``,只读聚合)与每日运营指标
快照表 ``DailyMetric``(由 ``manage.py metrics_daily`` 每天写入一行)。

文件信息:
    文件名称          stats/apps.py
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


class StatsConfig(AppConfig):
    """个人使用报告 + 每日运营指标快照。

    参数说明:
        无构造参数;``name`` 与 ``default_auto_field`` 由本类属性给出,实例化由 Django
        装载 ``INSTALLED_APPS`` 时完成。

    返回参数:
        配置实例;注册进 Django 的 ``apps`` 注册表供运行期查询。

    使用示例:
        ``StatsConfig.create("stats")``

    备注信息:
        主键类型固定为 ``BigAutoField``;``name`` 必须与包目录名 ``stats`` 一致,否则
        模型与迁移的 ``app_label`` 会对不上。本应用不定义 ``ready()``:没有需要在启动时
        注册的扩展类或系统检查。
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "stats"
