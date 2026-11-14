"""开发用手测脚本:清掉一对账号之间的滑卡与配对记录,好重演配对流程。

用法::

    python manage.py dev_reset_pair --a u8 --b u9

``--a`` / ``--b`` 收的是账号 id,``u8`` 与 ``8`` 等价:``u{id}`` 只是 IM 侧对账号的称呼,
本命令查的始终是 ``User.id``(账号主键),不是 IM 会话 id。
清完后两人会重新出现在彼此的候选卡组里,可以再演一遍
「单向喜欢不弹 → 互喜弹配对动效」。IM 聊天记录不动(重配会再发一条灰条)。
"""

import re

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from discovery.models import Match, Swipe

User = get_user_model()

# u 前缀可有可无、数字部分必填;配合 fullmatch 使用,因此 uu8 / u8x / u 都不认。
ACCOUNT_ID_RE = re.compile(r"u?(\d+)")


class Command(BaseCommand):
    """重置一对账号之间的滑卡与配对记录。"""

    help = "清掉两个账号之间的滑卡与配对记录(开发手测用)"

    def add_arguments(self, parser):
        """声明命令行参数。

        Args:
            parser: argparse 的参数解析器。
        """
        parser.add_argument(
            "--a", required=True, help="账号 id,如 u8 或 8(查的是 User.id,不是 IM 会话 id)")
        parser.add_argument(
            "--b", required=True, help="账号 id,如 u9 或 9(查的是 User.id,不是 IM 会话 id)")

    def handle(self, *args, **options):
        """执行重置:删除两人之间双向的滑卡与配对记录。

        Args:
            *args: 位置参数,未使用。
            **options: 已解析的命令行参数(``a`` / ``b``,均为账号 id,可写成 ``u8`` 或 ``8``)。

        Raises:
            CommandError: 两个账号 id 指向同一个人,或格式非法、账号不存在。
        """
        user_a = self._user_by_account_id(options["a"])
        user_b = self._user_by_account_id(options["b"])
        if user_a == user_b:
            raise CommandError("--a 和 --b 不能是同一个人")

        swipes, _ = Swipe.objects.filter(
            Q(swiper=user_a, target=user_b) | Q(swiper=user_b, target=user_a)
        ).delete()
        matches, _ = Match.objects.filter(
            Q(user_a=user_a, user_b=user_b) | Q(user_a=user_b, user_b=user_a)
        ).delete()

        self.stdout.write(self.style.SUCCESS(
            f"已重置 u{user_a.id} <-> u{user_b.id}:滑卡 {swipes} 条、配对 {matches} 条"))

    def _user_by_account_id(self, raw: str):
        """把账号 id(``u8`` 或 ``8``)解析成用户。

        Args:
            raw: 命令行传入的账号 id,形如 ``u8`` 或 ``8``。

        Returns:
            对应的用户实例。

        Raises:
            CommandError: 格式不是 ``u<数字>`` 或纯数字,或该账号不存在。
        """
        matched = ACCOUNT_ID_RE.fullmatch(raw)
        if matched is None:
            raise CommandError(f"账号 id 格式不对:{raw}(应形如 u8 或 8)")
        user = User.objects.filter(id=int(matched.group(1))).first()
        if user is None:
            raise CommandError(f"没有账号 id = {raw} 的用户")
        return user
