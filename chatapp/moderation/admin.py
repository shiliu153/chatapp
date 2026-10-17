"""Django admin 中的举报处理、黑名单与封禁审计。

设计要点:
    1. ``ReportAdmin`` 是举报的**实际处理入口**:首次标记「已处理」时补上处理人与
       处理时间,并给举报者发系统通知;
    2. ``BlockAdmin`` 与 ``BanLogAdmin`` 都是只读页 —— 拉黑必须走 App 接口(要同步
       IM 黑名单),封禁审计只增不改,手工增删都会破坏一致性。
"""

from django.contrib import admin
from django.utils import timezone

from .models import BanLog, Block, Report, ReportStatus
from .services import notify_report_handled


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """举报的后台处理页。"""

    list_display = ("id", "type", "status", "reporter", "target", "created_at", "handled_by")
    list_filter = ("status", "type")
    search_fields = ("reporter__phone", "target__phone", "detail")
    readonly_fields = ("created_at", "handled_at", "handled_by")
    # 倒序排:字符串降序让 "pending" 排在 "handled" 前面,打开就是待办
    ordering = ("-status", "-created_at")

    def save_model(self, request, obj, form, change):
        """保存举报,并在首次标记已处理时补审计字段与通知举报者。

        Args:
            request: 当前后台请求,用于记录处理人。
            obj: 待保存的举报对象。
            form: 后台表单。
            change: ``True`` 表示修改已有对象。
        """
        first_handling = obj.status == ReportStatus.HANDLED and obj.handled_at is None
        if first_handling:
            obj.handled_at = timezone.now()
            obj.handled_by = request.user
        super().save_model(request, obj, form, change)
        if first_handling:
            notify_report_handled(obj)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    """只读对账页:拉黑必须走 App 接口(要同步 IM),手工加会漏。"""

    list_display = ("id", "blocker", "blocked", "created_at")
    search_fields = ("blocker__phone", "blocked__phone")

    def has_add_permission(self, request):
        """禁止手工新增:拉黑必须走 App 接口才能同步 IM 黑名单。

        Args:
            request: Django admin 传入的请求对象。

        Returns:
            恒为 ``False``。
        """
        return False

    def has_change_permission(self, request, obj=None):
        """禁止编辑:黑名单记录只读。

        Args:
            request: Django admin 传入的请求对象。
            obj: 目标对象;新增场景为 ``None``。

        Returns:
            恒为 ``False``。
        """
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止删除:解除拉黑必须走 App 接口才能同步 IM 黑名单。

        Args:
            request: Django admin 传入的请求对象。
            obj: 目标对象;新增场景为 ``None``。

        Returns:
            恒为 ``False``。
        """
        return False


@admin.register(BanLog)
class BanLogAdmin(admin.ModelAdmin):
    """只读审计页:只增不改。"""

    list_display = ("id", "user", "action", "reason", "operator", "created_at")
    list_filter = ("action",)
    search_fields = ("user__phone",)

    def has_add_permission(self, request):
        """禁止手工新增:审计记录只能由封禁流程写入。

        Args:
            request: Django admin 传入的请求对象。

        Returns:
            恒为 ``False``。
        """
        return False

    def has_change_permission(self, request, obj=None):
        """禁止编辑:审计记录不可篡改。

        Args:
            request: Django admin 传入的请求对象。
            obj: 目标对象;新增场景为 ``None``。

        Returns:
            恒为 ``False``。
        """
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止删除:审计记录不可抹除。

        Args:
            request: Django admin 传入的请求对象。
            obj: 目标对象;新增场景为 ``None``。

        Returns:
            恒为 ``False``。
        """
        return False
