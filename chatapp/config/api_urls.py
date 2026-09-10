from django.urls import include, path

from accounts.views import health

urlpatterns = [
    path("health", health),
    path("auth/", include("accounts.urls")),
    path("users/", include("users.urls")),
    path("im/", include("im.urls")),
]
