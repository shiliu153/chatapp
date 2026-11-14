"""Django admin 中的举报处理、黑名单与封禁审计。

设计要点:
    1. ``ReportAdmin`` 是举报的**实际处理入口**:首次标记「已处理」时补上处理人与
       处理时间,并给举报者发系统通知;
    2. ``BlockAdmin`` 与 ``BanLogAdmin`` 都是只读页 —— 拉黑必须走 App 接口(要同步
       IM 黑名单),封禁审计只增不改,手工增删都会破坏一致性。

文件信息:
    文件名称          moderation/admin.py
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
from django.utils import timezone

from .models import BanLog, Block, Report, ReportStatus
from .services import notify_report_handled


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """举报的后台处理页。

    参数说明:
        model: 被注册的模型,固定为 ``Report``。
        admin_site: admin 站点实例(默认为 ``django.contrib.admin.site``)。

    返回参数:
        后台配置对象;列表页与编辑页的行为由下方属性与 ``save_model`` 决定。

    使用示例:
        ``@admin.register(Report)`` 装饰后由 ``ModerationConfig`` 自动加载。

    备注信息:
        它是举报的**实际处理入口**:运营把状态改成 ``handled`` 保存即完成处理;
        ``handled_by`` / ``handled_at`` / ``created_at`` 只读,不给手改。
        列表按 ``-status`` 倒序 —— 字符串降序让 ``pending`` 排在 ``handled`` 前面,
        打开就是待办。
    """

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
            ``ReportAdmin(Report, admin.site).save_model(request, obj, form, change=True)``

        备注信息:
            「首次处理」判定为 ``status == handled`` 且 ``handled_at is None`` ——
            重复保存已处理的举报不会覆盖处理人/时间,也不会再发通知。
            补字段必须在 ``super().save_model`` **之前**,通知放在**之后**,
            否则会先通知、后落库,事务回滚时留下一条无记录的灰条。
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
    """只读对账页:拉黑必须走 App 接口(要同步 IM),手工加会漏。

    参数说明:
        model: 被注册的模型,固定为 ``Block``。
        admin_site: admin 站点实例(默认为 ``django.contrib.admin.site``)。

    返回参数:
        后台配置对象;增删改三处权限全部返回 ``False``,页面只能查看与搜索。

    使用示例:
        ``@admin.register(Block)`` 装饰后由 ``ModerationConfig`` 自动加载。

    备注信息:
        保留这个页是为了**对账**:运营要能查某两人之间有没有拉黑关系,以及
        由谁在何时发起;写入一律走 ``POST /api/v1/blocks``(那里才会同步 IM 黑名单
        并撤销聊天权限),手工新增会留下「本地有记录、IM 不知道」的半截状态。
    """

    list_display = ("id", "blocker", "blocked", "created_at")
    search_fields = ("blocker__phone", "blocked__phone")

    def has_add_permission(self, request):
        """禁止手工新增:拉黑必须走 App 接口才能同步 IM 黑名单。

        参数说明:
            request: Django admin 传入的请求对象。

        返回参数:
            恒为 ``False``。

        使用示例:
            ``BlockAdmin(Block, admin.site).has_add_permission(request)``

        备注信息:
            后台新增只写本地 ``Block`` 表,不会同步 IM 黑名单、也不会撤销聊天权限,
            等于留下半截状态;新增入口只保留 ``POST /api/v1/blocks``。
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
            ``BlockAdmin(Block, admin.site).has_change_permission(request)``

        备注信息:
            只读的原因:改发起方/被拉黑方等于绕过接口凭空造关系,IM 侧完全不知情;
            要解绑请走 ``DELETE /api/v1/blocks/{user_id}``。
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
            ``BlockAdmin(Block, admin.site).has_delete_permission(request)``

        备注信息:
            后台删除只删本地行,IM 黑名单里仍留着,对方照样发不出消息
            (表现成「解除了拉黑却收不到消息」);解除入口只保留接口。
        """
        return False


@admin.register(BanLog)
class BanLogAdmin(admin.ModelAdmin):
    """只读审计页:只增不改。

    参数说明:
        model: 被注册的模型,固定为 ``BanLog``。
        admin_site: admin 站点实例(默认为 ``django.contrib.admin.site``)。

    返回参数:
        后台配置对象;增删改三处权限全部返回 ``False``,页面只能查看与按动作筛选。

    使用示例:
        ``@admin.register(BanLog)`` 装饰后由 ``ModerationConfig`` 自动加载。

    备注信息:
        审计流水由 ``moderation.services._write_log`` 在状态跨封禁边界时写入
        (含 ``unban`` 与多次重封禁);当前生效的封禁原因看 ``Profile.ban_reason``,
        两者职责不同,不要用本页记录的最后一行动作去推断当前状态。
    """

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
            ``BanLogAdmin(BanLog, admin.site).has_add_permission(request)``

        备注信息:
            审计只能由 ``moderation.services._write_log`` 在状态跨封禁边界时写入;
            手工补录会让「动作流水」与 ``Profile.status`` 对不上。
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
            ``BanLogAdmin(BanLog, admin.site).has_change_permission(request)``

        备注信息:
            审计的价值就在「原样留存」;需要更正请新增一条动作记录,不要改历史行。
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
            ``BanLogAdmin(BanLog, admin.site).has_delete_permission(request)``

        备注信息:
            账号注销时审计随 ``user`` 外键 CASCADE 一起清理,这是唯一会减少行数的路径。
        """
        return False
