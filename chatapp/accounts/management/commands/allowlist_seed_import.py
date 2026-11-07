"""把 ``.env`` 的 ``SMS_PHONE_WHITELIST``(兜底种子)一次性导入准入名单表。

用法::

    python manage.py allowlist_seed_import --dry-run     # 只看会加哪些号
    python manage.py allowlist_seed_import               # 真导
    python manage.py allowlist_seed_import --note "老号迁移"

为什么需要这个命令(B-1c):
    名单的正主是数据库(``accounts.PhoneAllowlist``,``/ops/allowlist/`` 维护),
    但生产上线那一刻库里还是空的,只有 ``.env`` 里那串逗号分隔的老号码。
    这个命令把它们搬进库,之后 ``.env`` 就只是「库读不到时的兜底」——
    不然「停用某个老号」永远停不掉(它还在 ``.env`` 里)。

设计要点:
    1. **幂等**:已存在的号码一律跳过,重复执行不会重复插入、也不会改动备注与启停状态;
    2. **不重新启用**:库里已停用的号码**保持停用** —— 导入是「补齐」而不是「重置」,
       否则一次手误执行就把刚停掉的号全放回来了;
    3. **留一条流水**:每条真正插进来的号码写一条 ``PhoneAllowlistEvent``
       (``action=seed_import``,``operator`` 为空 —— 命令没有操作人);被幂等跳过的不写,
       否则重复执行一次就往审计表里刷一批噪声,把真正的人工操作埋掉;
    4. 输出只打脱敏号码(``139****9000``),清单本身是安全边界,别往日志里抄明文。

关联文档:
    - 运维手册:docs/ops/runbook.md「准入名单的日常运维」
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.allowlist import invalidate
from accounts.models import PhoneAllowlist, PhoneAllowlistAction, PhoneAllowlistEvent
from accounts.validators import mask_phone


class Command(BaseCommand):
    """把 ``settings.SMS_PHONE_WHITELIST`` 里的号码补进准入名单表。"""

    help = "把 .env 的 SMS_PHONE_WHITELIST 种子号码幂等导入 accounts.PhoneAllowlist"

    def add_arguments(self, parser):
        """声明命令行参数。

        Args:
            parser: Django 的参数解析器。
        """
        parser.add_argument(
            "--dry-run", action="store_true",
            help="只打印将要新增的号码与数量,不写库",
        )
        parser.add_argument(
            "--note", default="从 .env 种子导入", help="写进备注栏的说明文本",
        )

    def handle(self, *args, **options):
        """执行导入。

        Args:
            *args: 位置参数(管理命令框架会传,这里不用)。
            **options: 已解析的命令行选项(``dry_run`` / ``note``)。
        """
        seed = sorted(settings.SMS_PHONE_WHITELIST)
        if not seed:
            self.stdout.write("SMS_PHONE_WHITELIST 为空,没有可导入的号码。")
            return
        existing = set(PhoneAllowlist.objects.filter(phone__in=seed)
                       .values_list("phone", flat=True))
        missing = [phone for phone in seed if phone not in existing]
        self.stdout.write(
            f"种子 {len(seed)} 个 / 库里已有 {len(existing)} 个 / 待新增 {len(missing)} 个")
        if not missing:
            self.stdout.write("没有需要新增的号码。")
            return
        for phone in missing:
            self.stdout.write(f"  + {mask_phone(phone)}")
        if options["dry_run"]:
            self.stdout.write("--dry-run:未写库。")
            return
        note = options["note"]
        imported = 0
        with transaction.atomic():
            for phone in missing:
                _, created = PhoneAllowlist.objects.get_or_create(
                    phone=phone, defaults={"note": note})
                if not created:      # 并发下刚被别人插进来:按幂等跳过,不留流水
                    continue
                PhoneAllowlistEvent.objects.create(
                    phone=phone, action=PhoneAllowlistAction.SEED_IMPORT, note=note)
                imported += 1
            # 立刻生效:不让 App/Web 等快照 TTL;放在流水之后,理由同 /ops/ 的写路径。
            invalidate()
        self.stdout.write(self.style.SUCCESS(f"已导入 {imported} 个号码,立刻生效。"))
