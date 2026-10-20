"""手动发测试推送的管理命令:给真机验收用,不经过任何业务事件。

设计要点:
    1. 直接调用 ``send_push.run``,走和线上完全相同的「偏好 → 设备 → 冷却」链路,
       不是另写一条发送路径;
    2. 三类通知各给一条示例文案与深链,方便一次验收点击跳转;
    3. 设备没登记 / 偏好关闭 / 通道是日志后端,都给出明确提示,避免「发了但没收到」的误会。
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from notifications.models import NotificationPreference, PushDevice
from notifications.tasks import like_cooldown_key, send_push

KIND_CHOICES = ["like", "match", "system", "all"]


class Command(BaseCommand):
    """给指定用户发送一条或多条测试推送。"""

    help = "给指定用户发测试推送(需先配好极光 key,并在 App 登录过以登记设备)"

    def add_arguments(self, parser):
        """注册命令行参数。

        Args:
            parser: argparse 的解析器。
        """
        parser.add_argument("--user", type=int, required=True, help="接收者账号 id")
        parser.add_argument("--kind", choices=KIND_CHOICES, default="all",
                            help="发哪一类;默认三类各发一条")
        parser.add_argument("--peer", type=int, help="match 通知的聊天对象账号 id")
        parser.add_argument("--force", action="store_true",
                            help="忽略「新的喜欢」30 分钟冷却")

    def handle(self, *args, **options):
        """执行命令。

        Args:
            *args: 透传的位置参数。
            **options: 解析后的命令行选项。

        Raises:
            CommandError: 用户不存在 / 没有设备 / match 缺少 peer。
        """
        user = get_user_model().objects.filter(id=options["user"]).first()
        if user is None:
            raise CommandError(f"账号 {options['user']} 不存在")

        devices = PushDevice.objects.filter(user=user)
        if not devices.exists():
            raise CommandError("该账号没有登记设备:请先在 App 登录一次,再重试")

        kind = options["kind"]
        peer = options["peer"]
        if kind in ("match", "all") and peer is None:
            raise CommandError("--kind match/all 需要同时给 --peer(聊天对象账号 id)")

        preference = NotificationPreference.for_user(user)
        self.stdout.write(
            f"账号 {user.id};设备 {devices.count()} 台;"
            f"PUSH_ENABLED={settings.PUSH_ENABLED}"
        )
        if not settings.PUSH_ENABLED:
            self.stdout.write(self.style.WARNING(
                "PUSH_ENABLED=0:当前是日志后端,只会打日志,不会真的发到手机"))

        kinds = ["like", "match", "system"] if kind == "all" else [kind]
        for item in kinds:
            if item == "like" and options["force"]:
                cache.delete(like_cooldown_key(user.id))
            if item == "like" and not preference.likes:
                self.stdout.write(self.style.WARNING("「新的喜欢」开关已关闭,跳过"))
                continue
            if item == "match" and not preference.matches:
                self.stdout.write(self.style.WARNING("「配对成功」开关已关闭,跳过"))
                continue
            if item == "system" and not preference.system:
                self.stdout.write(self.style.WARNING("「系统通知」开关已关闭,跳过"))
                continue
            title, alert, extras = self._sample(item, peer)
            send_push.run(user.id, item, title, alert, extras)
            self.stdout.write(f"已发送 {item}: {title} → {extras['deeplink']}")

        self.stdout.write(self.style.SUCCESS("完成。若手机没收到,先看后端日志有没有 [推送-日志]。"))

    def _sample(self, kind, peer):
        """按通知类型给一条示例文案与深链。

        Args:
            kind: ``like`` / ``match`` / ``system``。
            peer: match 通知的聊天对象账号 id。

        Returns:
            ``(title, alert, extras)`` 三元组。
        """
        if kind == "like":
            return ("有人喜欢了你", "去看看是谁", {"deeplink": "/likes", "type": "like"})
        if kind == "match":
            return ("配对成功", "你和对方互相喜欢,快去打招呼吧",
                    {"deeplink": f"/chat/{peer}", "type": "match"})
        return ("系统通知", "这是一条测试系统通知",
                {"deeplink": "/chat/system_notice", "type": "system"})
