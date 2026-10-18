"""``/api/v1`` 的路由表:把各业务 app 的 URLconf 挂到对应前缀下。

设计要点:
    ``matches`` 与 ``presence`` 直接挂在根前缀(即 ``/api/v1/matches``、
    ``/api/v1/presence``),其余接口按 app 分组。

注意事项:
    改动本文件的路径会同时影响 ``ApiDocsCoverageTests`` 的双向比对 ——
    新增或删除接口时必须在同一次改动内同步 ``docs/api/`` 对应分册。
"""

from django.urls import include, path

from accounts.views import health, readyz
from discovery import views as discovery_views
from users import views as users_views

urlpatterns = [
    path("health", health),
    path("readyz", readyz),
    path("auth/", include("accounts.urls")),
    path("users/", include("users.urls")),
    path("im/", include("im.urls")),
    path("discovery/", include("discovery.urls")),
    path("", include("moderation.urls")),
    path("", include("feed.urls")),
    path("matches", discovery_views.match_list),
    path("presence", users_views.presence_status),
]
