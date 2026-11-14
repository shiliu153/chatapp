"""Django admin 中的资料、照片与标签管理。

设计要点:
    照片审核动作与 ``ops`` 审核台共用 ``users.services.review_photos``,
    保证两条路径的审计记录与资料状态重算完全一致。

文件信息:
    文件名称          users/admin.py
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
from django.utils.html import format_html

from moderation.services import log_ban_change

from .models import Photo, PhotoStatus, Preference, Profile, Tag
from .services import review_photos


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """资料的后台管理,保存时记录封禁变更审计。

    参数说明:
        Django 按 ``ModelAdmin(model, admin_site)`` 构造,``@admin.register`` 会以
        ``Profile`` 与默认 ``AdminSite`` 实例化;本类不额外接收参数。

    返回参数:
        注册到 admin 的 ``ProfileAdmin`` 实例。

    使用示例:
        ``admin.site.register(Profile, ProfileAdmin)``

    备注信息:
        实际的注册由 ``@admin.register(Profile)`` 装饰器完成;列表页字段与筛选器见
        类体内的 ``list_display`` / ``list_filter`` / ``search_fields``。
    """

    list_display = ("user", "nickname", "gender", "city", "status", "ban_reason")
    list_filter = ("status", "gender")
    search_fields = ("nickname", "user__phone")

    def save_model(self, request, obj, form, change):
        """保存资料,并记录封禁状态变更。

        改动前先取旧状态,保存后交给 ``log_ban_change`` 比对 —— 只有真正发生
        封禁/解封时才会写审计记录。

        参数说明:
            request: 当前后台请求。
            obj: 待保存的资料对象。
            form: 后台表单。
            change: ``True`` 表示修改已有对象,``False`` 表示新建。

        返回参数:
            无返回值。

        使用示例:
            ``admin.site._registry[Profile].save_model(request, profile, form, True)``

        备注信息:
            新建时 ``old_status`` 为 ``None``,``log_ban_change`` 据此区分首次设置;
            审核台(ops)走的是另一条路径,两条路径最终都调 ``log_ban_change``。
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

    参数说明:
        modeladmin: 当前 ModelAdmin 实例。
        request: 当前后台请求。
        queryset: 选中的照片查询集。

    返回参数:
        无返回值。

    使用示例:
        ``approve_photos(modeladmin, request, Photo.objects.filter(status="pending"))``

    备注信息:
        实际动作交给 ``_review_photos``:过审会重算资料完善状态,并把头像同步到 IM
        (入队在 ``review_photos`` 内完成)。
    """
    _review_photos(modeladmin, request, queryset, PhotoStatus.APPROVED)


@admin.action(description="驳回所选照片")
def reject_photos(modeladmin, request, queryset):
    """批量驳回所选照片。

    参数说明:
        modeladmin: 当前 ModelAdmin 实例。
        request: 当前后台请求。
        queryset: 选中的照片查询集。

    返回参数:
        无返回值。

    使用示例:
        ``reject_photos(modeladmin, request, Photo.objects.filter(status="pending"))``

    备注信息:
        驳回同样会重算资料完善状态(照片不足会掉回「未完善」),但不做 IM 头像同步。
    """
    _review_photos(modeladmin, request, queryset, PhotoStatus.REJECTED)


def _review_photos(modeladmin, request, queryset, status):
    """两个审核动作的公共实现:调用服务层并回显处理条数。

    参数说明:
        modeladmin: 当前 ModelAdmin 实例,用于回显消息。
        request: 当前后台请求。
        queryset: 选中的照片查询集。
        status: 目标审核状态。

    返回参数:
        无返回值。

    使用示例:
        ``_review_photos(modeladmin, request, queryset, PhotoStatus.APPROVED)``

    备注信息:
        运营账号取自 ``request.user``,作为 ``reviewed_by`` 落库用于审计;
        两个动作共用这里,保证后台与 ops 审核台的行为一致。
    """
    count = review_photos(queryset, status, request.user)
    modeladmin.message_user(request, f"已处理 {count} 张照片")


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    """照片的后台管理:带缩略图预览与批量审核动作。

    参数说明:
        Django 按 ``ModelAdmin(model, admin_site)`` 构造,``@admin.register`` 会以
        ``Photo`` 与默认 ``AdminSite`` 实例化;本类不额外接收参数。

    返回参数:
        注册到 admin 的 ``PhotoAdmin`` 实例。

    使用示例:
        ``admin.site.register(Photo, PhotoAdmin)``

    备注信息:
        批量审核动作是 ``approve_photos`` 与 ``reject_photos``,两者都走
        ``users.services.review_photos``;缩略图由 ``preview`` 列渲染。
    """

    list_display = ("id", "preview", "user", "status", "order", "created_at")
    list_filter = ("status",)
    actions = [approve_photos, reject_photos]

    @admin.display(description="预览")
    def preview(self, obj):
        """在列表页渲染照片缩略图。

        参数说明:
            obj: 当前照片对象。

        返回参数:
            限高 60px 的 ``<img>`` 标签;没有文件时返回 ``-``。

        使用示例:
            ``photo_admin.preview(photo)``

        备注信息:
            用 ``format_html`` 拼标签(会转义 ``url``);这里直接用 ``obj.file.url``,
            不签名也不过期,与公开资料卡同口径。
        """
        if not obj.file:
            return "-"
        return format_html('<img src="{}" style="height:60px;border-radius:4px">', obj.file.url)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """标签池的后台管理。

    参数说明:
        Django 按 ``ModelAdmin(model, admin_site)`` 构造,``@admin.register`` 会以
        ``Tag`` 与默认 ``AdminSite`` 实例化;本类不额外接收参数。

    返回参数:
        注册到 admin 的 ``TagAdmin`` 实例。

    使用示例:
        ``admin.site.register(Tag, TagAdmin)``

    备注信息:
        只读用途为主:标签池由数据迁移写入,后台改名称会让迁移记录与实际数据不一致。
    """

    list_display = ("id", "name", "icon")


@admin.register(Preference)
class PreferenceAdmin(admin.ModelAdmin):
    """择偶偏好的后台管理。

    参数说明:
        Django 按 ``ModelAdmin(model, admin_site)`` 构造,``@admin.register`` 会以
        ``Preference`` 与默认 ``AdminSite`` 实例化;本类不额外接收参数。

    返回参数:
        注册到 admin 的 ``PreferenceAdmin`` 实例。

    使用示例:
        ``admin.site.register(Preference, PreferenceAdmin)``

    备注信息:
        只列关键字段便于排查;偏好校验(最小 18 岁、上下界关系)在
        ``users.serializers.PreferenceSerializer``,后台改动不走那次校验。
    """

    list_display = ("profile", "target_gender", "age_min", "age_max", "city")
