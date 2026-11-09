"""使用报告接口的路由。

本文件挂载在 ``/api/v1/stats/`` 前缀下;接口契约见 docs/api/stats.md。
"""

from django.urls import path

from . import views

urlpatterns = [
    path("me", views.my_stats),
]
