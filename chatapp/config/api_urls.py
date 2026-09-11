from django.urls import include, path

from accounts.views import health
from discovery import views as discovery_views

urlpatterns = [
    path("health", health),
    path("auth/", include("accounts.urls")),
    path("users/", include("users.urls")),
    path("im/", include("im.urls")),
    path("discovery/", include("discovery.urls")),
    path("", include("moderation.urls")),
    path("matches", discovery_views.match_list),
]
