"""发现页接口的路由:候选卡片、今日精选、滑卡、撤销与每日额度。

本文件挂载在 ``/api/v1/discovery/`` 前缀下;配对列表在 ``/api/v1/matches``,
由 ``config/api_urls.py`` 直接挂载。接口契约见 docs/api/discovery.md。
"""

from django.urls import path

from . import views

urlpatterns = [
    path("candidates", views.candidates),
    # 批次 S:今日精选(复用候选池,种子 = 日期 + 用户 id)
    path("daily", views.daily),
    path("swipe", views.swipe),
    # 批次 O:撤销上一次滑卡 + 每日喜欢额度(配额查的是 Redis 计数,不查库)
    path("swipe/undo", views.swipe_undo),
    path("quota", views.quota_view),
    path("likes", views.likes_received),
    path("likes/count", views.likes_received_count),
    path("visits", views.visits),
    path("visits/count", views.visits_count),
]
