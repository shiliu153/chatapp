"""Django admin 中的用户管理配置。

设计要点:
    本项目用手机号作登录标识并移除了 ``username`` 字段,因此不能沿用 ``UserAdmin``
    的默认 fieldsets(它引用 ``username`` 会报错),必须显式自定义。
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """按手机号展示与管理用户的后台配置。"""

    model = User
    # username 已移除,不能用 UserAdmin 默认 fieldsets(它引用 username 会报错)
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("个人信息", {"fields": ("first_name", "last_name", "email")}),
        ("权限", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("重要日期", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("phone", "password1", "password2")}),
    )
    list_display = ("phone", "is_staff", "is_active")
    search_fields = ("phone",)
    ordering = ("id",)
