from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import OpsLoginForm

app_name = "ops"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(
        template_name="ops/login.html",
        authentication_form=OpsLoginForm,
        redirect_authenticated_user=True,
    ), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="ops:login"), name="logout"),
    path("reports/", views.reports_list, name="reports"),
    path("reports/<int:report_id>/", views.report_detail, name="report_detail"),
    path("reports/<int:report_id>/handle", views.report_handle, name="report_handle"),
    path("reports/<int:report_id>/ban", views.report_ban, name="report_ban"),
    path("photos/", views.photos, name="photos"),
    path("photos/review", views.photo_review, name="photo_review"),
    path("users/", views.users_search, name="users"),
    path("users/<int:user_id>/", views.user_detail, name="user_detail"),
]
