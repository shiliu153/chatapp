"""一次性/随时可跑:把本地昵称全量同步到腾讯 IM(幂等,失败只记日志)。

用法::

    python manage.py im_sync_nicknames

用于修复历史数据:IM 侧昵称被覆盖(如早期 ``account_import`` 的覆盖行为)后,
用它把库里正确的昵称重新刷回去。
"""

from django.core.management.base import BaseCommand

from im.client import set_profile_nick
from users.models import Profile


class Command(BaseCommand):
    """把全部非空昵称同步到 IM。"""

    help = "把用户昵称全量同步到腾讯 IM(幂等)"

    def handle(self, *args, **options):
        """逐条同步并汇总成败数量。

        单条失败不中断整体流程,只在结尾汇总告警。

        Args:
            *args: 位置参数,未使用。
            **options: 已解析的命令行参数(本命令无参数)。
        """
        ok = fail = 0
        for profile in Profile.objects.exclude(nickname="").select_related("user"):
            if set_profile_nick(profile.user.im_user_id, profile.nickname):
                ok += 1
            else:
                fail += 1
        style = self.style.WARNING if fail else self.style.SUCCESS
        self.stdout.write(style(f"昵称同步完成:成功 {ok},失败 {fail}"))
