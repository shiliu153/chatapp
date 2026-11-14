"""回填资料图与广场图的 ``bytes`` 字段(存量数据)。

``bytes`` 用于单账号存储配额统计(M7);新增上传会自己写入,只有历史行是 0。
部署本批后跑一次即可(幂等):

    python manage.py media_bytes_backfill --dry-run   # 先看要补多少
    python manage.py media_bytes_backfill

文件信息:
    文件名称          users/management/commands/media_bytes_backfill.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from feed.models import PostImage
from users.models import Photo


class Command(BaseCommand):
    """把存量照片/动态图的文件大小写回 ``bytes``。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py media_bytes_backfill --dry-run``

    备注信息:
        ``help`` 的语义是「回填 Py 侧 ``Photo.bytes`` 与 ``PostImage.bytes`` 的存量行,供存储配额统计」。
        两模型逐表处理,单个模型出错不影响另一个模型的统计输出。
    """

    help = "回填 Photo.bytes / PostImage.bytes(存量行),供存储配额统计"

    def add_arguments(self, parser):
        """注册命令行参数。

        参数说明:
            parser: argparse 解析器,由 Django 在调用 ``handle()`` 前传入。

        返回参数:
            无返回值。

        使用示例:
            ``self.add_arguments(parser)``

        备注信息:
            定义 ``--dry-run``(只统计不写库)与 ``--batch-size``(每批处理行数,默认 500)。
        """
        parser.add_argument("--dry-run", action="store_true", help="只统计,不写库")
        parser.add_argument("--batch-size", type=int, default=500, help="每批处理行数")

    def handle(self, *args, **options):
        """按模型逐个回填并打印结果。

        参数说明:
            *args: 位置参数(未使用)。
            **options: 命令行选项,含 ``dry_run`` 与 ``batch_size``。

        返回参数:
            无返回值。

        使用示例:
            ``python manage.py media_bytes_backfill --dry-run --batch-size 1000``

        备注信息:
            ``batch_size`` 至少取 1;``--dry-run`` 时只打印将回填的行数并提示去掉该开关。
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

        参数说明:
            model: 带 ``bytes`` 与 ``file`` 字段的模型,``Photo`` 或 ``PostImage``。
            batch_size: 迭代游标的分块大小。
            dry_run: 为 ``True`` 时不写库。

        返回参数:
            ``(回填行数, 文件缺失行数)`` 二元组。

        使用示例:
            ``self._backfill(Photo, 500, False)``

        备注信息:
            ``default_storage.size()`` 抛异常(文件已不在存储上)时计入「文件缺失」并跳过该行;
            写库走 ``update()``,不触发 ``save()`` 与模型信号。
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
