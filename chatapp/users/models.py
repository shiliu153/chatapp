"""用户资料、照片与择偶偏好。

设计要点:
    1. **账号与资料分离**:``accounts.User`` 只管登录标识(手机号),本模块的
       ``Profile`` 管对外展示的资料,一对一关联、懒创建(见 ``services.get_profile``);
    2. **「资料完善」的判定口径**在 ``Profile.missing_fields``:昵称、性别、生日、城市、
       简介均非空且至少有一张已过审照片;候选池只收 ``status=COMPLETE`` 的人;
    3. 封禁状态与完善状态共用 ``Profile.status`` 一个字段,``refresh_status`` 会跳过
       封禁状态,避免审核动作把封禁覆盖掉。

关联文档:
    - 接口契约:docs/api/users.md
    - 踩坑记录:docs/pitfalls/backend.md「账号注销」
"""

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

SHUFFLE_KEY_UPPER = 1_000_000_000


def random_shuffle_key():
    """生成候选池的随机排序键。

    用 ``secrets`` 而不是 ``random``:这个值会长期落库并决定「谁先被看到」,
    虽然不涉及资金,但也不该是可预测的伪随机序列。

    Returns:
        ``[0, 10^9)`` 区间内的整数。
    """
    return secrets.randbelow(SHUFFLE_KEY_UPPER)


def calculate_age(birthday, today=None):
    """按「今年生日是否已过」计算周岁。

    不用「天数差 / 365」的近似算法:那种写法在闰年与生日当天都会差一岁,
    而本项目要用年龄做候选过滤与未成年人拦截,差一岁是合规问题。

    Args:
        birthday: 出生日期。
        today: 参照日期;``None`` 表示取本地时区的今天(便于测试注入)。

    Returns:
        周岁整数。
    """
    today = today or timezone.localdate()
    return today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))


def shift_years(day, years):
    """把日期往前推 N 年;2 月 29 日退化成 2 月 28 日。

    Args:
        day: 起始日期。
        years: 往前推的年数。

    Returns:
        推后得到的日期。
    """
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def birthday_bounds(age_min, age_max, today=None):
    """把年龄区间换算成生日区间:birthday <= upper 且 birthday > lower。

    推导:age >= age_min ⇔ 生日不晚于"今天减 age_min 年";
         age <= age_max ⇔ 生日晚于"今天减 (age_max+1) 年"。

    Args:
        age_min: 年龄下限(含)。
        age_max: 年龄上限(含)。
        today: 参照日期;``None`` 表示取本地时区的今天。

    Returns:
        ``(upper, lower)`` 二元组,对应上面两个比较边界。
    """
    today = today or timezone.localdate()
    return shift_years(today, age_min), shift_years(today, age_max + 1)


class Gender(models.TextChoices):
    """性别取值。"""

    MALE = "male", "男"
    FEMALE = "female", "女"


class ProfileStatus(models.TextChoices):
    """资料状态:完善度与封禁共用同一字段。"""

    INCOMPLETE = "incomplete", "未完善"
    COMPLETE = "complete", "已完善"
    BANNED_LIGHT = "banned_light", "轻度封禁"
    BANNED_HEAVY = "banned_heavy", "重度封禁"


class PhotoStatus(models.TextChoices):
    """照片审核状态。"""

    PENDING = "pending", "待审核"
    APPROVED = "approved", "已通过"
    REJECTED = "rejected", "已驳回"


