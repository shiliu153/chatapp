"""开发用手测脚本:以某个用户身份给对方发消息(走腾讯 REST,不经 App)。

用法:
    python manage.py im_send --from u2 --to u3 --text "你好呀"
    python manage.py im_send --from u2 --to u3 --notice   # 发 match_notice 灰条
"""

from django.core.management.base import BaseCommand, CommandError

from im.client import MATCH_NOTICE_TEXT, send_custom_elem, send_text


class Command(BaseCommand):
    help = "以 --from 的身份给 --to 发一条消息(开发手测用)"

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="sender", required=True, help="发送方 IM id,如 u2")
        parser.add_argument("--to", dest="receiver", required=True, help="接收方 IM id,如 u3")
        parser.add_argument("--text", help="文本内容")
        parser.add_argument("--notice", action="store_true", help="发 match_notice 灰条事件")

    def handle(self, *args, **options):
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
