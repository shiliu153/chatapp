"""聊天图片用量报表:各状态条数/字节、磁盘占用与剩余空间、Top 发送者。

只读命令,用来判断要不要调 ``CHAT_IMAGE_RETENTION_DAYS``、以及磁盘是否吃紧。

文件信息:
    文件名称          im/management/commands/im_media_stats.py
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
from django.db.models import Count, Sum

from im.models import ChatImage

CHAT_DIR = "chat"


class Command(BaseCommand):
    """打印聊天图片的数据库与磁盘用量(只读)。

    参数说明:
        无构造参数;由 ``manage.py`` 在调用命令时实例化。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py im_media_stats``

    备注信息:
        ``help`` 的语义是「聊天图片用量报表:各状态条数/字节、磁盘占用与剩余空间、
        Top 5 发送者」;全程只读,不写库、不删文件。
    """

    help = "聊天图片用量报表:各状态条数/字节、磁盘占用与剩余空间、Top 5 发送者"

    def handle(self, *args, **options):
        """收集并打印用量信息。

        参数说明:
            *args: 位置参数(未使用)。
            **options: 命令行选项(本命令未定义,保持签名兼容)。

        返回参数:
            无返回值;三组统计写到 ``stdout``。

        使用示例:
            ``python manage.py im_media_stats``

        备注信息:
            依次输出按 ``status`` 分组的条数与字节和、``MEDIA_ROOT/chat`` 下的文件数与
            实际占用、所在分区的总量/已用/剩余(MB),最后是字节数最多的 5 个发送者。
            ``Sum("bytes")`` 在无行时为 ``None``,输出一律按 0 兜底;
            ``MEDIA_ROOT/chat`` 不存在时按 0 个文件统计。
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
