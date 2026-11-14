"""``/api/v1/notifications/*`` 的子路由(站内通知中心)。

注意事项:
    1. 站内通知**不要**塞进 ``notifications/urls.py`` —— 那个文件挂在 ``/api/v1/push/``
       前缀下,塞进去会变成 ``/api/v1/push/notifications``(见计划 §4 H-2);
    2. 列表接口 ``GET /api/v1/notifications`` 由 ``config/api_urls.py`` 直接挂
       (与 ``/matches``、``/presence`` 同一写法):本项目的路由一律不带尾斜杠,
       若在这里用空路径再 include,会生成 ``/api/v1/notifications/`` 并触发 301,
       同时让文档门禁多出一个不存在的接口。

文件信息:
    文件名称          notifications/notification_urls.py
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
    path("unread_count", views.notification_unread_count),
    path("read", views.notification_read),
]
