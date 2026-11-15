"""一次性/随时可跑:把现有配对关系全量回填到自建 IM 的 ``im_pair`` 表。

用法::

    python manage.py im_sync_pairs --dry-run
    python manage.py im_sync_pairs

背景:H4 之后 imserver 只允许「有配对关系」的两人互发消息。上线这个校验之前
已经存在的配对不会被自动补录,必须跑一次本命令,否则老用户会突然发不出消息。
命令幂等(``im_pair`` 以 ``(user_a,user_b)`` 为主键),失败只记日志。
"""

from django.core.management.base import BaseCommand

from discovery.models import Match
from im.client import ensure_account, pair_add


class Command(BaseCommand):
    """把全部有效配对写入 imserver 的 ``im_pair``。"""

    help = "把现有配对关系全量回填到自建 IM(幂等)"

    def add_arguments(self, parser):
        """注册命令行参数。

        参数说明:
            parser: argparse 解析器。

        返回参数:
            无返回值。

        使用示例:
            ``python manage.py im_sync_pairs --dry-run``(见 ``docs/standards/dev-commands.md``)

        备注信息:
            只有一个 ``--dry-run`` 开关,默认关;打开时只统计待同步的配对数,不写 imserver。
        """
        parser.add_argument("--dry-run", action="store_true",
                            help="只统计不写入")

    def handle(self, *args, **options):
        """逐条同步并汇总成败数量。

        参数说明:
            *args: 位置参数,未使用。
            **options: 已解析的命令行参数;``dry_run`` 为真时只统计。

        返回参数:
            无返回值;汇总行写到标准输出。

        使用示例:
            ``python manage.py im_sync_pairs``(见 ``docs/ops/imserver.md`` 的上线回填步骤)

        备注信息:
            只处理 ``unmatched_at IS NULL`` 的有效配对;``im_pair`` 以 ``(user_a,user_b)`` 为主键,命令幂等。
            逐条先 ``ensure_account`` 补建 IM 账号(发送要求收件人存在,缺行会导致配对灰条与消息 42201),
            再 ``pair_add``;单条失败只累加计数,不中断整体流程。
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
