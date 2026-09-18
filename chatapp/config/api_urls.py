from django.urls import include, path

from accounts.views import health, readyz
from discovery import views as discovery_views
from users import views as users_views

urlpatterns = [
    path("health", health),
    path("readyz", readyz),
    path("auth/", include("accounts.urls")),
    path("users/", include("users.urls")),
    path("im/", include("im.urls")),
    path("discovery/", include("discovery.urls")),
    path("", include("moderation.urls")),
    path("", include("feed.urls")),
    path("matches", discovery_views.match_list),
    path("presence", users_views.presence_status),
]
