from django.urls import path

from . import views

urlpatterns = [
    path("posts", views.posts),
    path("posts/mine", views.my_posts),
    path("posts/<int:post_id>", views.post_detail),
    path("posts/<int:post_id>/like", views.post_like),
    path("posts/<int:post_id>/comments", views.post_comments),
]
