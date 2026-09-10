from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path("sms/send", views.sms_send),
    path("sms/verify", views.sms_verify),
    path("token/refresh", TokenRefreshView.as_view()),
]
