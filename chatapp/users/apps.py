"""users 应用的 AppConfig。

文件信息:
    文件名称          users/apps.py
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


class UsersConfig(AppConfig):
    """用户资料应用的配置:资料、照片、标签、择偶偏好与在线状态。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "users"
