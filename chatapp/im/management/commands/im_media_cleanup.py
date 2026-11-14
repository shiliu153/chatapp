"""清理聊天媒体(图片与语音):保留期、孤儿文件、删除残留。

默认 dry-run(只打印将要删除的内容),``--apply`` 才真正删文件 —— 删文件不可逆,
定时任务必须显式带 ``--apply``。

三类动作互相独立:
    1. 保留期:可见且早于保留期的图片/语音 → 删文件,行改 ``expired``;
    2. 孤儿文件:磁盘上有、库里没有对应行、且 mtime 早于宽限期的文件;
    3. 删除残留:行已 ``deleted`` 但文件还在(上次存储删除失败)→ 补删。

文件信息:
    文件名称          im/management/commands/im_media_cleanup.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.utils import timezone

from im.models import ChatImage, ChatImageStatus, ChatVoice, ChatVoiceStatus

CHAT_DIR = "chat"


class Command(BaseCommand):
    """清理聊天图片的磁盘占用(默认 dry-run)。

    参数说明:
        无构造参数;由 ``manage.py`` 在调用命令时实例化。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py im_media_cleanup --apply``

    备注信息:
        ``help`` 的语义是「清理聊天图片:保留期过期、孤儿文件、删除残留,默认 dry-run,
        加 ``--apply`` 才真正删文件」;实现上语音同样被清理(见 ``_expire_voices``),
        命令名沿用历史叫法。
    """

    help = "清理聊天图片:保留期过期、孤儿文件、删除残留(默认 dry-run,--apply 才删)"

    def add_arguments(self, parser):
        """注册命令行参数。

        参数说明:
            parser: argparse 解析器,由 Django 在调用 ``handle()`` 前传入。

        返回参数:
            无返回值。

        使用示例:
            ``python manage.py im_media_cleanup --apply --retention-days 15``

        备注信息:
            定义 ``--apply``、``--retention-days``、``--voice-retention-days``、
            ``--orphan-hours``、``--batch-size`` 五个开关;两个保留期缺省时分别回落到
            ``CHAT_IMAGE_RETENTION_DAYS`` 与 ``CHAT_VOICE_RETENTION_DAYS``(各默认 30 天),
            取 0 表示跳过该类清理。
        """
        parser.add_argument("--apply", action="store_true", help="真正删除;默认只打印")
        parser.add_argument("--retention-days", type=int, default=None,
                            help="图片保留期(天);默认取 CHAT_IMAGE_RETENTION_DAYS,0 表示不清理")
        parser.add_argument("--voice-retention-days", type=int, default=None,
                            help="语音保留期(天);默认取 CHAT_VOICE_RETENTION_DAYS,0 表示不清理")
        parser.add_argument("--orphan-hours", type=int, default=24,
                            help="孤儿文件的宽限期(小时);0 表示不扫孤儿文件")
        parser.add_argument("--batch-size", type=int, default=200, help="每批处理的行数")

    def handle(self, *args, **options):
        """执行三类清理并打印汇总。

        参数说明:
            *args: 位置参数(未使用)。
            **options: 命令行选项,含 ``apply`` / ``retention_days`` /
                ``voice_retention_days`` / ``orphan_hours`` / ``batch_size``。

        返回参数:
            无返回值;清理结果以一行汇总写到 ``stdout``。

        使用示例:
            ``python manage.py im_media_cleanup --apply --batch-size 500``

        备注信息:
            四个动作依次执行:图片保留期 → 语音保留期 → 删除残留 → 孤儿文件;
            ``batch_size`` 至少取 1,非法值按 1 处理。dry-run 时各动作只数不删,
            结尾额外打印一行提示要求确认后加 ``--apply``。
        """
        apply = bool(options["apply"])
        retention_days = options["retention_days"]
        if retention_days is None:
            retention_days = getattr(settings, "CHAT_IMAGE_RETENTION_DAYS", 30)
        voice_retention_days = options["voice_retention_days"]
        if voice_retention_days is None:
            voice_retention_days = getattr(settings, "CHAT_VOICE_RETENTION_DAYS", 30)
        batch_size = max(int(options["batch_size"]), 1)

        mode = "apply" if apply else "dry-run"
        self.stdout.write(f"[im_media_cleanup] mode={mode}")

        expired = self._expire_old(retention_days, batch_size, apply)
        expired_voices = self._expire_voices(voice_retention_days, batch_size, apply)
        removed_files = self._delete_leftovers(batch_size, apply)
        orphans = self._delete_orphans(int(options["orphan_hours"]), apply)
        self.stdout.write(
            f"保留期({retention_days} 天):{expired} 张;"
            f"语音保留期({voice_retention_days} 天):{expired_voices} 条;"
            f"删除残留:{removed_files} 个文件;孤儿文件:{orphans} 个")
        if not apply:
            self.stdout.write("dry-run:未删除任何文件,确认无误后加 --apply")

    def _expire_old(self, retention_days: int, batch_size: int, apply: bool) -> int:
        """把早于保留期的可见图片删文件并标记过期。

        参数说明:
            retention_days: 保留天数;``0`` 表示跳过。
            batch_size: 每批处理行数。
            apply: 是否真正删除。

        返回参数:
            处理的图片数量;dry-run 时是「将要处理」的行数。

        使用示例:
            ``self._expire_old(30, 200, False)``

        备注信息:
            只处理 ``status=VISIBLE`` 且 ``created_at`` 早于 cutoff 的行;批处理按 ``id``
            升序取前 ``batch_size`` 条,处理完即改状态为 ``EXPIRED``,因此下一轮查询自然
            缩小、循环必然收敛。行更新只写 ``status`` 与 ``expired_at`` 两列。
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

    def _expire_voices(self, retention_days: int, batch_size: int, apply: bool) -> int:
        """把早于保留期的可见语音删文件并标记过期。

        参数说明:
            retention_days: 保留天数;``0`` 表示跳过。
            batch_size: 每批处理行数。
            apply: 是否真正删除。

        返回参数:
            处理的语音数量;dry-run 时是「将要处理」的行数。

        使用示例:
            ``self._expire_voices(30, 200, False)``

        备注信息:
            与图片保留期同构:只处理 ``status=VISIBLE`` 且 ``created_at`` 早于 cutoff 的
            语音,按 ``id`` 升序分批,处理完改状态为 ``EXPIRED`` 并写 ``expired_at``。
        """
        if retention_days <= 0:
            return 0
        cutoff = timezone.now() - timedelta(days=retention_days)
        rows = ChatVoice.objects.filter(
            status=ChatVoiceStatus.VISIBLE, created_at__lt=cutoff)
        if not apply:
            return rows.count()

        total = 0
        while True:
            batch = list(rows.order_by("id")[:batch_size])
            if not batch:
                return total
            for voice in batch:
                self._delete_voice_files(voice)
                voice.status = ChatVoiceStatus.EXPIRED
                voice.expired_at = timezone.now()
                voice.save(update_fields=["status", "expired_at"])
            total += len(batch)

    def _delete_leftovers(self, batch_size: int, apply: bool) -> int:
        """补删「行已删除但文件还在」的残留文件。

        参数说明:
            batch_size: 每批处理行数。
            apply: 是否真正删除。

        返回参数:
            仍有文件存在的图片行数量。

        使用示例:
            ``self._delete_leftovers(200, False)``

        备注信息:
            只扫 ``status=DELETED`` 的图片行,用 ``iterator(chunk_size=batch_size)`` 流式
            遍历;不动数据库状态,纯粹补删上次存储删除失败留下的文件。
        """
        total = 0
        for image in ChatImage.objects.filter(
                status=ChatImageStatus.DELETED).iterator(chunk_size=batch_size):
            if self._delete_files(image, apply=apply):
                total += 1
        return total

    def _delete_orphans(self, orphan_hours: int, apply: bool) -> int:
        """删除磁盘上没有数据库行、且超过宽限期的聊天图片文件。

        参数说明:
            orphan_hours: 宽限期(小时);``0`` 表示跳过。
            apply: 是否真正删除。

        返回参数:
            删除(或将要删除)的文件数量。

        使用示例:
            ``self._delete_orphans(24, False)``

        备注信息:
            扫描范围是 ``MEDIA_ROOT/chat`` 下的全部文件(图片、缩略图、语音都在这棵树下),
            「有数据库行」的判定同时收集 ``ChatImage.file`` / ``ChatImage.thumb`` /
            ``ChatVoice.file`` 三个字段的取值。``mtime`` 晚于宽限期的文件跳过,避免删掉
            刚上传还没写库的行;``stat`` 抛 ``OSError`` 也跳过。``unlink`` 失败只写 stderr,
            不计入失败统计。
        """
        if orphan_hours <= 0:
            return 0
        root = Path(settings.MEDIA_ROOT) / CHAT_DIR
        if not root.exists():
            return 0
        known = set(ChatImage.objects.values_list("file", flat=True))
        known |= set(ChatImage.objects.values_list("thumb", flat=True))
        known |= set(ChatVoice.objects.values_list("file", flat=True))
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

        参数说明:
            image: 聊天图片行。
            apply: 是否真正删除,默认 ``True``。

        返回参数:
            是否至少有一个文件存在(即「本来需要删」)。

        使用示例:
            ``self._delete_files(image, apply=False)``

        备注信息:
            逐字段处理 ``file`` 与 ``thumb``,字段为空则跳过;存储层任何异常都只写 stderr
            (``删除失败: 文件名``)并继续处理下一个字段,不向外抛。
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

    def _delete_voice_files(self, voice: ChatVoice, apply: bool = True) -> bool:
        """删除一条语音的文件。

        参数说明:
            voice: 聊天语音行。
            apply: 是否真正删除,默认 ``True``。

        返回参数:
            文件原本是否存在(即「本来需要删」)。

        使用示例:
            ``self._delete_voice_files(voice, apply=False)``

        备注信息:
            只处理 ``file`` 一个字段;存储层抛异常时写 stderr 并返回 ``False``,
            由调用方继续处理下一行。
        """
        if not voice.file:
            return False
        try:
            if not default_storage.exists(voice.file.name):
                return False
            if apply:
                default_storage.delete(voice.file.name)
            return True
        except Exception:
            self.stderr.write(f"删除失败: {voice.file.name}")
            return False
