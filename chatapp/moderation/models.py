"""合规相关的数据模型:举报、拉黑与封禁审计。

设计要点:
    1. ``Block`` 有 ``blocker != blocked`` 的检查约束(不能拉黑自己)与
       ``(blocker, blocked)`` 唯一约束(重复拉黑幂等);
    2. ``BanLog`` **只增不改**,是封禁动作的审计流水;当前生效的封禁原因存在
       ``Profile.ban_reason`` 上,两者职责不同,别互相替代。

文件信息:
    文件名称          moderation/models.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ReportType(models.TextChoices):
    """举报类型。"""

    HARASSMENT = "harassment", "骚扰"
    PORN = "porn", "色情"
    FRAUD = "fraud", "诈骗"
    OTHER = "other", "其他"


class ReportStatus(models.TextChoices):
    """举报处理状态。"""

    PENDING = "pending", "待处理"
    HANDLED = "handled", "已处理"


class Report(models.Model):
    """一条用户举报。

    Attributes:
        handled_by: 处理人(运营账号);未处理时为 ``None``。
        handled_at: 首次标记已处理的时间,用于判定「首次处理」以免重复通知。
        dedupe_key: 待处理举报的去重键(``举报人:被举报人:pending``),唯一约束
            保证并发提交也只落一条;处理完成后置空,允许再次举报。

    参数说明:
        无(字段初始值按字段名传给构造器,如 ``Report(reporter=user, target=other)``)。

    返回参数:
        实例化得到 ``Report`` 实例;``id`` / ``created_at`` 在 ``save()`` 之后才有值,
        ``status`` 默认 ``pending``。

    使用示例:
        ``Report.objects.create(reporter=me, target=other, type=ReportType.HARASSMENT)``

    备注信息:
        状态流转只有 ``pending → handled`` 一次(由 ``ReportAdmin.save_model`` 推进),
        没有驳回态;字段含义见下方每条字段的行内注释,去重键的维护在 ``save`` 里。
    """

    # 举报人;账号注销时其发出的举报随 CASCADE 删除
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="reports_made")
    # 被举报人;账号注销时收到的举报随 CASCADE 删除
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="reports_received")
    # 举报类型,取值见 ReportType
    type = models.CharField("类型", max_length=20, choices=ReportType.choices)
    # 举报人补充说明,可空;200 字上限
    detail = models.CharField("补充说明", max_length=200, blank=True)
    # 处理状态,默认待处理;只有 pending → handled 一个方向
    status = models.CharField("状态", max_length=10, choices=ReportStatus.choices,
                              default=ReportStatus.PENDING)
    # 运营的处理备注,可空
    handled_note = models.CharField("处理备注", max_length=200, blank=True)
    # 处理人(运营账号);未处理为 None,账号注销时置 NULL 而不是删举报
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="reports_handled")
    # 举报提交时间,后台按它倒序排
    created_at = models.DateTimeField(auto_now_add=True)
    # 首次标记已处理的时间;判「首次处理」靠它,重复保存不会再次通知
    handled_at = models.DateTimeField(null=True, blank=True)
    # 待处理举报的去重键,由 save 维护;离开待处理状态即置空
    dedupe_key = models.CharField("去重键", max_length=64, null=True, blank=True,
                                  unique=True, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        """保存前维护去重键。

        待处理举报写入 ``举报人:被举报人:pending``;一旦离开待处理状态就清空,
        这样用户处理完可以再次举报同一人,而并发提交仍被唯一约束挡住。

        参数说明:
            *args: 透传给 ``Model.save``。
            **kwargs: 透传给 ``Model.save``;``update_fields`` 会补上 ``dedupe_key``,
                否则只改 ``status`` 时去重键清不掉。

        返回参数:
            无返回值。

        使用示例:
            ``report.save(update_fields=["status"])``

        备注信息:
            唯一约束只在 ``dedupe_key`` 非空时生效,``None`` 可以重复出现,所以
            已处理的举报不会互相冲突;并发落库时由数据库唯一约束挡住第二条,
            调用方(``views.create_report``)用 ``get_or_create`` 回查已有记录。
        """
        if self.status == ReportStatus.PENDING:
            if not self.dedupe_key:
                self.dedupe_key = f"{self.reporter_id}:{self.target_id}:pending"
        else:
            self.dedupe_key = None
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"dedupe_key"}
        super().save(*args, **kwargs)

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``report#主键(举报人->被举报人:类型)``。

        使用示例:
            ``str(report)``

        备注信息:
            箭头两侧是**账号**主键 ``reporter_id`` / ``target_id``,不是资料主键;
            只读已加载的列,不触发额外查询。
        """
        return f"report#{self.pk}({self.reporter_id}->{self.target_id}:{self.type})"


