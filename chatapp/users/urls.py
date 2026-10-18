"""用户资料相关接口的路由。

本文件挂载在 ``/api/v1/users/`` 前缀下;``me`` 系列是当前用户自身资源,
``<int:user_id>`` 是他人公开资料卡。接口契约见 docs/api/users.md。
"""

from django.urls import path

from . import views

urlpatterns = [
    path("me", views.me),
    path("me/photos", views.upload_photo),
    path("me/photos/<int:photo_id>", views.delete_photo),
    path("me/preference", views.my_preference),
    path("tags", views.tag_list),
    path("<int:user_id>", views.public_profile),
]
