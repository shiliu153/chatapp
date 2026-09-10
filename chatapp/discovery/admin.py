from django.contrib import admin

from .models import Match, Swipe


@admin.register(Swipe)
class SwipeAdmin(admin.ModelAdmin):
    list_display = ("id", "swiper", "target", "action", "created_at")
    list_filter = ("action",)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("id", "user_a", "user_b", "created_at")
