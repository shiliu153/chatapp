"""广场动态接口的路由。

本文件挂在 ``/api/v1/`` 根前缀下(见 ``config/api_urls.py``);
接口契约见 docs/api/feed.md。
"""

from django.urls import path

from . import views

urlpatterns = [
    path("posts", views.posts),
    path("posts/mine", views.my_posts),
    path("posts/<int:post_id>", views.post_detail),
    path("posts/<int:post_id>/like", views.post_like),
    path("posts/<int:post_id>/comments", views.post_comments),
    path("posts/<int:post_id>/comments/<int:comment_id>/replies",
         views.post_comment_replies),
    path("posts/<int:post_id>/report", views.post_report),
]
