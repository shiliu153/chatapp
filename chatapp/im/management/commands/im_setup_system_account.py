"""一次性环境步骤:创建「系统通知」IM 账号(封禁/解封消息的发送方)。

用法::

    python manage.py im_setup_system_account

可重复执行;账号已存在视为成功。新环境部署后需跑一次,否则封禁通知发不出去。
"""

from django.core.management.base import BaseCommand, CommandError

from im.client import SYSTEM_NOTICE_IDENTIFIER, SYSTEM_NOTICE_NICK, ensure_account


class Command(BaseCommand):
    """创建「系统通知」IM 账号。"""

    help = "创建「系统通知」IM 账号(幂等)"

    def handle(self, *args, **options):
        """执行建号。

        参数说明:
            *args: 位置参数,未使用。
            **options: 已解析的命令行参数(本命令无参数)。

        返回参数:
            无返回值;成功时打印 ``系统账号就绪`` 一行。

        使用示例:
            ``python manage.py im_setup_system_account``(见 ``docs/pitfalls/im.md``)

        备注信息:
            可重复执行,账号已存在(imserver 返回 7015)视为成功;新环境部署后需跑一次,否则封禁通知发不出去。
            CommandError: IM 侧建号失败。
        """
        if not ensure_account(SYSTEM_NOTICE_IDENTIFIER, SYSTEM_NOTICE_NICK):
            raise CommandError("系统账号创建失败 —— 看上面的 IM 错误日志")
        self.stdout.write(self.style.SUCCESS(
            f"系统账号就绪:{SYSTEM_NOTICE_IDENTIFIER}({SYSTEM_NOTICE_NICK})"))