class Tag(models.Model):
    """兴趣标签(标签池由数据迁移写入,共 12 个)。"""

    name = models.CharField("名称", max_length=20, unique=True)
    icon = models.CharField("图标", max_length=50, blank=True)

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            标签名称。
        """
        return self.name


class Profile(models.Model):
    """用户对外展示的资料。

    Attributes:
        status: 完善度与封禁共用;封禁取值见 ``BANNED_STATUSES``。
        ban_reason: 封禁原因,由审核台写入并在封禁提示中展示。
    """

    BANNED_STATUSES = (ProfileStatus.BANNED_LIGHT, ProfileStatus.BANNED_HEAVY)

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    nickname = models.CharField("昵称", max_length=20, blank=True)
    gender = models.CharField("性别", max_length=10, choices=Gender.choices, blank=True)
    birthday = models.DateField("生日", null=True, blank=True)
    city = models.CharField("城市", max_length=50, blank=True)
    bio = models.CharField("简介", max_length=200, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="profiles")
    status = models.CharField("状态", max_length=20, choices=ProfileStatus.choices,
                              default=ProfileStatus.INCOMPLETE)
    ban_reason = models.CharField("封禁原因", max_length=200, blank=True)
    # 候选池的预计算随机列:候选接口按它走索引取池,替代全表 ORDER BY RAND()。
    # 由 ``manage.py refresh_shuffle_keys`` 定期轮换(见该命令的 docstring)。
    shuffle_key = models.PositiveIntegerField("随机排序键", default=random_shuffle_key,
                                              db_index=True)

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``昵称(账号 id)``;昵称为空时用 ``?`` 占位。
        """
        return f"{self.nickname or '?'}({self.user_id})"

    @property
    def age(self):
        """由生日换算出的周岁。

        Returns:
            周岁;未填生日时返回 ``None``。
        """
        return calculate_age(self.birthday) if self.birthday else None

    def missing_fields(self):
        """列出「资料完善」还缺哪些项。

        Returns:
            缺失字段名列表(``nickname`` / ``gender`` / ``birthday`` / ``city`` /
            ``bio`` / ``photos``);空列表表示资料已完善。
        """
        missing = []
        if not self.nickname:
            missing.append("nickname")
        if not self.gender:
            missing.append("gender")
        if not self.birthday:
            missing.append("birthday")
        if not self.city:
            missing.append("city")
        if not self.bio:
            missing.append("bio")
        if not self.user.photos.filter(status=PhotoStatus.APPROVED).exists():
            missing.append("photos")
        return missing

    @property
    def is_banned(self):
        """当前是否处于任一封禁状态。

        Returns:
            轻封禁或重封禁时为 ``True``。
        """
        return self.status in self.BANNED_STATUSES

    def refresh_status(self):
        """在 未完善/已完善 之间流转;封禁状态不被覆盖(M1b/M3 靠它兜底)。"""
        if self.status in self.BANNED_STATUSES:
            return
        new_status = ProfileStatus.COMPLETE if not self.missing_fields() else ProfileStatus.INCOMPLETE
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=["status"])


class Photo(models.Model):
    """用户相册照片。

    Attributes:
        order: 相册内排序;首张(``order`` 最小)同时用作 IM 头像来源。
        reviewed_by: 审核人;由 admin 或 ops 审核台写入,用于审计。
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="photos")
    file = models.ImageField("图片", upload_to="photos/%Y/%m/")
    # 重编码后的文件字节数:存储配额按它求和,不必每次上传都去 stat 磁盘(M7)
    bytes = models.PositiveIntegerField("字节数", default=0)
    order = models.PositiveSmallIntegerField("排序", default=0)
    status = models.CharField("审核状态", max_length=10, choices=PhotoStatus.choices,
                              default=PhotoStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="photos_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``photo#主键(账号 id)``。
        """
        return f"photo#{self.pk}({self.user_id})"


class Preference(models.Model):
    """择偶偏好(「想找的人」),与资料一对一。"""

    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="preference")
    target_gender = models.CharField("想找的性别", max_length=10, choices=Gender.choices,
                                     null=True, blank=True)   # 空 = 不限
    age_min = models.PositiveSmallIntegerField("最小年龄", default=18)
    age_max = models.PositiveSmallIntegerField("最大年龄", default=99)
    city = models.CharField("城市", max_length=50, blank=True)

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``preference(资料 id)``。
        """
        return f"preference({self.profile_id})"
