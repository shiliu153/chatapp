from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
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
