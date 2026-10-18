"""举报与拉黑接口的路由。

本文件挂在 ``/api/v1/`` 根前缀下(见 ``config/api_urls.py``);
接口契约见 docs/api/moderation.md。
"""

from django.urls import path

from . import views

urlpatterns = [
    path("reports", views.create_report),
    path("blocks", views.blocks),
    path("blocks/<int:user_id>", views.unblock),
]
