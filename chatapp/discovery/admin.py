"""Django admin 中的滑卡与配对记录管理。

两个模型都只做只读性质的查看:滑卡与配对由业务写入,
后台不提供编辑入口,避免手工改数据破坏唯一约束与幂等语义。
"""

from django.contrib import admin

from .models import Match, Swipe


@admin.register(Swipe)
class SwipeAdmin(admin.ModelAdmin):
    """滑卡记录的后台管理。"""

    list_display = ("id", "swiper", "target", "action", "created_at")
    list_filter = ("action",)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    """配对记录的后台管理。"""

    list_display = ("id", "user_a", "user_b", "created_at")
