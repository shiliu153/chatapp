from django.urls import path

from . import views

urlpatterns = [
    path("reports", views.create_report),
    path("blocks", views.blocks),
    path("blocks/<int:user_id>", views.unblock),
]
