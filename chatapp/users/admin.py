from django.contrib import admin

from moderation.services import log_ban_change

from .models import Photo, Preference, Profile, Tag


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


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "order", "created_at")
    list_filter = ("status",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "icon")


@admin.register(Preference)
class PreferenceAdmin(admin.ModelAdmin):
    list_display = ("profile", "target_gender", "age_min", "age_max", "city")
