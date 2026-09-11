from django.conf import settings
from django.db import models
from django.utils import timezone


def calculate_age(birthday, today=None):
    today = today or timezone.localdate()
    return today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))


def shift_years(day, years):
    """把日期往前推 N 年;2 月 29 日退化成 2 月 28 日。"""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def birthday_bounds(age_min, age_max, today=None):
    """把年龄区间换算成生日区间:birthday <= upper 且 birthday > lower。

    推导:age >= age_min ⇔ 生日不晚于"今天减 age_min 年";
         age <= age_max ⇔ 生日晚于"今天减 (age_max+1) 年"。
    """
    today = today or timezone.localdate()
    return shift_years(today, age_min), shift_years(today, age_max + 1)


class Gender(models.TextChoices):
    MALE = "male", "男"
    FEMALE = "female", "女"


class ProfileStatus(models.TextChoices):
    INCOMPLETE = "incomplete", "未完善"
    COMPLETE = "complete", "已完善"
    BANNED_LIGHT = "banned_light", "轻度封禁"
    BANNED_HEAVY = "banned_heavy", "重度封禁"


class PhotoStatus(models.TextChoices):
    PENDING = "pending", "待审核"
    APPROVED = "approved", "已通过"
    REJECTED = "rejected", "已驳回"


class Tag(models.Model):
    name = models.CharField("名称", max_length=20, unique=True)
    icon = models.CharField("图标", max_length=50, blank=True)

    def __str__(self):
        return self.name


class Profile(models.Model):
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

    def __str__(self):
        return f"{self.nickname or '?'}({self.user_id})"

    @property
    def age(self):
        return calculate_age(self.birthday) if self.birthday else None

    def missing_fields(self):
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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="photos")
    file = models.ImageField("图片", upload_to="photos/%Y/%m/")
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
        return f"photo#{self.pk}({self.user_id})"


class Preference(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="preference")
    target_gender = models.CharField("想找的性别", max_length=10, choices=Gender.choices,
                                     null=True, blank=True)   # 空 = 不限
    age_min = models.PositiveSmallIntegerField("最小年龄", default=18)
    age_max = models.PositiveSmallIntegerField("最大年龄", default=99)
    city = models.CharField("城市", max_length=50, blank=True)

    def __str__(self):
        return f"preference({self.profile_id})"
