"""删除超过保留期的资料页访问记录(默认 dry-run,``--apply`` 才真删)。

访客记录属于个人信息,按「最小必要」原则保留 90 天(见
``users.services.PROFILE_VISIT_RETENTION_DAYS``)。建议挂每天低峰的计划任务。

文件信息:
    文件名称          users/management/commands/purge_profile_visits.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import ProfileVisit
from users.services import PROFILE_VISIT_RETENTION_DAYS


class Command(BaseCommand):
    """清理过期访客记录(默认 dry-run)。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py purge_profile_visits --apply``

    备注信息:
        ``help`` 的语义是「删除超过保留期的资料页访问记录,默认只打印,--apply 才真正删除」。
        保留期取自 ``users.services.PROFILE_VISIT_RETENTION_DAYS``,可用 ``--days`` 临时覆盖。
    """

    help = "删除超过保留期的资料页访问记录(默认 dry-run,--apply 才删)"

    def add_arguments(self, parser):
        """注册命令行参数。

        参数说明:
            parser: argparse 解析器,由 Django 在调用 ``handle()`` 前传入。

        返回参数:
            无返回值。

        使用示例:
            ``self.add_arguments(parser)``

        备注信息:
            定义 ``--apply``(默认只打印)与 ``--days``(保留天数,默认读常量)。
        """
        parser.add_argument("--apply", action="store_true", help="真正删除;默认只打印")
        parser.add_argument("--days", type=int, default=PROFILE_VISIT_RETENTION_DAYS,
                            help=f"保留天数,默认 {PROFILE_VISIT_RETENTION_DAYS}")

    def handle(self, *args, **options):
        """按保留期删除(或列出)过期记录。

        参数说明:
            *args: 位置参数(未使用)。
            **options: 命令行选项,含 ``apply`` 与 ``days``。

        返回参数:
            无返回值。

        使用示例:
            ``python manage.py purge_profile_visits --days 180 --apply``

        备注信息:
            「过期」的判定是 ``ProfileVisit.last_at`` 早于 ``now() - days``;
            不加 ``--apply`` 时只打印将删除的条数与最早一条的时间,不删任何行。
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
