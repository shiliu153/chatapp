"""开发用手测脚本:以某个用户身份给对方发消息(走 imserver 内部 API,不经 App)。

用法::

    python manage.py im_send --from u2 --to u3 --text "你好呀"
    python manage.py im_send --from u2 --to u3 --notice   # 发 match_notice 灰条

文件信息:
    文件名称          im/management/commands/im_send.py
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

from im.client import MATCH_NOTICE_TEXT, send_custom_elem, send_text


class Command(BaseCommand):
    """以指定身份代发一条 IM 消息。

    参数说明:
        无构造参数;由 ``manage.py`` 在调用命令时实例化。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py im_send --from u2 --to u3 --text "你好"``

    备注信息:
        ``help`` 的语义是「以 ``--from`` 的身份给 ``--to`` 发一条消息(开发手测用)」;
        直接走 imserver 内部 API,不经 App,因此可用于验证发消息链路是否通。
    """

    help = "以 --from 的身份给 --to 发一条消息(开发手测用)"

    def add_arguments(self, parser):
        """声明命令行参数。

        参数说明:
            parser: argparse 的参数解析器,由 Django 在调用 ``handle()`` 前传入。

        返回参数:
            无返回值。

        使用示例:
            ``python manage.py im_send --from u2 --to u3 --text "你好呀"``

        备注信息:
            ``--from`` / ``--to`` 必填,分别写入 dest ``sender`` / ``receiver``;
            ``--text`` 与 ``--notice`` 二选一,互斥关系在 ``handle()`` 里校验。
        """
        parser.add_argument("--from", dest="sender", required=True, help="发送方 IM id,如 u2")
        parser.add_argument("--to", dest="receiver", required=True, help="接收方 IM id,如 u3")
        parser.add_argument("--text", help="文本内容")
        parser.add_argument("--notice", action="store_true", help="发 match_notice 灰条事件")

    def handle(self, *args, **options):
        """按参数发送文本或灰条。

        参数说明:
            *args: 位置参数,未使用。
            **options: 已解析的命令行参数(``sender`` / ``receiver`` / ``text`` / ``notice``)。

        返回参数:
            无返回值;成功时按 ``Command`` 的 success 样式打印「已发送 A -> B」。

        使用示例:
            ``python manage.py im_send --from u2 --to u3 --notice``

        备注信息:
            抛 ``CommandError`` 的两种情况:``--text`` 与 ``--notice`` 同时给出或都未给;
            IM 侧返回失败(账号没导入会报 7013 之类,需看 IM 错误日志)。
        """
        text, notice = options["text"], options["notice"]
        if bool(text) == bool(notice):
            raise CommandError("--text 和 --notice 必须且只能给一个")
        if notice:
            ok = send_custom_elem(options["sender"], options["receiver"],
                                  {"type": "match_notice"}, MATCH_NOTICE_TEXT)
        else:
            ok = send_text(options["sender"], options["receiver"], text)
        if not ok:
            raise CommandError("发送失败 —— 看上面的 IM 错误日志(账号没导入会报 7013 之类)")
        self.stdout.write(
            self.style.SUCCESS(f"已发送 {options['sender']} -> {options['receiver']}"))
