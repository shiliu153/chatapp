"""审核台的路由表(挂在 ``/ops/`` 下,不在 ``/api/v1`` 内)。

设计要点:
    以 ``/`` 结尾的是整页,不带结尾斜杠的是 HTMX 局部刷新端点
    (``handle`` / ``ban`` / ``review`` / ``delete`` / ``add`` / ``toggle``),
    两者返回的模板粒度不同。

注意事项:
    ``allowlist/`` 与 ``allowlist/<int:entry_id>/toggle`` 不会互相吞路由:
    前者带斜杠且是字面量,``add`` 也是字面量,``<int:>`` 只吃数字。

文件信息:
    文件名称          ops/urls.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import OpsLoginForm
from .otp import otp_verify

app_name = "ops"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(
        template_name="ops/login.html",
        authentication_form=OpsLoginForm,
        redirect_authenticated_user=True,
    ), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="ops:login"), name="logout"),
    path("otp/", otp_verify, name="otp"),
    path("reports/", views.reports_list, name="reports"),
    path("reports/<int:report_id>/", views.report_detail, name="report_detail"),
    path("reports/<int:report_id>/handle", views.report_handle, name="report_handle"),
    path("reports/<int:report_id>/ban", views.report_ban, name="report_ban"),
    path("photos/", views.photos, name="photos"),
    path("photos/review", views.photo_review, name="photo_review"),
    path("chat-images/", views.chat_images, name="chat_images"),
    path("chat-images/<int:image_id>/delete", views.chat_image_delete,
         name="chat_image_delete"),
    path("chat-voices/", views.chat_voices, name="chat_voices"),
    path("chat-voices/<int:voice_id>/delete", views.chat_voice_delete,
         name="chat_voice_delete"),
    path("users/", views.users_search, name="users"),
    path("users/<int:user_id>/", views.user_detail, name="user_detail"),
    path("users/<int:user_id>/ban", views.user_ban, name="user_ban"),
    path("metrics/", views.metrics, name="metrics"),
    path("logs/", views.logs, name="logs"),
    path("feedback/", views.feedback_list, name="feedback"),
    path("feedback/<int:feedback_id>/handle", views.feedback_handle,
         name="feedback_handle"),
    path("posts/", views.posts, name="posts"),
    path("posts/<int:post_id>/delete", views.post_delete, name="post_delete"),
    path("post-reports/", views.post_reports, name="post_reports"),
    path("post-reports/<int:report_id>/handle", views.post_report_handle,
         name="post_report_handle"),
    path("post-reports/<int:report_id>/delete-post", views.post_report_delete_post,
         name="post_report_delete_post"),
    path("allowlist/", views.allowlist_page, name="allowlist"),
    path("allowlist/add", views.allowlist_add, name="allowlist_add"),
    path("allowlist/<int:entry_id>/toggle", views.allowlist_toggle,
         name="allowlist_toggle"),
]
