from django.contrib import admin

from .models import Photo, Preference, Profile, Tag


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "nickname", "gender", "city", "status")
    list_filter = ("status", "gender")
    search_fields = ("nickname", "user__phone")


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
