"""发现页接口的路由:候选卡片与滑卡。

本文件挂载在 ``/api/v1/discovery/`` 前缀下;配对列表在 ``/api/v1/matches``,
由 ``config/api_urls.py`` 直接挂载。接口契约见 docs/api/discovery.md。
"""

from django.urls import path

from . import views

urlpatterns = [
    path("candidates", views.candidates),
    path("swipe", views.swipe),
    path("likes", views.likes_received),
    path("likes/count", views.likes_received_count),
]
