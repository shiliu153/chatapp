"""在规模数据上量候选池与广场列表的延迟、并打印执行计划。

用法::

    python manage.py scale_probe --offsets 0,1000,10000
    python manage.py scale_probe --repeat 5 --explain

设计要点:
    1. 直接跑**线上同款查询集**(``candidate_pool_queryset`` / ``Post`` 的默认排序),
       不是另写一条 SQL —— 否则测的不是真实路径;
    2. 每个点重复多次取中位数,单次测量在共享机器上抖动太大;
    3. ``--explain`` 打印 MySQL 执行计划,用来确认「走没走索引」而不是只看耗时。
"""

import statistics
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from discovery.services import candidate_pool_queryset
from feed.models import Post
from feed.services import page_visible_posts, visible_base
from users.models import Photo, Preference, Profile, ProfileStatus


def _median_ms(fn, repeat: int) -> float:
    """重复执行取中位耗时。

    Args:
        fn: 无参可调用对象。
        repeat: 重复次数。

    Returns:
        中位耗时(毫秒)。
    """
    samples = []
    for _ in range(max(1, repeat)):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 2)


class Command(BaseCommand):
    """规模数据探针。"""

    help = "量候选池/广场列表在规模数据下的延迟与执行计划"

    def add_arguments(self, parser):
        """声明命令行参数。

        Args:
            parser: argparse 的参数解析器。
        """
        parser.add_argument("--offsets", default="0,100,1000,10000",
                            help="广场列表要测的 offset,逗号分隔")
        parser.add_argument("--repeat", type=int, default=5, help="每个点重复次数")
        parser.add_argument("--explain", action="store_true", help="打印执行计划")
        parser.add_argument("--limit", type=int, default=10, help="每页条数")

    def handle(self, *args, **options):
        """执行探测并打印表格。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Raises:
            CommandError: 没有可用的已完善资料账号。
        """
        repeat = options["repeat"]
        page = options["limit"]
        profile = (Profile.objects.filter(status=ProfileStatus.COMPLETE)
                   .select_related("user").first())
        if profile is None:
            raise CommandError("没有资料完善的账号,先跑 seed_scale_users")
        preference, _ = Preference.objects.get_or_create(profile=profile)

        self.stdout.write("| 数据量 | 用户 {} / 资料 {} / 照片 {} / 动态 {} |".format(
            Profile.objects.count(), Profile.objects.count(),
            Photo.objects.count(), Post.objects.count()))

        cold = _median_ms(lambda: list(candidate_pool_queryset(profile.user, preference, 200)),
                          repeat)
        self.stdout.write(f"| 候选池(200 条,冷) | {cold} ms |")

        if options["explain"]:
            plan = candidate_pool_queryset(profile.user, preference, 200).explain()
            self.stdout.write("候选池执行计划:\n" + str(plan))

        self.stdout.write("| 广场 offset | 耗时 |")
        self.stdout.write("|---|---|")
        # 用线上同款两段式查询(取当页 id → 只对这几条聚合),不是裸 Post 查询。
        offsets = []
        for raw in options["offsets"].split(","):
            try:
                offsets.append(int(raw))
            except ValueError:
                continue
        for offset in offsets:
            cost = _median_ms(
                lambda o=offset: page_visible_posts(profile.user, o, page), repeat)
            self.stdout.write(f"| {offset} | {cost} ms |")

        if options["explain"] and offsets:
            deepest = max(offsets)
            plan = (visible_base(profile.user)
                    .order_by("-created_at", "-id")[deepest:deepest + page].explain())
            self.stdout.write("广场取当页 id 的执行计划:\n" + str(plan))
            self.stdout.write(f"数据库:{connection.vendor}")
