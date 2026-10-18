"""账号与鉴权接口的路由:发码、校验登录、刷新令牌。

本文件挂载在 ``/api/v1/auth/`` 前缀下;接口契约见 docs/api/auth.md。
"""

from django.urls import path

from . import views

urlpatterns = [
    path("sms/send", views.sms_send),
    path("sms/verify", views.sms_verify),
    path("token/refresh", views.SessionTokenRefreshView.as_view()),
]
