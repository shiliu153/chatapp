"""清理语音异步转码的残骸:24 小时前的临时文件与 ``pending`` 行。

异步转码把原始音频先落进 ``MEDIA_ROOT/tmp/voice/``、行标成 ``pending``,由 worker 取走
转码后删除。进程崩在中间(worker 被杀、broker 丢消息、磁盘满)会留下两类残骸:

    1. ``pending`` 行超时没转完 —— 转码任务不会再来了,行留着只会让客户端一直轮询;
    2. 临时文件没有行认领 —— 行被删了、或行建好之前就崩了。

两者都按 24 小时判定(``--hours`` 可改),与 ``im_media_cleanup`` 的孤儿宽限期同一口径:
一次转码 15 秒上限,留 24 小时不会误删正在跑的任务。默认 dry-run,``--apply`` 才真正删除 ——
删文件不可逆。命令幂等:重复执行不会报错,第二次只会打印 0 条。

关联文档:
    - 运维命令:docs/standards/dev-commands.md §2
    - 接口契约:docs/api/im.md(6.4 / 6.5)、docs/api/users.md(2.11)

文件信息:
    文件名称          im/management/commands/voice_transcode_cleanup.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-16        shiliu153          新建:语音异步转码残骸兜底清理(第五轮审计 M-3)
"""

import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from im.models import ChatVoice, TranscodeStatus
from im.transcode_queue import TMP_PREFIX, STALE_HOURS


class Command(BaseCommand):
    """清理超时的语音转码临时文件与 ``pending`` 行(默认 dry-run)。"""

    help = ("清理语音异步转码的残骸:--hours 前的 tmp/voice 文件与 pending 行"
            "(默认 dry-run,--apply 才删)")

    def add_arguments(self, parser):
        """注册命令行参数。

        参数说明:
            parser: argparse 解析器。

        返回参数:
            无返回值。

        使用示例:
            ``python manage.py voice_transcode_cleanup --hours 24 --apply``
            (见 ``im/tests.py`` 的 ``VoiceTranscodeCleanupTests``)

        备注信息:
            ``--apply`` 默认关,不带只统计;``--hours`` 默认 24,传 0 或负数表示跳过
            (什么都不做,避免「传 0 以为清全部」的误操作)。
        """
        parser.add_argument("--apply", action="store_true", help="真正删除;默认只统计")
        parser.add_argument("--hours", type=int, default=STALE_HOURS,
                            help=f"残骸的判定阈值(小时),默认 {STALE_HOURS};<=0 表示跳过")

    def handle(self, *args, **options):
        """执行两遍清理并打印汇总。

        参数说明:
            *args: 位置参数(未使用)。
            **options: 命令行选项(``apply`` / ``hours``)。

        返回参数:
            无返回值;两遍清理的条数写到标准输出。

        使用示例:
            ``python manage.py voice_transcode_cleanup --apply``(见 ``deploy`` 的每日维护)

        备注信息:
            先收 ``pending`` 行(顺带删它指向的临时文件),再扫临时区的孤儿文件 ——
            顺序反了会把「行还在、文件刚被删」的行留成 ``pending`` 直到下一轮。
            默认 dry-run 只统计;``--apply`` 才真正删,删文件不可逆。
        """
        hours = int(options["hours"])
        apply = bool(options["apply"])
        mode = "apply" if apply else "dry-run"
        self.stdout.write(f"[voice_transcode_cleanup] mode={mode} hours={hours}")
        if hours <= 0:
            self.stdout.write("跳过:--hours <= 0")
            return

        cutoff = timezone.now() - timedelta(hours=hours)
        rows = self._drop_pending_rows(cutoff, apply)
        files = self._drop_stale_files(hours, apply)
        self.stdout.write(f"pending 行:{rows} 条;临时文件:{files} 个")
        if not apply:
            self.stdout.write("dry-run:未删除任何内容,确认无误后加 --apply")

    def _drop_pending_rows(self, cutoff, apply: bool) -> int:
        """删掉超过阈值仍停在 ``pending`` 的行(连同它的临时文件)。

        参数说明:
            cutoff: 时间阈值(``created_at`` 早于它的行才算残骸)。
            apply: 是否真正删除。

        返回参数:
            处理(或将要处理)的行数。

        使用示例:
            ``rows = self._drop_pending_rows(cutoff, apply)``(见本模块 ``handle``)

        备注信息:
            ``users.models`` 在函数体内导入:``users`` 依赖 ``im.models``,反向的模块级导入
            会成环。转码任务对「行已不存在」是幂等的,所以这里删行不需要和 worker 打招呼。
        """
        from users.models import ProfileVoice   # 延迟导入,避免与 users.models 成环

        total = 0
        for model in (ChatVoice, ProfileVoice):
            stale = model.objects.filter(transcode_status=TranscodeStatus.PENDING,
                                         created_at__lt=cutoff)
            total += stale.count() if not apply else self._delete_rows(stale)
        return total

    def _delete_rows(self, queryset) -> int:
        """逐行删文件再删行(逐条是为了先删文件、后删库,失败能定位)。

        参数说明:
            queryset: 待删除的 ``pending`` 行查询集。

        返回参数:
            实际删掉的行数。

        使用示例:
            ``total += self._delete_rows(stale)``(见本模块 ``_drop_pending_rows``)

        备注信息:
            文件删失败只写 stderr 后继续删行 —— 行留着客户端会一直轮询,比丢一个临时文件更糟;
            残留文件下一轮扫临时区时会被扫到。
        """
        total = 0
        for row in queryset:
            name = row.file.name or ""
            if name:
                try:
                    row.file.storage.delete(name)
                except Exception:
                    self.stderr.write(f"删除失败: {name}")
            row.delete()
            total += 1
        return total

    def _drop_stale_files(self, hours: int, apply: bool) -> int:
        """删掉临时区里超过阈值、没有行认领(或行已被上面删掉)的文件。

        参数说明:
            hours: 判定阈值(小时),按文件 mtime 算。
            apply: 是否真正删除。

        返回参数:
            处理(或将要处理)的文件数。

        使用示例:
            ``files = self._drop_stale_files(hours, apply)``(见本模块 ``handle``)

        备注信息:
            只扫 ``MEDIA_ROOT/tmp/voice`` 一层(临时区是扁平的 ``<uuid>.<ext>``);mtime 晚于
            阈值的文件视为「可能还在上传/转码」,跳过。
        """
        root = Path(settings.MEDIA_ROOT) / TMP_PREFIX
        if not root.exists():
            return 0
        cutoff = time.time() - hours * 3600
        total = 0
        for path in root.glob("*"):
            if not path.is_file():
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
                    self.stderr.write(f"删除失败: {path.name}")
        return total
