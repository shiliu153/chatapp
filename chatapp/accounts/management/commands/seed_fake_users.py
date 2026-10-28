"""开发与手测造数:批量创建「资料已完善 + 有已过审照片」的女号。

用法::

    python manage.py seed_fake_users                 # 默认 20 个
    python manage.py seed_fake_users --count 8
    python manage.py seed_fake_users --skip-im       # 不调腾讯 IM(离线环境)

设计要点:
    1. 号码从 ``13900000001`` 起按序分配,已存在的号码直接跳过 —— 幂等,可反复执行;
    2. 照片从 randomuser.me 拉取(免费人像图源),按序号命名后落库,不会重复上传;
    3. 造数会直调 IM 同步昵称与头像,不必等 Celery worker 起来。

关联文档:
    - 踩坑记录:docs/pitfalls/backend.md「管理命令(补漏)」
"""

import random
from datetime import date

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from im import client as im_client
from users.models import Photo, PhotoStatus, Preference, Profile, ProfileStatus, Tag

User = get_user_model()

PHONE_PREFIX = "139000000"   # 9 位;后 2 位按序号补足 11 位号码
PHONE_MAX = 99

NAMES = [
    "小雨", "诗涵", "子萱", "梦瑶", "思琪", "静怡", "婉婷", "语嫣", "晓彤", "可欣",
    "若曦", "佳琪", "cc", "月儿", "阿宁", "知夏", "糖糖", "竹子", "多多", "小满",
]

CITIES = [
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "南京", "重庆",
]

BIOS = [
    "喜欢猫咪和一切毛茸茸的东西",
    "周末要么在爬山,要么在家躺平",
    "美食探店爱好者,欢迎推荐好吃的",
    "会做饭,拿手菜是番茄牛腩",
    "爱看电影,偏爱悬疑和文艺片",
    "健身两年,力量区常驻选手",
    "摄影新手,喜欢拍城市夜景",
    "想找个人一起看展逛街",
    "咖啡续命,手冲入门中",
    "旅行过 12 个城市,下一站西北",
]

AVATAR_URL = "https://randomuser.me/api/portraits/women/{n}.jpg"


def _download(url: str) -> bytes:
    """下载头像图;超过 5MB(接口上限)或拿不到内容直接失败。"""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    if not resp.content or len(resp.content) > 5 * 1024 * 1024:
        raise CommandError(f"图片内容异常: {url}")
    return resp.content


