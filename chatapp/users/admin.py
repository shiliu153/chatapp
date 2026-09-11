from django.contrib import admin
from django.utils.html import format_html

from moderation.services import log_ban_change

from .models import Photo, PhotoStatus, Preference, Profile, Tag


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "nickname", "gender", "city", "status", "ban_reason")
    list_filter = ("status", "gender")
    search_fields = ("nickname", "user__phone")

    def save_model(self, request, obj, form, change):
        old_status = None
        if change:
            old_status = (Profile.objects.filter(pk=obj.pk)
                          .values_list("status", flat=True).first())
        super().save_model(request, obj, form, change)
        log_ban_change(obj.user, old_status, obj.status, obj.ban_reason, request.user)


@admin.action(description="通过所选照片")
def approve_photos(modeladmin, request, queryset):
    _review_photos(modeladmin, request, queryset, PhotoStatus.APPROVED)


@admin.action(description="驳回所选照片")
def reject_photos(modeladmin, request, queryset):
    _review_photos(modeladmin, request, queryset, PhotoStatus.REJECTED)


def _review_photos(modeladmin, request, queryset, status):
    user_ids = set(queryset.values_list("user_id", flat=True))
    count = queryset.count()
    queryset.update(status=status)
    # 照片数量变化会影响「资料完善」判定(掉回未完善 = 失去候选资格),必须重算
    for profile in Profile.objects.filter(user_id__in=user_ids):
        profile.refresh_status()
    modeladmin.message_user(request, f"已处理 {count} 张照片")


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "preview", "user", "status", "order", "created_at")
    list_filter = ("status",)
    actions = [approve_photos, reject_photos]

    @admin.display(description="预览")
    def preview(self, obj):
        if not obj.file:
            return "-"
        return format_html('<img src="{}" style="height:60px;border-radius:4px">', obj.file.url)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "icon")


@admin.register(Preference)
class PreferenceAdmin(admin.ModelAdmin):
    list_display = ("profile", "target_gender", "age_min", "age_max", "city")
