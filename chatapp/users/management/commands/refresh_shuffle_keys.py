"""刷新候选池的随机排序键(``Profile.shuffle_key``)。

候选接口按 ``shuffle_key`` 索引取池,不再对全表 ``ORDER BY RAND()``;
但键长期不变会让同一批人一直排在同一位置,建议每天低峰跑一次:

    python manage.py refresh_shuffle_keys

``--dry-run`` 只统计将影响多少行,不写库。
"""

import secrets

from django.core.management.base import BaseCommand

from users.models import SHUFFLE_KEY_UPPER, Profile


class Command(BaseCommand):
    """给所有资料重新生成随机排序键(候选池轮换)。"""

    help = "为所有资料重新生成候选池随机排序键(建议每天低峰执行)"

    def add_arguments(self, parser):
        """注册命令行参数。

        Args:
            parser: argparse 解析器。
        """
        parser.add_argument("--batch-size", type=int, default=500,
                            help="每批 bulk_update 的行数")
        parser.add_argument("--dry-run", action="store_true", help="只统计,不写库")

    def handle(self, *args, **options):
        """执行轮换并打印影响行数。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Returns:
            None。
        """
        batch_size = max(int(options["batch_size"]), 1)
        dry_run = bool(options["dry_run"])
        total = 0
        batch = []
        # only("id") 避免把整行资料读进内存;新键在 Python 侧生成后批量写回
        for profile in Profile.objects.only("id").iterator(chunk_size=batch_size):
            profile.shuffle_key = secrets.randbelow(SHUFFLE_KEY_UPPER)
            batch.append(profile)
            if len(batch) >= batch_size:
                total += self._flush(batch, dry_run)
                batch = []
        total += self._flush(batch, dry_run)
        suffix = "(dry-run,未写库)" if dry_run else ""
        self.stdout.write(f"[refresh_shuffle_keys] 更新 {total} 条{suffix}")

    def _flush(self, batch, dry_run):
        """把一批新键写回数据库。

        Args:
            batch: 已改好 ``shuffle_key`` 的 Profile 列表。
            dry_run: 为 ``True`` 时只计数。

        Returns:
            本批处理的行数。
        """
        if not batch:
            return 0
        if not dry_run:
            Profile.objects.bulk_update(batch, ["shuffle_key"])
        return len(batch)
