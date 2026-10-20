"""意见反馈的路由表。"""

from django.urls import path

from . import views

urlpatterns = [
    path("feedback", views.create_feedback),
]
