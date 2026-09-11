from django.urls import path

from . import views

urlpatterns = [
    path("reports", views.create_report),
]
