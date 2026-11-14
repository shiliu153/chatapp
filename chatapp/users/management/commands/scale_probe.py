"""在规模数据上量候选池、列表接口的延迟、并打印执行计划。

用法::

    python manage.py scale_probe --offsets 0,1000,10000
    python manage.py scale_probe --repeat 5 --explain

设计要点:
    1. 直接跑**线上同款查询集**(``candidate_pool_queryset`` / ``Post`` 的默认排序 /
       ``likes_received_queryset`` / ``visits_received_queryset`` / ``Match`` 的 OR 查询),
       不是另写一条 SQL —— 否则测的不是真实路径;
    2. 每个点重复多次取中位数,单次测量在共享机器上抖动太大;
    3. ``--explain`` 打印 MySQL 执行计划(``type``/``key``/``rows``/``Extra``),
       用来确认「走没走索引」而不是只看耗时。``type=ALL`` 就是全表扫。

文件信息:
    文件名称          users/management/commands/scale_probe.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import statistics
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Q

from discovery.models import Match
from discovery.services import candidate_pool_queryset, likes_received_queryset, visits_received_queryset
from feed.models import Post
from feed.services import page_visible_posts, visible_base
from users.models import Photo, Preference, Profile, ProfileStatus


def _median_ms(fn, repeat: int) -> float:
    """重复执行取中位耗时。

    参数说明:
        fn: 无参可调用对象,内部完成一次真实查询。
        repeat: 重复次数。

    返回参数:
        中位耗时(毫秒),保留两位小数。

    使用示例:
        ``_median_ms(lambda: list(candidate_pool_queryset(user, preference, 200)), 5)``

    备注信息:
        次数下限取 1;偶数次采样时 ``statistics.median`` 取两数均值,
        共享机器上单次测量抖动大,故用中位数而非均值。
    """
    samples = []
    for _ in range(max(1, repeat)):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 2)


def _explain_rows(queryset) -> list[str]:
    """取查询集的传统 EXPLAIN(每行一个表)。

    参数说明:
        queryset: 要分析的查询集。

    返回参数:
        ``table/type/key/rows/Extra`` 组成的可读行列表。

    使用示例:
        ``_explain_rows(likes_received_queryset(profile.user))``

    备注信息:
        只支持 MySQL 的传统 ``EXPLAIN`` 输出;``type=ALL`` 表示全表扫,
        列名取自 ``cursor.description``,与驱动返回顺序解耦。
    """
    sql, params = queryset.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN " + sql, params)
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
    lines = []
    for row in rows:
        record = dict(zip(columns, row))
        lines.append("    table={} type={} key={} rows={} Extra={}".format(
            record.get("table"), record.get("type"), record.get("key"),
            record.get("rows"), record.get("Extra")))
    return lines


class Command(BaseCommand):
    """规模数据探针。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py scale_probe --offsets 0,1000 --repeat 3``

    备注信息:
        ``help`` 的语义是「量候选池与广场列表在规模数据下的延迟与执行计划」。
        只读探测:不写库、不造数据,造数用 ``seed_scale_users``。
    """

    help = "量候选池/广场列表在规模数据下的延迟与执行计划"

    def add_arguments(self, parser):
        """声明命令行参数。

        参数说明:
            parser: argparse 的参数解析器。

        返回参数:
            无返回值。

        使用示例:
            ``self.add_arguments(parser)``

        备注信息:
            定义 ``--offsets``(广场列表要测的 offset,逗号分隔)、``--repeat``、
            ``--explain``、``--limit`` 与 ``--phone`` 五个参数。
        """
        parser.add_argument("--offsets", default="0,100,1000,10000",
                            help="广场列表要测的 offset,逗号分隔")
        parser.add_argument("--repeat", type=int, default=5, help="每个点重复次数")
        parser.add_argument("--explain", action="store_true", help="打印执行计划")
        parser.add_argument("--limit", type=int, default=10, help="每页条数")
        parser.add_argument("--phone", default="", help="指定探针账号的手机号(默认取第一个完善资料的人)")

    def handle(self, *args, **options):
        """执行探测并打印表格。

        参数说明:
            *args: 位置参数(未使用)。
            **options: 命令行选项,含 ``offsets``/``repeat``/``explain``/``limit``/``phone``。

        返回参数:
            无返回值;探测结果以 Markdown 表格形式写到 stdout。

        使用示例:
            ``python manage.py scale_probe --repeat 5 --explain --phone 13800000000``

        备注信息:
            探针账号必须是资料完善(``ProfileStatus.COMPLETE``)的人,找不到时抛
            ``CommandError``;偏好记录缺失会自动建一条;``--offsets`` 里的非数字项直接跳过。
        """
        repeat = options["repeat"]
        page = options["limit"]
        if options["phone"]:
            profile = (Profile.objects.filter(status=ProfileStatus.COMPLETE,
                                              user__phone=options["phone"])
                       .select_related("user").first())
        else:
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

        # 三个「社交列表」接口(A-2 的三条索引就是为它们建的)
        me = profile.user
        lists = {
            "喜欢我的人": lambda: list(likes_received_queryset(me)[:20]),
            "谁看过我": lambda: list(visits_received_queryset(me)[:20]),
            "配对列表": lambda: list(Match.objects.filter(
                Q(user_a=me) | Q(user_b=me), unmatched_at__isnull=True)
                .order_by("-created_at")[:20]),
        }
        self.stdout.write("| 列表接口 | 耗时 |")
        self.stdout.write("|---|---|")
        for name, fn in lists.items():
            self.stdout.write(f"| {name} | {_median_ms(fn, repeat)} ms |")

        if options["explain"]:
            deepest = max(offsets) if offsets else 0
            plan = (visible_base(profile.user)
                    .order_by("-created_at", "-id")[deepest:deepest + page].explain())
            self.stdout.write("广场取当页 id 的执行计划:\n" + str(plan))
            self.stdout.write(f"数据库:{connection.vendor}")

            explain_querysets = {
                "喜欢我的人": likes_received_queryset(me),
                "谁看过我": visits_received_queryset(me),
                "配对列表": Match.objects.filter(
                    Q(user_a=me) | Q(user_b=me), unmatched_at__isnull=True)
                .order_by("-created_at"),
            }
            for name, queryset in explain_querysets.items():
                self.stdout.write(f"{name}执行计划:")
                for line in _explain_rows(queryset):
                    self.stdout.write(line)
