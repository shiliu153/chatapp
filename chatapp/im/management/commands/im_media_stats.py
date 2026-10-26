"""聊天图片用量报表:各状态条数/字节、磁盘占用与剩余空间、Top 发送者。

只读命令,用来判断要不要调 ``CHAT_IMAGE_RETENTION_DAYS``、以及磁盘是否吃紧。
"""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count, Sum

from im.models import ChatImage

CHAT_DIR = "chat"


class Command(BaseCommand):
    """打印聊天图片的数据库与磁盘用量(只读)。"""

    help = "聊天图片用量报表:各状态条数/字节、磁盘占用与剩余空间、Top 5 发送者"

    def handle(self, *args, **options):
        """收集并打印用量信息。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项(未使用)。

        Returns:
            None。
        """
        root = Path(settings.MEDIA_ROOT) / CHAT_DIR
        files = [path for path in root.rglob("*") if path.is_file()] if root.exists() else []
        disk_bytes = sum(path.stat().st_size for path in files)

        for row in ChatImage.objects.values("status").annotate(
                count=Count("id"), total=Sum("bytes")).order_by("status"):
            self.stdout.write(f"{row['status']}={row['count']} 字节={row['total'] or 0}")

        usage = shutil.disk_usage(settings.MEDIA_ROOT)
        self.stdout.write(f"磁盘文件={len(files)} 磁盘字节={disk_bytes}")
        self.stdout.write(
            f"分区:总={usage.total // (1024 * 1024)}MB "
            f"已用={usage.used // (1024 * 1024)}MB "
            f"剩余={usage.free // (1024 * 1024)}MB")

        top = ChatImage.objects.values("owner_id").annotate(
            count=Count("id"), total=Sum("bytes")).order_by("-total")[:5]
        for row in top:
            self.stdout.write(
                f"top owner={row['owner_id']} 张数={row['count']} 字节={row['total'] or 0}")
