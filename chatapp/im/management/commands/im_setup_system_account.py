"""一次性环境步骤:创建「系统通知」IM 账号(封禁/解封消息的发送方)。

用法::

    python manage.py im_setup_system_account

可重复执行;账号已存在视为成功。新环境部署后需跑一次,否则封禁通知发不出去。

文件信息:
    文件名称          im/management/commands/im_setup_system_account.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.core.management.base import BaseCommand, CommandError

from im.client import SYSTEM_NOTICE_IDENTIFIER, SYSTEM_NOTICE_NICK, ensure_account


class Command(BaseCommand):
    """创建「系统通知」IM 账号。

    参数说明:
        无构造参数;由 ``manage.py`` 在调用命令时实例化。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py im_setup_system_account``

    备注信息:
        ``help`` 的语义是「创建「系统通知」IM 账号(幂等)」;账号身份与昵称取自
        ``SYSTEM_NOTICE_IDENTIFIER`` / ``SYSTEM_NOTICE_NICK``,账号已存在也视为成功。
    """

    help = "创建「系统通知」IM 账号(幂等)"

    def handle(self, *args, **options):
        """执行建号。

        参数说明:
            *args: 位置参数,未使用。
            **options: 已解析的命令行参数(本命令无参数)。

        返回参数:
            无返回值;成功时打印「系统账号就绪:<id>(<昵称>)」。

        使用示例:
            ``python manage.py im_setup_system_account``

        备注信息:
            ``ensure_account`` 返回假值时抛 ``CommandError``,提示看 IM 错误日志;
            该函数先查后建,不会覆盖已同步的昵称。
        """
        if not ensure_account(SYSTEM_NOTICE_IDENTIFIER, SYSTEM_NOTICE_NICK):
            raise CommandError("系统账号创建失败 —— 看上面的 IM 错误日志")
        self.stdout.write(self.style.SUCCESS(
            f"系统账号就绪:{SYSTEM_NOTICE_IDENTIFIER}({SYSTEM_NOTICE_NICK})"))
