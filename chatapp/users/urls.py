"""用户资料相关接口的路由。

本文件挂载在 ``/api/v1/users/`` 前缀下;``me`` 系列是当前用户自身资源,
``<int:user_id>`` 是他人公开资料卡,``<int:user_id>/follow`` 是关注关系
(视图在 ``feed.views``:关系语义归 feed,路由仍挂在 users 下)。
接口契约见 docs/api/users.md 与 docs/api/feed.md。

注意事项:
    ``<int:user_id>/follow`` 必须排在 ``<int:user_id>`` **之前**:Django 按顺序
    匹配,``<int:user_id>`` 匹配不到 ``12/follow`` 这种两段路径,但把具体路由放前面
    可以避免以后有人把 ``user_id`` 改成 ``<str:...>`` 时静默吞掉子路径。

文件信息:
    文件名称          users/urls.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.urls import path

from feed import views as feed_views

from . import views

urlpatterns = [
    path("me", views.me),
    path("me/photos", views.upload_photo),
    path("me/photos/<int:photo_id>", views.delete_photo),
    path("me/voice", views.my_voice),
    path("me/preference", views.my_preference),
    path("tags", views.tag_list),
    path("<int:user_id>/follow", feed_views.follow_user),
    path("<int:user_id>", views.public_profile),
]
