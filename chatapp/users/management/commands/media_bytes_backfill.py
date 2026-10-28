"""回填资料图与广场图的 ``bytes`` 字段(存量数据)。

``bytes`` 用于单账号存储配额统计(M7);新增上传会自己写入,只有历史行是 0。
部署本批后跑一次即可(幂等):

    python manage.py media_bytes_backfill --dry-run   # 先看要补多少
    python manage.py media_bytes_backfill
"""

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from feed.models import PostImage
from users.models import Photo


class Command(BaseCommand):
    """把存量照片/动态图的文件大小写回 ``bytes``。"""

    help = "回填 Photo.bytes / PostImage.bytes(存量行),供存储配额统计"

    def add_arguments(self, parser):
        """注册命令行参数。

        Args:
            parser: argparse 解析器。
        """
        parser.add_argument("--dry-run", action="store_true", help="只统计,不写库")
        parser.add_argument("--batch-size", type=int, default=500, help="每批处理行数")

    def handle(self, *args, **options):
        """按模型逐个回填并打印结果。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Returns:
            None。
        """
        dry_run = bool(options["dry_run"])
        batch_size = max(int(options["batch_size"]), 1)
        for model, label in ((Photo, "资料图"), (PostImage, "动态图")):
            filled, missing = self._backfill(model, batch_size, dry_run)
            self.stdout.write(f"{label}:回填 {filled} 行,文件缺失 {missing} 行")
        if dry_run:
            self.stdout.write("dry-run:未写库,确认无误后去掉 --dry-run")

    def _backfill(self, model, batch_size, dry_run):
        """给单个模型的 ``bytes=0`` 行补文件大小。

        Args:
            model: ``Photo`` 或 ``PostImage``。
            batch_size: 迭代游标的分块大小。
            dry_run: 为 ``True`` 时不写库。

        Returns:
            ``(回填行数, 文件缺失行数)`` 二元组。
        """
        filled = 0
        missing = 0
        rows = model.objects.filter(bytes=0).only("id", "file")
        for row in rows.iterator(chunk_size=batch_size):
            try:
                size = default_storage.size(row.file.name)
            except Exception:
                missing += 1
                continue
            if not dry_run:
                model.objects.filter(pk=row.pk).update(bytes=size)
            filled += 1
        return filled, missing
