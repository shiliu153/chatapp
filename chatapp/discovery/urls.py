from django.urls import path

from . import views

urlpatterns = [
    path("candidates", views.candidates),
]
