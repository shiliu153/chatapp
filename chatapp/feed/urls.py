"""广场动态接口的路由。

本文件挂在 ``/api/v1/`` 根前缀下(见 ``config/api_urls.py``);
接口契约见 docs/api/feed.md。

文件信息:
    文件名称          feed/urls.py
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

from . import views

urlpatterns = [
    path("posts", views.posts),
    path("posts/mine", views.my_posts),
    path("posts/<int:post_id>", views.post_detail),
    path("posts/<int:post_id>/like", views.post_like),
    # 点赞列表(批次 U):`/likes` 与 `/like` 分属两个接口 —— 前者读列表,后者写点赞
    path("posts/<int:post_id>/likes", views.post_likes),
    # 收藏 / 取消收藏(批次 U):POST 与 DELETE 同路径,恒 204 幂等
    path("posts/<int:post_id>/favorite", views.post_favorite),
    path("posts/<int:post_id>/comments", views.post_comments),
    path("posts/<int:post_id>/comments/<int:comment_id>/replies",
         views.post_comment_replies),
    path("posts/<int:post_id>/comments/<int:comment_id>", views.post_comment_detail),
    path("posts/<int:post_id>/report", views.post_report),
    # 关注流:路径带 ``feed/`` 前缀(计划 §4 I-2 定死的契约,App/Web 都按它接)
    path("feed/following", views.following_posts),
    # 我的收藏(批次 U):与关注流并列在 ``feed/`` 前缀下
    path("feed/favorites", views.favorite_posts),
]
