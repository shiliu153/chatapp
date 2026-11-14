"""清理过期站内通知的管理命令(默认 dry-run)。

设计要点:
    1. **默认不删**:不带 ``--apply`` 只统计,避免手滑清空历史;
    2. 查询侧本来就只返回 90 天内的通知(``notifications.views``),本命令只负责
       物理回收;不接 cron —— 个人项目量级,查询侧截断已经够用,接计划任务要动
       服务器 crontab,收益不成比例(取舍见计划 §2.3);
    3. 删除是硬删:通知不是账务数据,留痕价值随过期归零。

文件信息:
    文件名称          notifications/management/commands/notifications_prune.py
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

from notifications.models import InAppNotification

DEFAULT_DAYS = 90


class Command(BaseCommand):
    """删除超过保留期的站内通知。

    参数说明:
        无构造参数;命令行参数在 :meth:`add_arguments` 里注册(``--apply`` / ``--days``)。

    返回参数:
        无返回值;结果通过 ``stdout`` 打印(将删条数或已删条数)。

    使用示例:
        ``python manage.py notifications_prune --days 90 --apply``

    备注信息:
        ``help`` 的语义是「删除过期站内通知,默认 dry-run,加 --apply 才真删」——
        命令的默认行为必须是无损的,所以 ``--apply`` 存在才执行 ``delete()``;
        保留天数由 ``--days`` 给出,默认 ``DEFAULT_DAYS=90``,与
        ``notifications.views.NOTIFICATION_WINDOW_DAYS`` 是同一个口径。
    """

    help = "删除过期站内通知(默认 dry-run;加 --apply 才真删)"

    def add_arguments(self, parser):
        """注册命令行参数。

        参数说明:
            parser: argparse 的解析器。

        返回参数:
            无返回值。

        使用示例:
            ``self.add_arguments(parser)``

        备注信息:
            ``--apply`` 是 ``store_true``(默认假);``--days`` 默认取 ``DEFAULT_DAYS``,
            负数不做校验,传入后会因截止时间在未来而删掉全部通知。
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

        返回参数:
            无返回值;``stdout`` 打印 dry-run 或删除结果。

        使用示例:
            ``python manage.py notifications_prune --days 90 --apply``

        备注信息:
            删除条件是 ``created_at < now() - days``(不含边界);``delete()`` 返回的
            总数含级联子行,本命令的报告直接用这个数;不加 ``--apply`` 时只 ``count()``
            后打印,不写库。
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
