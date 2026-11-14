"""``/api/v1`` 的路由表:把各业务 app 的 URLconf 挂到对应前缀下。

设计要点:
    ``matches``、``presence``、``devices`` 直接挂在根前缀(即 ``/api/v1/matches``、
    ``/api/v1/presence``、``/api/v1/devices``),其余接口按 app 分组。

注意事项:
    改动本文件的路径会同时影响 ``ApiDocsCoverageTests`` 的双向比对 ——
    新增或删除接口时必须在同一次改动内同步 ``docs/api/`` 对应分册。

文件信息:
    文件名称          config/api_urls.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.urls import include, path

from accounts.views import device_logout, devices, health, readyz
from discovery import views as discovery_views
from notifications import views as notifications_views
from users import views as users_views

urlpatterns = [
    path("health", health),
    path("readyz", readyz),
    path("auth/", include("accounts.urls")),
    path("users/", include("users.urls")),
    path("im/", include("im.urls")),
    path("app/", include("appconfig.urls")),
    path("discovery/", include("discovery.urls")),
    path("", include("moderation.urls")),
    path("", include("feed.urls")),
    path("", include("feedback.urls")),
    path("", include("telemetry.urls")),
    path("push/", include("notifications.urls")),
    path("stats/", include("stats.urls")),
    path("notifications", notifications_views.notification_list),
    path("notifications/", include("notifications.notification_urls")),
    path("matches", discovery_views.match_list),
    path("matches/<int:user_id>", discovery_views.unmatch),
    path("presence", users_views.presence_status),
    path("devices", devices),
    path("devices/<str:client_type>", device_logout),
]
