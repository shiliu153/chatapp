from django.urls import path

from . import views

urlpatterns = [
    path("sms/send", views.sms_send),
    path("sms/verify", views.sms_verify),
    path("token/refresh", views.SessionTokenRefreshView.as_view()),
]
