"""使用报告接口的路由。

本文件挂载在 ``/api/v1/stats/`` 前缀下;接口契约见 docs/api/stats.md。

文件信息:
    文件名称          stats/urls.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.urls import path

from . import views

urlpatterns = [
    path("me", views.my_stats),
]
