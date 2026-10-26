"""IM 接口的路由:签发 userSig、上传聊天图片。

本文件挂载在 ``/api/v1/im/`` 前缀下;接口契约见 docs/api/im.md。
"""

from django.urls import path

from . import views

urlpatterns = [
    path("user_sig", views.user_sig),
    path("images", views.upload_image),
]
