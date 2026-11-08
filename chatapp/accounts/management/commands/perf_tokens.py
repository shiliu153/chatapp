"""签发压测用访问令牌(每账号一行 JSON 头集),供 ``perf/run.py --headers-file`` 使用。

为什么不让压测脚本自己走短信登录批量取令牌:
    1. **IP 限流**:``sms_verify`` 按 IP 限流,几十个账号连着登录就被 429 挡住;
    2. **同类端互顶**:每登录一次,该端的会话版本 +1,前一个令牌立刻作废 ——
       批量"登录取令牌"等于让这些账号互相顶号,拿到的令牌一大半是死的;
    3. 这两条都是产品的正式行为,不该为了压测去改代码或改配置。

所以这里直接用 ``SessionRefreshToken.for_user`` 在库内签发:不碰短信、不动会话版本,
签出来的和 App/Web 登录拿到的是同一种 access(同样带 ``session_version`` 与 ``ct`` claim;
这些账号通常没有端会话行,鉴权与签发都按 ``User.session_version`` 的历史值兜底)。

为什么需要多账号:写接口的限流都按用户计(滑卡 300/小时、发动态 20/天)。
单账号跑几秒就会撞 429,压出来的是限额而不是容量。粗算需要的账号数::

    账号数 ≈ 目标 RPS × 压测时长(秒) ÷ 单账号额度

例如 30 秒压到 50 rps 的滑卡 ≈ 1500 次 > 5 个账号的额度,得用 20 个以上。

用法::

    python manage.py perf_tokens --count 50 --out perf/results/headers.jsonl
    python manage.py perf_tokens --count 5 --start 100      # 跳过前 100 个测试号

每行形如 ``{"Authorization": "Bearer ...", "X-Forwarded-For": "10.99.0.7"}``。
``X-Forwarded-For`` 让 IP 维度的限流按连接分散 —— **只在直连 gunicorn 时生效**;
过 nginx 时它排在真实来源前面,DRF 取最后一跳,不吃这个值。

注意事项:
    1. 文件里是活令牌 —— 压测完立刻删除,别进 git、别贴群(命令会把文件权限设成 600);
    2. access 默认 30 分钟过期,压测前现场签发,不要提前几小时准备好;
    3. 只签 ``seed_scale_users`` 造的 199 号段测试号,并排除 staff/superuser;
    4. ``DEBUG=0``(生产)默认拒绝执行,确需压生产副本时显式 ``--allow-production``。

关联文档:
    - 压测入口与场景矩阵:perf/README.md
"""

import json
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.tokens import SessionRefreshToken

User = get_user_model()


class Command(BaseCommand):
    """给压测发令牌的管理命令。"""

    help = "签发压测用访问令牌(每行一个头集 JSON),供 perf/run.py --headers-file"

    def add_arguments(self, parser):
        """声明命令行参数。

        Args:
            parser: argparse 的参数解析器。
        """
        parser.add_argument("--count", type=int, default=20, help="签发几个账号")
        parser.add_argument("--start", type=int, default=0,
                            help="从号段内第几个账号开始(偏移,用来换一批号)")
        parser.add_argument("--xff-prefix", default="10.99",
                            help="X-Forwarded-For 前缀(默认 10.99)")
        parser.add_argument("--out", default="", help="输出文件;不给就打到 stdout")
        parser.add_argument("--allow-production", action="store_true",
                            help="DEBUG=0 时也允许签发(仅压测生产副本时用)")

    def handle(self, *args, **options):
        """签发令牌并写出头集文件。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Raises:
            CommandError: 生产环境未显式放行、数量越界,或没有可用测试号。
        """
        if not settings.DEBUG and not options["allow_production"]:
            raise CommandError("生产环境默认不签发压测令牌;确需时加 --allow-production")
        count = options["count"]
        if count <= 0 or count > 1000:
            raise CommandError("--count 必须在 1..1000 之间")

        users = self._pick_users(count, options["start"])
        if not users:
            raise CommandError("没有可用的测试号,先跑 "
                               "python manage.py seed_scale_users --count 1000")
        if len(users) < count:
            self.stderr.write(f"只找到 {len(users)} 个测试号(要 {count} 个);"
                              f"先补跑 seed_scale_users 或用 --start 换一批")

        lines = [json.dumps(self._header_set(user, index, options["xff_prefix"]),
                            ensure_ascii=False)
                 for index, user in enumerate(users)]
        if not options["out"]:
            self.stdout.write("\n".join(lines))
            return
        path = Path(options["out"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)   # 里面有活令牌,别让同机其它账号读到
        except OSError:
            pass
        self.stdout.write(self.style.SUCCESS(
            f"已写入 {len(lines)} 个账号的令牌:{path}"
            f"(access 30 分钟后过期,压测完删掉)"))

    def _pick_users(self, count: int, start: int) -> list:
        """取号段内可用的测试号(排除运营账号与停用账号)。

        Args:
            count: 需要几个账号。
            start: 号段内的偏移。

        Returns:
            账号列表,按 id 升序;数量可能少于 ``count``。
        """
        # 号段的唯一定义在造数命令里,这里复用它,避免两处各写一个魔数
        from users.management.commands.seed_scale_users import PHONE_BASE, PHONE_MAX
        return list(
            User.objects
            .filter(phone__gte=str(PHONE_BASE),
                    phone__lt=str(PHONE_BASE + PHONE_MAX),
                    is_active=True)
            .exclude(is_staff=True)
            .exclude(is_superuser=True)
            .order_by("id")[start:start + count])

    def _header_set(self, user, index: int, xff_prefix: str) -> dict[str, str]:
        """给一个账号签令牌,拼出它那一行的头集。

        Args:
            user: 账号实例。
            index: 本次输出的序号(用于给每条连接分一个不同的 X-Forwarded-For)。
            xff_prefix: X-Forwarded-For 前缀,例如 ``10.99``。

        Returns:
            ``{头名: 头值}``,直接写进 ``--headers-file`` 的一行。
        """
        token = SessionRefreshToken.for_user(user).access_token
        return {
            "Authorization": f"Bearer {token}",
            # 10.99.a.b:a = 每 250 个账号换一段,b = 序号取模 —— 只要不撞真实网段即可
            "X-Forwarded-For": f"{xff_prefix}.{index // 250}.{index % 250 + 1}",
        }
