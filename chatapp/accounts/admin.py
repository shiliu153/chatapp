"""Django admin 中的用户管理配置。

设计要点:
    本项目用手机号作登录标识并移除了 ``username`` 字段,因此不能沿用 ``UserAdmin``
    的默认 fieldsets(它引用 ``username`` 会报错),必须显式自定义。

文件信息:
    文件名称          accounts/admin.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """按手机号展示与管理用户的后台配置。

    参数说明:
        model: 受管模型,由类属性 ``model = User`` 给出。
        admin_site: 后台站点实例,由 ``@admin.register(User)`` 传入。

    返回参数:
        模型管理实例;登记为 ``User`` 在 ``/admin/`` 下的管理类。

    使用示例:
        ``CustomUserAdmin(User, admin.site)``

    备注信息:
        ``username`` 字段已从模型移除,``fieldsets`` / ``add_fieldsets`` 必须整体
        重写 —— 沿用 ``UserAdmin`` 的默认值会因引用 ``username`` 报错。
    """

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
