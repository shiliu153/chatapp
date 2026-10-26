"""清理聊天图片:保留期、孤儿文件、删除残留。

默认 dry-run(只打印将要删除的内容),``--apply`` 才真正删文件 —— 删文件不可逆,
定时任务必须显式带 ``--apply``。

三类动作互相独立:
    1. 保留期:可见且早于保留期的图片 → 删原图/缩略图,行改 ``expired``;
    2. 孤儿文件:磁盘上有、库里没有对应行、且 mtime 早于宽限期的文件;
    3. 删除残留:行已 ``deleted`` 但文件还在(上次存储删除失败)→ 补删。
"""

import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.utils import timezone

from im.models import ChatImage, ChatImageStatus

CHAT_DIR = "chat"


class Command(BaseCommand):
    """清理聊天图片的磁盘占用(默认 dry-run)。"""

    help = "清理聊天图片:保留期过期、孤儿文件、删除残留(默认 dry-run,--apply 才删)"

    def add_arguments(self, parser):
        """注册命令行参数。

        Args:
            parser: argparse 解析器。
        """
        parser.add_argument("--apply", action="store_true", help="真正删除;默认只打印")
        parser.add_argument("--retention-days", type=int, default=None,
                            help="保留期(天);默认取 CHAT_IMAGE_RETENTION_DAYS,0 表示不清理")
        parser.add_argument("--orphan-hours", type=int, default=24,
                            help="孤儿文件的宽限期(小时);0 表示不扫孤儿文件")
        parser.add_argument("--batch-size", type=int, default=200, help="每批处理的行数")

    def handle(self, *args, **options):
        """执行三类清理并打印汇总。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Returns:
            None。
        """
        apply = bool(options["apply"])
        retention_days = options["retention_days"]
        if retention_days is None:
            retention_days = getattr(settings, "CHAT_IMAGE_RETENTION_DAYS", 30)
        batch_size = max(int(options["batch_size"]), 1)

        mode = "apply" if apply else "dry-run"
        self.stdout.write(f"[im_media_cleanup] mode={mode}")

        expired = self._expire_old(retention_days, batch_size, apply)
        removed_files = self._delete_leftovers(batch_size, apply)
        orphans = self._delete_orphans(int(options["orphan_hours"]), apply)
        self.stdout.write(
            f"保留期({retention_days} 天):{expired} 张;"
            f"删除残留:{removed_files} 个文件;孤儿文件:{orphans} 个")
        if not apply:
            self.stdout.write("dry-run:未删除任何文件,确认无误后加 --apply")

    def _expire_old(self, retention_days: int, batch_size: int, apply: bool) -> int:
        """把早于保留期的可见图片删文件并标记过期。

        Args:
            retention_days: 保留天数;``0`` 表示跳过。
            batch_size: 每批处理行数。
            apply: 是否真正删除。

        Returns:
            处理的图片数量。
        """
        if retention_days <= 0:
            return 0
        cutoff = timezone.now() - timedelta(days=retention_days)
        rows = ChatImage.objects.filter(
            status=ChatImageStatus.VISIBLE, created_at__lt=cutoff)
        if not apply:
            return rows.count()

        total = 0
        while True:
            batch = list(rows.order_by("id")[:batch_size])
            if not batch:
                return total
            for image in batch:
                self._delete_files(image)
                image.status = ChatImageStatus.EXPIRED
                image.expired_at = timezone.now()
                image.save(update_fields=["status", "expired_at"])
            total += len(batch)

    def _delete_leftovers(self, batch_size: int, apply: bool) -> int:
        """补删「行已删除但文件还在」的残留文件。

        Args:
            batch_size: 每批处理行数。
            apply: 是否真正删除。

        Returns:
            处理的文件数量。
        """
        total = 0
        for image in ChatImage.objects.filter(
                status=ChatImageStatus.DELETED).iterator(chunk_size=batch_size):
            if self._delete_files(image, apply=apply):
                total += 1
        return total

    def _delete_orphans(self, orphan_hours: int, apply: bool) -> int:
        """删除磁盘上没有数据库行、且超过宽限期的聊天图片文件。

        Args:
            orphan_hours: 宽限期(小时);``0`` 表示跳过。
            apply: 是否真正删除。

        Returns:
            删除(或将要删除)的文件数量。
        """
        if orphan_hours <= 0:
            return 0
        root = Path(settings.MEDIA_ROOT) / CHAT_DIR
        if not root.exists():
            return 0
        known = set(ChatImage.objects.values_list("file", flat=True))
        known |= set(ChatImage.objects.values_list("thumb", flat=True))
        cutoff = time.time() - orphan_hours * 3600
        total = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.relative_to(settings.MEDIA_ROOT).as_posix()
            if name in known:
                continue
            try:
                if path.stat().st_mtime > cutoff:
                    continue
            except OSError:
                continue
            total += 1
            if apply:
                try:
                    path.unlink()
                except OSError:
                    self.stderr.write(f"删除失败: {name}")
        return total

    def _delete_files(self, image: ChatImage, apply: bool = True) -> bool:
        """删除一张图片的原图与缩略图文件。

        Args:
            image: 聊天图片行。
            apply: 是否真正删除。

        Returns:
            是否至少有一个文件存在(即「本来需要删」)。
        """
        existed = False
        for field in (image.file, image.thumb):
            if not field:
                continue
            try:
                if not default_storage.exists(field.name):
                    continue
                existed = True
                if apply:
                    default_storage.delete(field.name)
            except Exception:
                self.stderr.write(f"删除失败: {field.name}")
        return existed
