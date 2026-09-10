"""开发用手测脚本:清掉一对用户之间的滑卡与配对记录,好重演配对流程。

用法:
    python manage.py dev_reset_pair --a u8 --b u9

清完后两人会重新出现在彼此的候选卡组里,可以再演一遍
「单向喜欢不弹 → 互喜弹配对动效」。IM 聊天记录不动(重配会再发一条灰条)。
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from discovery.models import Match, Swipe

User = get_user_model()


class Command(BaseCommand):
    help = "清掉两个用户之间的滑卡与配对记录(开发手测用)"

    def add_arguments(self, parser):
        parser.add_argument("--a", required=True, help="IM id,如 u8")
        parser.add_argument("--b", required=True, help="IM id,如 u9")

    def handle(self, *args, **options):
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
        try:
            user_id = int(raw.lstrip("u"))
        except ValueError:
            raise CommandError(f"IM id 格式不对:{raw}(应形如 u8)")
        user = User.objects.filter(id=user_id).first()
        if user is None:
            raise CommandError(f"没有 IM id = {raw} 的用户")
        return user
