"""一次性/随时可跑:把本地昵称全量同步到腾讯 IM(幂等,失败只记日志)。

用法:
    python manage.py im_sync_nicknames
"""

from django.core.management.base import BaseCommand

from im.client import set_profile_nick
from users.models import Profile


class Command(BaseCommand):
    help = "把用户昵称全量同步到腾讯 IM(幂等)"

    def handle(self, *args, **options):
        ok = fail = 0
        for profile in Profile.objects.exclude(nickname="").select_related("user"):
            if set_profile_nick(profile.user.im_user_id, profile.nickname):
                ok += 1
            else:
                fail += 1
        style = self.style.WARNING if fail else self.style.SUCCESS
        self.stdout.write(style(f"昵称同步完成:成功 {ok},失败 {fail}"))