class Block(models.Model):
    """一条拉黑关系(单向)。

    参数说明:
        无(字段初始值按字段名传给构造器,如 ``Block(blocker=me, blocked=other)``)。

    返回参数:
        实例化得到 ``Block`` 实例;``created_at`` 在 ``save()`` 之后才有值。

    使用示例:
        ``Block.objects.get_or_create(blocker=request.user, blocked=target)``

    备注信息:
        关系是**单向**的(只有发起方视角),但可见性一律按双向并集计算
        (见 ``services.blocked_user_ids`` / ``exclude_blocked``)。
        ``(blocker, blocked)`` 唯一约束让重复拉黑幂等,``block_not_self`` 检查约束
        从库层挡住「拉黑自己」;写本地表的同时必须入队同步 IM 黑名单,否则对方仍能发消息。
    """

    # 拉黑发起方;账号注销时该关系随 CASCADE 删除
    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="blocks_made")
    # 被拉黑方;账号注销时该关系随 CASCADE 删除
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="blocks_received")
    # 拉黑时间,黑名单列表按它倒序
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="uniq_block_pair"),
            models.CheckConstraint(condition=~Q(blocker=F("blocked")), name="block_not_self"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``block(发起方->被拉黑方)``。

        使用示例:
            ``str(block)``

        备注信息:
            括号里是两个**账号**主键,方向即 ``blocker → blocked``,不表示互拉黑。
        """
        return f"block({self.blocker_id}->{self.blocked_id})"


class BanAction(models.TextChoices):
    """封禁审计的动作类型。"""

    BAN_LIGHT = "ban_light", "轻度封禁"
    BAN_HEAVY = "ban_heavy", "重度封禁"
    UNBAN = "unban", "解封"


class BanLog(models.Model):
    """封禁审计,只增不改;当前生效原因在 Profile.ban_reason。

    参数说明:
        无(字段初始值按字段名传给构造器,如 ``BanLog(user=target, action=...)``)。

    返回参数:
        实例化得到 ``BanLog`` 实例;``created_at`` 在 ``save()`` 之后才有值。

    使用示例:
        ``BanLog.objects.create(user=target, action=BanAction.BAN_HEAVY, reason="骚扰他人")``

    备注信息:
        写入入口只有 ``services._write_log``(经 ``log_ban_change`` 调用),
        admin 页面三处权限都返回 ``False``,审计不可手改、不可删除。
        它记的是**动作流水**(含 ``unban`` 与多次重封禁),不等于当前状态。
    """

    # 被封禁/解封的账号;账号注销时其审计随 CASCADE 删除
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="ban_logs")
    # 动作类型,取值见 BanAction(轻度/重度/解封)
    action = models.CharField("动作", max_length=10, choices=BanAction.choices)
    # 原因文本,可空;解封时填的通常是申诉结论
    reason = models.CharField("原因", max_length=200, blank=True)
    # 操作人(运营账号);为 None 表示系统或脚本触发
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="ban_actions")
    # 动作发生时间,审计列表按它倒序
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``ban#主键(账号 id:动作)``。

        使用示例:
            ``str(ban_log)``

        备注信息:
            括号里是**账号**主键 ``user_id`` 与动作枚举值(如 ``ban_heavy``),不含原因。
        """
        return f"ban#{self.pk}({self.user_id}:{self.action})"
