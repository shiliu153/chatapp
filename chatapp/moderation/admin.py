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

        参数说明:
            request: 当前后台请求,用于记录处理人。
            obj: 待保存的举报对象。
            form: 后台表单。
            change: ``True`` 表示修改已有对象。

        返回参数:
            无返回值。

        使用示例:
            ``model_admin.save_model(request, obj, form=None, change=True)``(见 ``moderation/tests.py``
            的 ``ReportAdminTests.test_handling_report_fills_handler_and_time``);
            运营实际是在 ``/admin/moderation/report/<id>/change/`` 把状态改成「已处理」再保存。

        备注信息:
            只在「首次处理」那一次动作:``status`` 已是 ``handled`` 且 ``handled_at`` 仍为空时,
            补 ``handled_at`` 与 ``handled_by``,保存后调 ``notify_report_handled`` 通知举报者;
            重复保存已处理的举报不会再发通知(判定见本方法首行的 ``first_handling``)。
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

        参数说明:
            request: Django admin 传入的请求对象。

        返回参数:
            恒为 ``False``。

        使用示例:
            ``model_admin.has_add_permission(request)``(见 ``moderation/tests.py`` 的
            ``ReportAdminTests.test_block_and_banlog_admins_are_readonly``);
            后台表现是 ``/admin/moderation/block/`` 没有「增加」按钮。

        备注信息:
            拉黑还要同步 IM 黑名单并撤销聊天权限,只写 ``Block`` 表对方仍能发来消息;
            Django admin 据返回值隐藏新增入口,绕过界面直接 POST 也会被拒。
        """
        return False

    def has_change_permission(self, request, obj=None):
        """禁止编辑:黑名单记录只读。

        参数说明:
            request: Django admin 传入的请求对象。
            obj: 目标对象;新增场景为 ``None``。

        返回参数:
            恒为 ``False``。

        使用示例:
            ``model_admin.has_change_permission(request)``(见 ``moderation/tests.py`` 的
            ``ReportAdminTests.test_block_and_banlog_admins_are_readonly``)

        备注信息:
            ``/admin/moderation/block/<id>/change/`` 只显示不可编辑;解除拉黑必须走 App 接口
            (``DELETE /api/v1/blocks/{user_id}``),否则 IM 黑名单与配对权限不会同步。
        """
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止删除:解除拉黑必须走 App 接口才能同步 IM 黑名单。

        参数说明:
            request: Django admin 传入的请求对象。
            obj: 目标对象;新增场景为 ``None``。

        返回参数:
            恒为 ``False``。

        使用示例:
            ``model_admin.has_delete_permission(request)``(见 ``moderation/tests.py`` 的
            ``ReportAdminTests.test_block_and_banlog_admins_are_readonly``)

        备注信息:
            后台删行不会触发 ``sync_im_blacklist(..., add=False)``,对方的 IM 黑名单会残留,
            因此本页干脆不给删除入口。
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

        参数说明:
            request: Django admin 传入的请求对象。

        返回参数:
            恒为 ``False``。

        使用示例:
            ``model_admin.has_add_permission(request)``(见 ``moderation/tests.py`` 的
            ``ReportAdminTests.test_block_and_banlog_admins_are_readonly``);
            后台表现是 ``/admin/moderation/banlog/`` 没有「增加」按钮。

        备注信息:
            审计行只由 ``moderation.services.log_ban_change`` 经 ``_write_log`` 写入;
            手工补行会和 ``Profile.ban_reason`` 上的当前状态对不上。
        """
        return False

    def has_change_permission(self, request, obj=None):
        """禁止编辑:审计记录不可篡改。

        参数说明:
            request: Django admin 传入的请求对象。
            obj: 目标对象;新增场景为 ``None``。

        返回参数:
            恒为 ``False``。

        使用示例:
            ``model_admin.has_change_permission(request)``(见 ``moderation/tests.py`` 的
            ``ReportAdminTests.test_block_and_banlog_admins_are_readonly``)

        备注信息:
            动作与原因只能靠新的封禁/解封动作落新行,历史行保持原样;
            ``/admin/moderation/banlog/<id>/change/`` 因此只读。
        """
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止删除:审计记录不可抹除。

        参数说明:
            request: Django admin 传入的请求对象。
            obj: 目标对象;新增场景为 ``None``。

        返回参数:
            恒为 ``False``。

        使用示例:
            ``model_admin.has_delete_permission(request)``(见 ``moderation/tests.py`` 的
            ``ReportAdminTests.test_block_and_banlog_admins_are_readonly``)

        备注信息:
            审计流水是事后追责凭证,删行等于抹掉「谁在什么时候封了谁」;
            需要纠正时补一条新的动作行,不改旧行。
        """
        return False
