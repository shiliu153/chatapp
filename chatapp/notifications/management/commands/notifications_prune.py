"""清理过期站内通知的管理命令(默认 dry-run)。

设计要点:
    1. **默认不删**:不带 ``--apply`` 只统计,避免手滑清空历史;
    2. 查询侧本来就只返回 90 天内的通知(``notifications.views``),本命令只负责
       物理回收;不接 cron —— 个人项目量级,查询侧截断已经够用,接计划任务要动
       服务器 crontab,收益不成比例(取舍见计划 §2.3);
    3. 删除是硬删:通知不是账务数据,留痕价值随过期归零。
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.models import InAppNotification

DEFAULT_DAYS = 90


class Command(BaseCommand):
    """删除超过保留期的站内通知。"""

    help = "删除过期站内通知(默认 dry-run;加 --apply 才真删)"

    def add_arguments(self, parser):
        """注册命令行参数(``--apply`` / ``--days``)。

        参数说明:
            parser: argparse 的解析器。

        使用示例:
            ``python manage.py notifications_prune --apply --days 1000``(见 ``notifications/test_in_app.py`` 的 ``NotificationsPruneCommandTests``)

        备注信息:
            两个参数都可选:``--apply`` 不传即 dry-run,``--days`` 默认 ``DEFAULT_DAYS``(90)。
        """
        parser.add_argument("--apply", action="store_true",
                            help="真正删除;不加时只统计将要删除的条数")
        parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                            help=f"保留天数,默认 {DEFAULT_DAYS}")

    def handle(self, *args, **options):
        """执行清理。

        参数说明:
            *args: 透传的位置参数。
            **options: 解析后的命令行选项(``apply`` / ``days``)。

        使用示例:
            ``python manage.py notifications_prune --apply --days 1000``(见 ``notifications/test_in_app.py`` 的 ``NotificationsPruneCommandTests.test_custom_retention_days``)

        备注信息:
            默认只统计将删除的条数并打印 dry-run 提示,加 ``--apply`` 才真删;删除是硬删,
            不接 cron(取舍见模块 docstring)。
        """
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)
        queryset = InAppNotification.objects.filter(created_at__lt=cutoff)
        total = queryset.count()
        if not options["apply"]:
            self.stdout.write(
                f"dry-run:将删除 {total} 条 {days} 天前的通知(加 --apply 才会真删)")
            return
        deleted, _ = queryset.delete()
        self.stdout.write(self.style.SUCCESS(
            f"已删除 {deleted} 条 {days} 天前的通知"))
