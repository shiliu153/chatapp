"""合规相关的数据模型:举报、拉黑与封禁审计。

设计要点:
    1. ``Block`` 有 ``blocker != blocked`` 的检查约束(不能拉黑自己)与
       ``(blocker, blocked)`` 唯一约束(重复拉黑幂等);
    2. ``BanLog`` **只增不改**,是封禁动作的审计流水;当前生效的封禁原因存在
       ``Profile.ban_reason`` 上,两者职责不同,别互相替代。
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
    """

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="reports_made")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="reports_received")
    type = models.CharField("类型", max_length=20, choices=ReportType.choices)
    detail = models.CharField("补充说明", max_length=200, blank=True)
    status = models.CharField("状态", max_length=10, choices=ReportStatus.choices,
                              default=ReportStatus.PENDING)
    handled_note = models.CharField("处理备注", max_length=200, blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="reports_handled")
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)
    dedupe_key = models.CharField("去重键", max_length=64, null=True, blank=True,
                                  unique=True, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        """保存前维护去重键。

        待处理举报写入 ``举报人:被举报人:pending``;一旦离开待处理状态就清空,
        这样用户处理完可以再次举报同一人,而并发提交仍被唯一约束挡住。

        Args:
            *args: 透传给 ``Model.save``。
            **kwargs: 透传给 ``Model.save``;``update_fields`` 会补上 ``dedupe_key``,
                否则只改 ``status`` 时去重键清不掉。
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

        Returns:
            ``report#主键(举报人->被举报人:类型)``。
        """
        return f"report#{self.pk}({self.reporter_id}->{self.target_id}:{self.type})"


class Block(models.Model):
    """一条拉黑关系(单向)。"""

    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="blocks_made")
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="blocks_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="uniq_block_pair"),
            models.CheckConstraint(condition=~Q(blocker=F("blocked")), name="block_not_self"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``block(发起方->被拉黑方)``。
        """
        return f"block({self.blocker_id}->{self.blocked_id})"


class BanAction(models.TextChoices):
    """封禁审计的动作类型。"""

    BAN_LIGHT = "ban_light", "轻度封禁"
    BAN_HEAVY = "ban_heavy", "重度封禁"
    UNBAN = "unban", "解封"


class BanLog(models.Model):
    """封禁审计,只增不改;当前生效原因在 Profile.ban_reason。"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="ban_logs")
    action = models.CharField("动作", max_length=10, choices=BanAction.choices)
    reason = models.CharField("原因", max_length=200, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="ban_actions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``ban#主键(账号 id:动作)``。
        """
        return f"ban#{self.pk}({self.user_id}:{self.action})"
