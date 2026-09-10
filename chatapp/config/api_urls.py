from django.urls import path

from accounts.views import health

urlpatterns = [
    path("health", health),
]
