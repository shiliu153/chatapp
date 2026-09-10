from django.urls import path

from . import views

urlpatterns = [
    path("me", views.me),
    path("tags", views.tag_list),
]
