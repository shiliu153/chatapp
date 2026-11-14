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

文件信息:
    文件名称          stats/models.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.db import models


class DailyMetric(models.Model):
    """一天的运营数字快照(一天一行,由 ``manage.py metrics_daily`` 写入)。

    参数说明:
        date: ``Asia/Shanghai`` 自然日,``unique=True``,幂等 upsert 的冲突键。
        dau: 日活人数,取自 ``users.activity`` 当天的活跃集合;集合不存在时为 ``NULL``。
        new_users: 当天注册人数(``date_joined`` 落在当天区间内)。
        profiles_completed: 当天新注册者中**当前**资料状态为 ``complete`` 的人数。
        swipes_like: 当天 ``SwipeAction.LIKE`` 的滑卡数。
        swipes_pass: 当天 ``SwipeAction.PASS`` 的滑卡数。
        matches: 当天新建的配对数(按 ``Match.created_at``,含事后被解除的)。
        messages: 当天 IM 消息条数,读 ``chatapp_im`` 库;读不到时为 ``NULL``。
        active_hours: 长度 24 的整数数组,每个元素是该小时的去重活跃人数;无数据时 ``NULL``。
        retention_d1: 次日留存人数(当天注册 cohort ∩ 次日活跃),目标日无数据时 ``NULL``。
        retention_d7: 7 日留存人数(同一口径,目标日为第 7 天)。
        created_at: 本行首次写入时间,自动写入。
        updated_at: 本行最近一次覆盖写入时间,自动维护。

    返回参数:
        构造出的 ``DailyMetric`` 实例。

    使用示例:
        ``DailyMetric.objects.update_or_create(date=day, defaults=snapshot)``

    备注信息:
        写入入口只有 ``stats.metrics.save_snapshot``(``update_or_create``,同一天重跑
        覆盖而不新增)与 ``stats.metrics.fill_retention``(只 ``update`` 已存在的行);
        ``Meta`` 是声明式内部类,按 ``config/comment_coverage.py`` 的规则豁免 docstring。
    """

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

        参数说明:
            无。

        返回参数:
            ``日期 + 日活``。

        使用示例:
            ``str(row)``

        备注信息:
            日活为 ``None`` 时渲染成 ``-``,与命令输出、看板的缺失值口径一致;只用于
            后台与排障日志,不进任何对外响应。
        """
        return f"{self.date} dau={self.dau if self.dau is not None else '-'}"
