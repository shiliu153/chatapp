from django.contrib import admin
from django.utils import timezone

from .models import BanLog, Block, Report, ReportStatus


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "type", "status", "reporter", "target", "created_at", "handled_by")
    list_filter = ("status", "type")
    search_fields = ("reporter__phone", "target__phone", "detail")
    readonly_fields = ("created_at", "handled_at", "handled_by")
    # 倒序排:字符串降序让 "pending" 排在 "handled" 前面,打开就是待办
    ordering = ("-status", "-created_at")

    def save_model(self, request, obj, form, change):
        if obj.status == ReportStatus.HANDLED and obj.handled_at is None:
            obj.handled_at = timezone.now()
            obj.handled_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    """只读对账页:拉黑必须走 App 接口(要同步 IM),手工加会漏。"""

    list_display = ("id", "blocker", "blocked", "created_at")
    search_fields = ("blocker__phone", "blocked__phone")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BanLog)
class BanLogAdmin(admin.ModelAdmin):
    """只读审计页:只增不改。"""

    list_display = ("id", "user", "action", "reason", "operator", "created_at")
    list_filter = ("action",)
    search_fields = ("user__phone",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
