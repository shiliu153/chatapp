"""删除超过保留期的资料页访问记录(默认 dry-run,``--apply`` 才真删)。

访客记录属于个人信息,按「最小必要」原则保留 90 天(见
``users.services.PROFILE_VISIT_RETENTION_DAYS``)。建议挂每天低峰的计划任务。
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import ProfileVisit
from users.services import PROFILE_VISIT_RETENTION_DAYS


class Command(BaseCommand):
    """清理过期访客记录(默认 dry-run)。"""

    help = "删除超过保留期的资料页访问记录(默认 dry-run,--apply 才删)"

    def add_arguments(self, parser):
        """注册命令行参数。

        Args:
            parser: argparse 解析器。
        """
        parser.add_argument("--apply", action="store_true", help="真正删除;默认只打印")
        parser.add_argument("--days", type=int, default=PROFILE_VISIT_RETENTION_DAYS,
                            help=f"保留天数,默认 {PROFILE_VISIT_RETENTION_DAYS}")

    def handle(self, *args, **options):
        """按保留期删除(或列出)过期记录。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Returns:
            None。
        """
        days = int(options["days"])
        cutoff = timezone.now() - timedelta(days=days)
        expired = ProfileVisit.objects.filter(last_at__lt=cutoff)
        total = expired.count()
        if not options["apply"]:
            oldest = expired.order_by("last_at").values_list("last_at", flat=True).first()
            self.stdout.write(f"[dry-run] 将删除 {total} 条(早于 {cutoff:%Y-%m-%d %H:%M}),"
                              f"最早一条 {oldest}")
            return
        deleted, _ = expired.delete()
        self.stdout.write(f"已删除 {deleted} 条(早于 {cutoff:%Y-%m-%d %H:%M})")
