"""开发用手测脚本:清掉一对用户之间的滑卡与配对记录,好重演配对流程。

用法::

    python manage.py dev_reset_pair --a u8 --b u9

清完后两人会重新出现在彼此的候选卡组里,可以再演一遍
「单向喜欢不弹 → 互喜弹配对动效」。IM 聊天记录不动(重配会再发一条灰条)。

文件信息:
    文件名称          discovery/management/commands/dev_reset_pair.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from discovery.models import Match, Swipe

User = get_user_model()


class Command(BaseCommand):
    """重置一对用户之间的滑卡与配对记录。

    参数说明:
        无;命令行参数由 ``add_arguments`` 声明,不经过构造函数。

    返回参数:
        ``Command`` 实例,由 ``manage.py`` 取出并调用 ``handle``。

    使用示例:
        ``python manage.py dev_reset_pair --a u8 --b u9``

    备注信息:
        只删 ``Swipe`` 与 ``Match`` 行,不改 IM 会话与历史消息;重配成功后会再发一条灰条。
    """

    help = "清掉两个用户之间的滑卡与配对记录(开发手测用)"

    def add_arguments(self, parser):
        """声明命令行参数。

        参数说明:
            parser: argparse 的参数解析器。

        返回参数:
            无返回值。

        使用示例:
            ``self.add_arguments(parser)``

        备注信息:
            ``--a`` / ``--b`` 都是必填,取值为 IM id(如 ``u8`` / ``u9``)。
        """
        parser.add_argument("--a", required=True, help="IM id,如 u8")
        parser.add_argument("--b", required=True, help="IM id,如 u9")

    def handle(self, *args, **options):
        """执行重置:删除两人之间双向的滑卡与配对记录。

        参数说明:
            *args: 位置参数,未使用。
            **options: 已解析的命令行参数(``a`` / ``b``,均为 IM id)。

        返回参数:
            无返回值(结果写到标准输出)。

        使用示例:
            ``python manage.py dev_reset_pair --a u8 --b u9``

        备注信息:
            两个 IM id 指向同一个人、格式非法或用户不存在时抛 ``CommandError``;
            删除是硬删除且不可撤销,仅用于开发手测。
        """
        user_a = self._user_by_im_id(options["a"])
        user_b = self._user_by_im_id(options["b"])
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

    def _user_by_im_id(self, raw: str):
        """把 IM id(如 ``u8``)解析成用户。

        参数说明:
            raw: 命令行传入的 IM id。

        返回参数:
            对应的用户实例(``User``)。

        使用示例:
            ``user = self._user_by_im_id("u8")``

        备注信息:
            只去掉前导 ``u`` 后按整数查主键,因此 ``8`` 与 ``u8`` 都能解析;格式非法或
            用户不存在时抛 ``CommandError``。这里按账号 id 查,不是 IM 侧的字符串 id。
        """
        try:
            user_id = int(raw.lstrip("u"))
        except ValueError:
            raise CommandError(f"IM id 格式不对:{raw}(应形如 u8)")
        user = User.objects.filter(id=user_id).first()
        if user is None:
            raise CommandError(f"没有 IM id = {raw} 的用户")
        return user