class Command(BaseCommand):
    """批量创建手测用女号的 Django 管理命令。"""

    help = "建一批资料完善的女号(开发手测用),幂等可重复执行"

    def add_arguments(self, parser):
        """声明命令行参数。

        Args:
            parser: argparse 的参数解析器。
        """
        parser.add_argument("--count", type=int, default=20, help="要建的人数(默认 20)")
        parser.add_argument("--skip-im", action="store_true", help="跳过 IM 导入/资料同步")

    def handle(self, *args, **options):
        """执行造数:续编号码、逐个建号并补齐资料与照片。

        Args:
            *args: 位置参数,未使用。
            **options: 已解析的命令行参数(``count`` / ``skip_im``)。

        Raises:
            CommandError: ``--count`` 小于 1,或号码段已用完,或照片下载失败。
        """
        count = options["count"]
        if count < 1:
            raise CommandError("--count 至少为 1")

        # 号码按「已分配的最大序号 + 1」续编,不会与手工注册的号撞车
        last = (User.objects.filter(phone__startswith=PHONE_PREFIX)
                .order_by("-phone").values_list("phone", flat=True).first())
        start = int(last[len(PHONE_PREFIX):]) if last else 0
        if start + count > PHONE_MAX:
            raise CommandError(f"号码段 {PHONE_PREFIX}xxx 已用完,请先清理旧数据")

        tag_ids = list(Tag.objects.values_list("id", flat=True))
        created = 0
        skipped = 0
        for i in range(count):
            phone = f"{PHONE_PREFIX}{start + i + 1:02d}"
            if User.objects.filter(phone=phone).exists():
                skipped += 1
                continue
            try:
                user = User.objects.create_user(phone=phone)
                self._fill_profile(user, i, tag_ids)
            except Exception:
                # 照片下载失败等中断场景必须回滚,避免留下永远无人能滑的半截账号
                User.objects.filter(phone=phone).delete()
                raise
            if not options["skip_im"]:
                im_client.ensure_account(user.im_user_id, user.profile.nickname)
                im_client.set_profile_nick(user.im_user_id, user.profile.nickname)
                first = user.photos.first()
                if first:
                    im_client.set_profile_avatar(user.im_user_id, first.file.url)
            created += 1
            self.stdout.write(f"  {user.im_user_id} {phone} {user.profile.nickname}")

        if skipped:
            self.stdout.write(f"跳过已存在号码 {skipped} 个")
        self.stdout.write(self.style.SUCCESS(f"完成:新建 {created} 个资料完善的女号"))

    def _fill_profile(self, user, index, tag_ids):
        """为新建用户补齐资料、偏好与两张已过审照片。

        Args:
            user: 刚创建的用户。
            index: 该用户在本次批次中的序号,用于轮流取用昵称/城市/简介。
            tag_ids: 全量标签主键,从中随机挑 2~4 个挂到资料上。
        """
        birthday = self._random_birthday()
        profile = Profile.objects.create(
            user=user,
            nickname=f"{NAMES[index % len(NAMES)]}{user.id % 100:02d}",  # id 后缀消重名
            gender="female",
            birthday=birthday,
            city=CITIES[index % len(CITIES)],
            bio=BIOS[index % len(BIOS)],
            status=ProfileStatus.COMPLETE,
        )
        if tag_ids:
            profile.tags.set(random.sample(tag_ids, k=random.randint(2, 4)))
        Preference.objects.create(profile=profile, target_gender="male")
        for order in range(2):
            data = self._fetch_photo()
            photo = Photo(user=user, order=order, status=PhotoStatus.APPROVED,
                          bytes=len(data))
            photo.file.save(f"seed_{user.id}_{order}.jpg",
                            ContentFile(data), save=True)
        profile.refresh_status()

    def _fetch_photo(self):
        """下载一张头像图,失败时换一张重试。

        Returns:
            图片二进制内容。

        Raises:
            CommandError: 连续三次下载均失败。
        """
        # randomuser 偶发某张图 404,换一张重试
        last_error = None
        for _ in range(3):
            try:
                return _download(AVATAR_URL.format(n=random.randint(1, 99)))
            except Exception as exc:
                last_error = exc
        raise CommandError(f"头像下载失败: {last_error}")

    def _random_birthday(self):
        """随机造一个 18~45 岁的生日。

        年龄区间覆盖默认偏好(18~99)与常见自设区间;区间太窄会把号全部过滤掉。
        月/日必须**不晚于今天** —— 否则「今年的生日还没过」,``calculate_age`` 会算出
        age-1,抽到 age=18 时就造出 17 岁的账号(平台明令禁止)。2026-10-13 CI 实测红,
        概率约 2%/轮:1/28 抽到 18 × 71/336 抽到「晚于今天」的月日 × 3 个用户。

        Returns:
            一个能算出目标年龄的 ``date``。
        """
        # 18–45 覆盖默认偏好(18–99)和常见自设区间;太窄的偏好区间会把号全过滤掉
        age = random.randint(18, 45)
        # 与 calculate_age 同源:不能用 date.today()(那是**系统时区**,CI 跑在 UTC 上,
        # 跨过 UTC/CST 的午夜差一天时同样会算错一岁)
        today = timezone.localdate()
        # 月/日不得晚于今天,否则 calculate_age 会算出 age-1(详见上方说明)
        month = random.randint(1, today.month)
        day = random.randint(1, 28)          # 每月都有 28 号,不会 ValueError
        if month == today.month:
            day = random.randint(1, min(today.day, 28))
        return date(today.year - age, month, day)
