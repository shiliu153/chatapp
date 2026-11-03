"""造规模数据:批量创建用户 + 资料 + 照片 + 动态,用于容量与索引验证。

用法::

    python manage.py seed_scale_users --count 100000 --posts 500000   # 服务器上跑
    python manage.py seed_scale_users --count 20000 --dry-run
    python manage.py seed_scale_users --count 20000 --clean

设计要点:
    1. **幂等**:号码固定从 ``19900000000`` 起顺序分配,``ignore_conflicts`` 跳过已存在,
       重复执行不会产生重复账号;
    2. **批量写**:全程 ``bulk_create``(绕开 ORM 的逐条 save 与信号),默认每批 1000 条;
    3. **可清理**:``--clean`` 只删这个号段内的账号,级联带走资料/照片/动态,
       不会误伤真实数据;
    4. **不造聊天消息**:``im_message`` 在独立的 ``chatapp_im`` 库(imserver 自建),
        Django 没有它的连接;消息量用 ``imserver/scripts/bench_ws.py`` 现场产生。

关联文档:
    - 压测入口:perf/README.md
"""

import random
import time
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from feed.models import Post
from users.models import Photo, PhotoStatus, Profile, ProfileStatus

User = get_user_model()

PHONE_BASE = 19_900_000_000        # 199 号段,11 位;向后顺序分配
PHONE_MAX = 1_000_000              # 号段容量,防止 --count 越界撞到真实号码

CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "南京", "重庆"]
BIOS = [
    "规模测试账号", "喜欢爬山和摄影", "咖啡续命", "周末看展", "健身两年",
]


class Command(BaseCommand):
    """批量造规模数据的 Django 管理命令。"""

    help = "造规模数据(用户/资料/照片/动态),幂等、可清理"

    def add_arguments(self, parser):
        """声明命令行参数。

        Args:
            parser: argparse 的参数解析器。
        """
        parser.add_argument("--count", type=int, default=10_000, help="用户数")
        parser.add_argument("--posts", type=int, default=0, help="动态总数(0 = 不造)")
        parser.add_argument("--batch", type=int, default=1_000, help="每批写入条数")
        parser.add_argument("--clean", action="store_true", help="删除该号段的全部数据")
        parser.add_argument("--dry-run", action="store_true", help="只打印计划,不写库")

    def handle(self, *args, **options):
        """执行造数或清理。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Raises:
            CommandError: 数量非法或号段越界。
        """
        count = options["count"]
        batch = max(100, options["batch"])
        if count <= 0 or count > PHONE_MAX:
            raise CommandError(f"--count 必须在 1..{PHONE_MAX} 之间")

        if options["clean"]:
            self._clean(count, batch, options["dry_run"])
            return

        started = time.perf_counter()
        if options["dry_run"]:
            self.stdout.write(f"将创建 {count} 用户 + {count} 资料 + {count} 照片"
                              f" + {options['posts']} 动态(号段 {PHONE_BASE}..)")
            return

        user_ids = self._create_users(count, batch)
        self._create_profiles(user_ids, batch)
        self._create_photos(user_ids, batch)
        if options["posts"]:
            self._create_posts(user_ids, options["posts"], batch)
        self.stdout.write(self.style.SUCCESS(
            f"完成:用户 {len(user_ids)},动态 {options['posts']},"
            f"耗时 {time.perf_counter() - started:.1f}s"))

    def _create_users(self, count: int, batch: int) -> list[int]:
        """批量创建账号并返回它们的 id。

        Args:
            count: 账号数量。
            batch: 每批条数。

        Returns:
            新建或已存在的账号 id 列表。
        """
        phones = [str(PHONE_BASE + i) for i in range(count)]
        for start in range(0, count, batch):
            chunk = [User(phone=phone) for phone in phones[start:start + batch]]
            User.objects.bulk_create(chunk, ignore_conflicts=True, batch_size=batch)
        ids = []
        for start in range(0, count, batch):
            ids.extend(User.objects.filter(phone__in=phones[start:start + batch])
                       .values_list("id", flat=True))
        self.stdout.write(f"账号:{len(ids)}")
        return ids

    def _create_profiles(self, user_ids: list[int], batch: int) -> None:
        """为每个账号建一条资料(资料完善,进候选池)。

        Args:
            user_ids: 账号 id 列表。
            batch: 每批条数。
        """
        existing = set(Profile.objects.filter(user_id__in=user_ids)
                       .values_list("user_id", flat=True))
        today = date.today()
        rows = []
        for index, user_id in enumerate(user_ids):
            if user_id in existing:
                continue
            rows.append(Profile(
                user_id=user_id,
                nickname=f"规模{index % 100000}",
                gender=random.choice(["male", "female"]),
                birthday=today - timedelta(days=random.randint(18 * 365, 40 * 365)),
                city=random.choice(CITIES),
                bio=random.choice(BIOS),
                status=ProfileStatus.COMPLETE,
            ))
        Profile.objects.bulk_create(rows, batch_size=batch)
        self.stdout.write(f"资料:{len(rows)}")

    def _create_photos(self, user_ids: list[int], batch: int) -> None:
        """给每个账号加一张已过审照片(候选池的准入条件)。

        Args:
            user_ids: 账号 id 列表。
            batch: 每批条数。
        """
        with_photo = set(Photo.objects.filter(user_id__in=user_ids, status=PhotoStatus.APPROVED)
                         .values_list("user_id", flat=True))
        rows = [Photo(user_id=user_id, file=f"photos/scale/{user_id}.jpg", bytes=1024,
                      order=0, status=PhotoStatus.APPROVED)
                for user_id in user_ids if user_id not in with_photo]
        Photo.objects.bulk_create(rows, batch_size=batch)
        self.stdout.write(f"照片:{len(rows)}")

    def _create_posts(self, user_ids: list[int], total: int, batch: int) -> None:
        """按账号轮转分配动态。

        Args:
            user_ids: 账号 id 列表。
            total: 动态总数。
            batch: 每批条数。
        """
        if not user_ids:
            return
        rows = []
        for index in range(total):
            rows.append(Post(author_id=user_ids[index % len(user_ids)],
                             text=f"规模动态 {index}"))
            if len(rows) >= batch:
                Post.objects.bulk_create(rows, batch_size=batch)
                rows.clear()
        if rows:
            Post.objects.bulk_create(rows, batch_size=batch)
        self.stdout.write(f"动态:{total}")

    def _clean(self, count: int, batch: int, dry_run: bool) -> None:
        """删除号段内的账号及其级联数据。

        Args:
            count: 号段内的账号数量。
            batch: 每批删除条数。
            dry_run: 只统计不删除。
        """
        phones = [str(PHONE_BASE + i) for i in range(count)]
        total = 0
        for start in range(0, count, batch):
            ids = list(User.objects.filter(phone__in=phones[start:start + batch])
                       .values_list("id", flat=True))
            total += len(ids)
            if dry_run or not ids:
                continue
            with transaction.atomic():
                User.objects.filter(id__in=ids).delete()
        action = "将删除" if dry_run else "已删除"
        self.stdout.write(self.style.SUCCESS(f"{action} {total} 个账号(含级联资料/照片/动态)"))
