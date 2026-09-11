from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ReportType(models.TextChoices):
    HARASSMENT = "harassment", "骚扰"
    PORN = "porn", "色情"
    FRAUD = "fraud", "诈骗"
    OTHER = "other", "其他"


class ReportStatus(models.TextChoices):
    PENDING = "pending", "待处理"
    HANDLED = "handled", "已处理"


class Report(models.Model):
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

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"report#{self.pk}({self.reporter_id}->{self.target_id}:{self.type})"


class Block(models.Model):
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
        return f"block({self.blocker_id}->{self.blocked_id})"


class BanAction(models.TextChoices):
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
        return f"ban#{self.pk}({self.user_id}:{self.action})"
