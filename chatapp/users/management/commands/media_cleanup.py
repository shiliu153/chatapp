"""清理资料图与广场图的孤儿文件(磁盘有、库里没有对应行)。

聊天图/语音由 ``im_media_cleanup`` 负责;本命令只扫 ``photos/`` 与 ``posts/``。
孤儿文件通常来自「上传成功但事务回滚」或「删行时删文件失败」,按 mtime 宽限
24 小时,避免误删正在上传的文件。默认 dry-run,``--apply`` 才真正删除。
"""

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from feed.models import PostImage
from users.models import Photo

MEDIA_DIRS = ("photos", "posts")


class Command(BaseCommand):
    """删除资料图/广场图的孤儿文件(默认 dry-run)。"""

    help = "清理资料图与广场图的孤儿文件(默认 dry-run,--apply 才删)"

    def add_arguments(self, parser):
        """注册命令行参数。

        Args:
            parser: argparse 解析器。
        """
        parser.add_argument("--apply", action="store_true", help="真正删除;默认只打印")
        parser.add_argument("--orphan-hours", type=int, default=24,
                            help="孤儿文件宽限期(小时);0 表示不扫")

    def handle(self, *args, **options):
        """扫描两个目录并删除(或列出)孤儿文件。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Returns:
            None。
        """
        apply = bool(options["apply"])
        orphan_hours = int(options["orphan_hours"])
        if orphan_hours <= 0:
            self.stdout.write("跳过:--orphan-hours <= 0")
            return
        # 两类文件都登记在库,磁盘上多出来的才算孤儿
        known = set(Photo.objects.values_list("file", flat=True))
        known |= set(PostImage.objects.values_list("file", flat=True))
        cutoff = time.time() - orphan_hours * 3600
        total = 0
        for directory in MEDIA_DIRS:
            root = Path(settings.MEDIA_ROOT) / directory
            if not root.exists():
                continue
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
        mode = "apply" if apply else "dry-run"
        self.stdout.write(f"[media_cleanup] mode={mode} 孤儿文件={total}")
        if not apply:
            self.stdout.write("dry-run:未删除任何文件,确认无误后加 --apply")
