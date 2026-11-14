"""feed 应用的 AppConfig。

文件信息:
    文件名称          feed/apps.py
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


class FeedConfig(AppConfig):
    """广场应用的配置:动态、配图、点赞、评论与动态举报。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "feed"
