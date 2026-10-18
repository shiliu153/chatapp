"""Django admin 中的资料、照片与标签管理。

设计要点:
    照片审核动作与 ``ops`` 审核台共用 ``users.services.review_photos``,
    保证两条路径的审计记录与资料状态重算完全一致。
"""

from django.contrib import admin
from django.utils.html import format_html

from moderation.services import log_ban_change

from .models import Photo, PhotoStatus, Preference, Profile, Tag
from .services import review_photos


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """资料的后台管理,保存时记录封禁变更审计。"""

    list_display = ("user", "nickname", "gender", "city", "status", "ban_reason")
    list_filter = ("status", "gender")
    search_fields = ("nickname", "user__phone")

    def save_model(self, request, obj, form, change):
        """保存资料,并记录封禁状态变更。

        改动前先取旧状态,保存后交给 ``log_ban_change`` 比对 —— 只有真正发生
        封禁/解封时才会写审计记录。

        Args:
            request: 当前后台请求。
            obj: 待保存的资料对象。
            form: 后台表单。
            change: ``True`` 表示修改已有对象,``False`` 表示新建。
        """
        old_status = None
        if change:
            old_status = (Profile.objects.filter(pk=obj.pk)
                          .values_list("status", flat=True).first())
        super().save_model(request, obj, form, change)
        log_ban_change(obj.user, old_status, obj.status, obj.ban_reason, request.user)


@admin.action(description="通过所选照片")
def approve_photos(modeladmin, request, queryset):
    """批量过审所选照片。

    Args:
        modeladmin: 当前 ModelAdmin 实例。
        request: 当前后台请求。
        queryset: 选中的照片查询集。
    """
    _review_photos(modeladmin, request, queryset, PhotoStatus.APPROVED)


@admin.action(description="驳回所选照片")
def reject_photos(modeladmin, request, queryset):
    """批量驳回所选照片。

    Args:
        modeladmin: 当前 ModelAdmin 实例。
        request: 当前后台请求。
        queryset: 选中的照片查询集。
    """
    _review_photos(modeladmin, request, queryset, PhotoStatus.REJECTED)


def _review_photos(modeladmin, request, queryset, status):
    """两个审核动作的公共实现:调用服务层并回显处理条数。

    Args:
        modeladmin: 当前 ModelAdmin 实例,用于回显消息。
        request: 当前后台请求。
        queryset: 选中的照片查询集。
        status: 目标审核状态。
    """
    count = review_photos(queryset, status, request.user)
    modeladmin.message_user(request, f"已处理 {count} 张照片")


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    """照片的后台管理:带缩略图预览与批量审核动作。"""

    list_display = ("id", "preview", "user", "status", "order", "created_at")
    list_filter = ("status",)
    actions = [approve_photos, reject_photos]

    @admin.display(description="预览")
    def preview(self, obj):
        """在列表页渲染照片缩略图。

        Args:
            obj: 当前照片对象。

        Returns:
            限高 60px 的 ``<img>`` 标签;没有文件时返回 ``-``。
        """
        if not obj.file:
            return "-"
        return format_html('<img src="{}" style="height:60px;border-radius:4px">', obj.file.url)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """标签池的后台管理。"""

    list_display = ("id", "name", "icon")


@admin.register(Preference)
class PreferenceAdmin(admin.ModelAdmin):
    """择偶偏好的后台管理。"""

    list_display = ("profile", "target_gender", "age_min", "age_max", "city")
