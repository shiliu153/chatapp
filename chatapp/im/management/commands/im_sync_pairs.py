"""一次性/随时可跑:把现有配对关系全量回填到自建 IM 的 ``im_pair`` 表。

用法::

    python manage.py im_sync_pairs --dry-run
    python manage.py im_sync_pairs

背景:H4 之后 imserver 只允许「有配对关系」的两人互发消息。上线这个校验之前
已经存在的配对不会被自动补录,必须跑一次本命令,否则老用户会突然发不出消息。
命令幂等(``im_pair`` 以 ``(user_a,user_b)`` 为主键),失败只记日志。

文件信息:
    文件名称          im/management/commands/im_sync_pairs.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.core.management.base import BaseCommand

from discovery.models import Match
from im.client import ensure_account, pair_add


class Command(BaseCommand):
    """把全部有效配对写入 imserver 的 ``im_pair``。

    参数说明:
        无构造参数;由 ``manage.py`` 在调用命令时实例化。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py im_sync_pairs --dry-run``

    备注信息:
        ``help`` 的语义是「把现有配对关系全量回填到自建 IM(幂等)」;幂等来自
        ``im_pair`` 以 ``(user_a,user_b)`` 为主键,重跑不会写出重复行。
    """

    help = "把现有配对关系全量回填到自建 IM(幂等)"

    def add_arguments(self, parser):
        """注册命令行参数。

        参数说明:
            parser: argparse 解析器,由 Django 在调用 ``handle()`` 前传入。

        返回参数:
            无返回值。

        使用示例:
            ``python manage.py im_sync_pairs --dry-run``

        备注信息:
            只定义 ``--dry-run`` 一个开关,写入 dest ``dry_run``;为真时只统计条数、
            不调 imserver 写入。
        """
        parser.add_argument("--dry-run", action="store_true",
                            help="只统计不写入")

    def handle(self, *args, **options):
        """逐条同步并汇总成败数量。

        参数说明:
            *args: 位置参数,未使用。
            **options: 已解析的命令行参数;``dry_run`` 为真时只统计。

        返回参数:
            无返回值;结尾打印「待同步:成功 N,失败 M」或「同步完成:成功 N,失败 M」。

        使用示例:
            ``python manage.py im_sync_pairs``

        备注信息:
            只处理 ``unmatched_at`` 为空的 ``Match``,每条先幂等补建双方的 IM 账号
            (老用户可能没走过 ``user_sig``,缺行会让发送 42201),再调 ``pair_add``;
            单条失败只累加计数、不中断整体流程。前缀为「待同步」时是 dry-run,
            此时不写 imserver。有失败用 ``WARNING`` 样式打印,全成功用 ``SUCCESS`` 样式。
        """
        dry_run = options["dry_run"]
        ok = fail = 0
        matches = (Match.objects.filter(unmatched_at__isnull=True)
                   .select_related("user_a__profile", "user_b__profile"))
        for match in matches.iterator():
            if dry_run:
                ok += 1
                continue
            # 先幂等建号:老用户可能从没走过自建 IM 的 user_sig,im_user 里没有行;
            # H4 之后发送要求收件人存在,缺行会导致配对灰条/消息 42201。
            a, b = match.user_a, match.user_b
            nick_a = getattr(getattr(a, "profile", None), "nickname", "") or ""
            nick_b = getattr(getattr(b, "profile", None), "nickname", "") or ""
            ensure_account(a.im_user_id, nick_a)
            ensure_account(b.im_user_id, nick_b)
            if pair_add(a.im_user_id, b.im_user_id):
                ok += 1
            else:
                fail += 1
        style = self.style.WARNING if fail else self.style.SUCCESS
        prefix = "待同步" if dry_run else "同步完成"
        self.stdout.write(style(f"{prefix}:成功 {ok},失败 {fail}"))
