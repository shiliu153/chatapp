"""刷新候选池的随机排序键(``Profile.shuffle_key``)。

候选接口按 ``shuffle_key`` 索引取池,不再对全表 ``ORDER BY RAND()``;
但键长期不变会让同一批人一直排在同一位置,建议每天低峰跑一次:

    python manage.py refresh_shuffle_keys

``--dry-run`` 只统计将影响多少行,不写库。

文件信息:
    文件名称          users/management/commands/refresh_shuffle_keys.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import secrets

from django.core.management.base import BaseCommand

from users.models import SHUFFLE_KEY_UPPER, Profile


class Command(BaseCommand):
    """给所有资料重新生成随机排序键(候选池轮换)。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py refresh_shuffle_keys --dry-run``

    备注信息:
        ``help`` 的语义是「为所有资料重新生成候选池随机排序键,建议每天低峰执行」。
        新键由 ``secrets.randbelow(SHUFFLE_KEY_UPPER)`` 生成,取值范围与模型索引一致。
    """

    help = "为所有资料重新生成候选池随机排序键(建议每天低峰执行)"

    def add_arguments(self, parser):
        """注册命令行参数。

        参数说明:
            parser: argparse 解析器,由 Django 在调用 ``handle()`` 前传入。

        返回参数:
            无返回值。

        使用示例:
            ``self.add_arguments(parser)``

        备注信息:
            定义 ``--batch-size``(每批 ``bulk_update`` 行数,默认 500)与 ``--dry-run``(只统计不写库)。
        """
        parser.add_argument("--batch-size", type=int, default=500,
                            help="每批 bulk_update 的行数")
        parser.add_argument("--dry-run", action="store_true", help="只统计,不写库")

    def handle(self, *args, **options):
        """执行轮换并打印影响行数。

        参数说明:
            *args: 位置参数(未使用)。
            **options: 命令行选项,含 ``batch_size`` 与 ``dry_run``。

        返回参数:
            无返回值。

        使用示例:
            ``python manage.py refresh_shuffle_keys --batch-size 1000``

        备注信息:
            ``batch_size`` 至少取 1;全表扫描,资料量大时避开高峰执行。
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

        参数说明:
            batch: 已改好 ``shuffle_key`` 的 Profile 列表。
            dry_run: 为 ``True`` 时只计数,不写库。

        返回参数:
            本批处理的行数;``batch`` 为空时返回 0。

        使用示例:
            ``self._flush(batch, False)``

        备注信息:
            只对 ``shuffle_key`` 一列做 ``bulk_update``,不触发 ``save()`` 与模型信号。
        """
        if not batch:
            return 0
        if not dry_run:
            Profile.objects.bulk_update(batch, ["shuffle_key"])
        return len(batch)
