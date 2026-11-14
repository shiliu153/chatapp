"""媒体磁盘用量报表:各目录占用、数据库口径合计、告警线。

与 ``im_media_stats`` 的分工:后者只看聊天图且带 Top 发送者;本命令覆盖
``photos/`` ``posts/`` ``chat/`` 三个目录,并按 ``MEDIA_DISK_WARN_MB`` 报警,
适合放 cron:

    python manage.py media_disk_report --fail-over

``--fail-over`` 在超过告警线时以退出码 1 结束,便于 cron/监控直接判定失败。

文件信息:
    文件名称          users/management/commands/media_disk_report.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Sum

from feed.models import PostImage
from im.models import ChatImage, ChatImageStatus, ChatVoice, ChatVoiceStatus
from users.models import Photo

MEDIA_DIRS = ("photos", "posts", "chat")
MEGABYTE = 1024 * 1024


class Command(BaseCommand):
    """打印媒体目录占用与告警状态(只读)。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py media_disk_report --fail-over``

    备注信息:
        ``help`` 的语义是「输出 photos/posts/chat 三个目录的占用、按配额口径的库内合计与告警线判定」。
        命令只读:既不写库也不删文件。
    """

    help = "媒体磁盘报表:photos/posts/chat 目录占用、配额口径合计、告警线"

    def add_arguments(self, parser):
        """注册命令行参数。

        参数说明:
            parser: argparse 解析器,由 Django 在调用 ``handle()`` 前传入。

        返回参数:
            无返回值。

        使用示例:
            ``self.add_arguments(parser)``

        备注信息:
            定义 ``--warn-mb``(告警线,默认取 ``settings.MEDIA_DISK_WARN_MB``)与
            ``--fail-over``(超线时以退出码 1 结束,供 cron 报警)。
        """
        parser.add_argument("--warn-mb", type=int, default=None,
                            help="告警线(MB);默认取 MEDIA_DISK_WARN_MB")
        parser.add_argument("--fail-over", action="store_true",
                            help="超过告警线时以退出码 1 结束(cron 报警用)")

    def handle(self, *args, **options):
        """收集目录与数据库用量并打印。

        参数说明:
            *args: 位置参数(未使用)。
            **options: 命令行选项,含 ``warn_mb`` 与 ``fail_over``。

        返回参数:
            无返回值;超过告警线且传了 ``--fail-over`` 时以退出码 1 结束进程。

        使用示例:
            ``python manage.py media_disk_report --warn-mb 10240``

        备注信息:
            库内合计只算可见状态的聊天图与语音(``ChatImageStatus.VISIBLE`` /
            ``ChatVoiceStatus.VISIBLE``);告警线为 0 表示不限;
            ``settings.MEDIA_ROOT`` 不存在时跳过分区用量一行。
        """
        root = Path(settings.MEDIA_ROOT)
        total_disk = 0
        for directory in MEDIA_DIRS:
            count, size = self._directory_usage(root / directory)
            total_disk += size
            self.stdout.write(
                f"{directory}/: 文件={count} 占用={size // MEGABYTE}MB")

        self.stdout.write(
            f"库内:资料图={self._sum(Photo) // MEGABYTE}MB "
            f"动态图={self._sum(PostImage) // MEGABYTE}MB "
            f"聊天图={self._sum(ChatImage, status=ChatImageStatus.VISIBLE) // MEGABYTE}MB "
            f"语音={self._sum(ChatVoice, status=ChatVoiceStatus.VISIBLE) // MEGABYTE}MB")

        if root.exists():
            usage = shutil.disk_usage(root)
            self.stdout.write(
                f"分区:总={usage.total // MEGABYTE}MB 已用={usage.used // MEGABYTE}MB "
                f"剩余={usage.free // MEGABYTE}MB")
        self.stdout.write(f"媒体目录合计={total_disk // MEGABYTE}MB")

        warn_mb = options["warn_mb"]
        if warn_mb is None:
            warn_mb = int(getattr(settings, "MEDIA_DISK_WARN_MB", 0) or 0)
        over = warn_mb > 0 and total_disk > warn_mb * MEGABYTE
        self.stdout.write(f"告警线={warn_mb}MB 状态={'OVER' if over else 'OK'}")
        if over:
            self.stderr.write(self.style.WARNING(
                f"媒体目录已超过告警线:{total_disk // MEGABYTE}MB > {warn_mb}MB"))
            if options["fail_over"]:
                raise SystemExit(1)

    def _directory_usage(self, path):
        """统计一个目录下的文件数与总字节。

        参数说明:
            path: 目录路径,允许不存在。

        返回参数:
            ``(文件数, 总字节数)`` 二元组;目录不存在时为 ``(0, 0)``。

        使用示例:
            ``self._directory_usage(root / "photos")``

        备注信息:
            递归扫描子目录;``stat()`` 抛 ``OSError`` 的文件仍计入文件数但不计字节。
        """
        if not path.exists():
            return 0, 0
        count = 0
        size = 0
        for item in path.rglob("*"):
            if not item.is_file():
                continue
            count += 1
            try:
                size += item.stat().st_size
            except OSError:
                continue
        return count, size

    def _sum(self, model, **filters):
        """按过滤条件汇总某个模型的 ``bytes``。

        参数说明:
            model: 带 ``bytes`` 字段的模型,如 ``Photo``、``ChatVoice``。
            **filters: 额外的过滤条件,如 ``status=ChatImageStatus.VISIBLE``。

        返回参数:
            总字节数;没有匹配行时为 0。

        使用示例:
            ``self._sum(ChatImage, status=ChatImageStatus.VISIBLE)``

        备注信息:
            聚合结果为 ``None`` 时统一折算成 0,避免调用方再判空。
        """
        return model.objects.filter(**filters).aggregate(
            value=Sum("bytes"))["value"] or 0
