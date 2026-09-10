from django.urls import path

from . import views

urlpatterns = [
    path("user_sig", views.user_sig),
]
