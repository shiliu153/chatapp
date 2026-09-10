from django.urls import path

from . import views

urlpatterns = [
    path("sms/send", views.sms_send),
]
