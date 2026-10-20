"""``/api/v1/push`` 的子路由。"""

from django.urls import path

from . import views

urlpatterns = [
    path("devices", views.register_device),
    path("devices/<str:registration_id>", views.unregister_device),
    path("preferences", views.preferences),
]
