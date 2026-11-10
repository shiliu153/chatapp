"""运营指标的持久化模型:一天一行的快照表。

``stats`` 直到本批之前只有只读聚合(个人使用报告);这里给它加**第一张表**
``DailyMetric``,由 ``manage.py metrics_daily`` 每天写入一行,供 ``/ops/metrics/``
看板读历史趋势。

设计要点:
    1. ``dau`` / ``messages`` / ``active_hours`` / 留存四个字段**允许 NULL**:它们有
       「当天没采到」与「采到了但是 0」两种状态,看板必须能区分(显示 ``—`` 而不是
       ``0``);其余计数在库里一定有源,缺省 0;
    2. ``date`` 唯一 —— 命令用 ``update_or_create`` 幂等 upsert,同一天跑几次都只有一行。

注意事项:
    ``date`` 是 ``Asia/Shanghai`` 自然日,不是 UTC 日;切日一律走
    ``stats.metrics.day_range``。
"""

from django.db import models


class DailyMetric(models.Model):
    """一天的运营数字快照(一天一行,由 ``manage.py metrics_daily`` 写入)。"""

    date = models.DateField("日期", unique=True)          # Asia/Shanghai 自然日
    dau = models.PositiveIntegerField("日活", null=True)   # 无 Redis 记录时 None(不是 0)
    new_users = models.PositiveIntegerField("新注册", default=0)
    profiles_completed = models.PositiveIntegerField("新注册中资料已完善", default=0)
    swipes_like = models.PositiveIntegerField("喜欢", default=0)
    swipes_pass = models.PositiveIntegerField("跳过", default=0)
    matches = models.PositiveIntegerField("新增配对", default=0)
    messages = models.PositiveIntegerField("消息条数", null=True)   # 读不到 IM 库时 None
    active_hours = models.JSONField("活跃时段分布", null=True)      # 24 个整数;无数据 None
    retention_d1 = models.PositiveIntegerField("次日留存", null=True)
    retention_d7 = models.PositiveIntegerField("7 日留存", null=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        """按日期倒序,看板与后台都按最新在前展示。"""

        ordering = ["-date"]
        verbose_name = "每日指标"
        verbose_name_plural = "每日指标"

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``日期 + 日活``。
        """
        return f"{self.date} dau={self.dau if self.dau is not None else '-'}"
