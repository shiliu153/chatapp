from django.urls import path

from . import views

urlpatterns = [
    path("me", views.me),
    path("me/photos", views.upload_photo),
    path("me/photos/<int:photo_id>", views.delete_photo),
    path("me/preference", views.my_preference),
    path("tags", views.tag_list),
]
