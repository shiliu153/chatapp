"""客户端错误上报的路由表。"""

from django.urls import path

from . import views

urlpatterns = [
    path("client-errors", views.report_client_error),
]
