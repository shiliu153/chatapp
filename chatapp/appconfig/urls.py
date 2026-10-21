"""appconfig 路由。"""

from django.urls import path

from .views import app_config

urlpatterns = [
    path("config", app_config),
]
