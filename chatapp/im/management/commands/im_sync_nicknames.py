"""一次性/随时可跑:把本地昵称全量同步到 IM(幂等,失败只记日志)。

用法::

    python manage.py im_sync_nicknames

用于修复历史数据:IM 侧昵称被覆盖(如早期 ``account_import`` 的覆盖行为)后,
用它把库里正确的昵称重新刷回去。

文件信息:
    文件名称          im/management/commands/im_sync_nicknames.py
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

from im.client import set_profile_nick
from users.models import Profile


class Command(BaseCommand):
    """把全部非空昵称同步到 IM。

    参数说明:
        无构造参数;由 ``manage.py`` 在调用命令时实例化。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py im_sync_nicknames``

    备注信息:
        ``help`` 的语义是「把用户昵称全量同步到 IM(幂等)」;幂等来自 IM 侧
        ``set_profile_nick`` 的覆盖语义,重跑不会产生多余账号。
    """

    help = "把用户昵称全量同步到 IM(幂等)"

    def handle(self, *args, **options):
        """逐条同步并汇总成败数量。

        单条失败不中断整体流程,只在结尾汇总告警。

        参数说明:
            *args: 位置参数,未使用。
            **options: 已解析的命令行参数(本命令无参数)。

        返回参数:
            无返回值;结尾打印「昵称同步完成:成功 N,失败 M」。

        使用示例:
            ``python manage.py im_sync_nicknames``

        备注信息:
            只遍历 ``nickname`` 非空的 ``Profile``,并按 ``select_related("user")`` 取
            ``im_user_id``;单条失败不中断整体流程,只在结尾汇总告警 —— 有失败时用
            ``WARNING`` 样式打印,全成功用 ``SUCCESS`` 样式。
        """
        ok = fail = 0
        for profile in Profile.objects.exclude(nickname="").select_related("user"):
            if set_profile_nick(profile.user.im_user_id, profile.nickname):
                ok += 1
            else:
                fail += 1
        style = self.style.WARNING if fail else self.style.SUCCESS
        self.stdout.write(style(f"昵称同步完成:成功 {ok},失败 {fail}"))
