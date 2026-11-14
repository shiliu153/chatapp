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

文件信息:
    文件名称          users/models.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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

    参数说明:
        无。

    返回参数:
        ``[0, 10^9)`` 区间内的整数。

    使用示例:
        ``key = random_shuffle_key()``

    备注信息:
        作为 ``Profile.shuffle_key`` 的字段默认值调用,由 ``manage.py refresh_shuffle_keys``
        定期轮换;``SHUFFLE_KEY_UPPER`` 是开区间上限,改它会改变既有数据的排序分布。
    """
    return secrets.randbelow(SHUFFLE_KEY_UPPER)


def calculate_age(birthday, today=None):
    """按「今年生日是否已过」计算周岁。

    不用「天数差 / 365」的近似算法:那种写法在闰年与生日当天都会差一岁,
    而本项目要用年龄做候选过滤与未成年人拦截,差一岁是合规问题。

    参数说明:
        birthday: 出生日期。
        today: 参照日期;``None`` 表示取本地时区的今天(便于测试注入)。

    返回参数:
        周岁整数。

    使用示例:
        ``calculate_age(date(2000, 5, 1))``

    备注信息:
        结果为「已过生日 → 满岁」的严格周岁;``birthday`` 为未来日期时返回负数,
        调用方需自行拦截(注册路径由 ``ProfileUpdateSerializer.validate_birthday`` 拦)。
    """
    today = today or timezone.localdate()
    return today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))


def shift_years(day, years):
    """把日期往前推 N 年;2 月 29 日退化成 2 月 28 日。

    参数说明:
        day: 起始日期。
        years: 往前推的年数。

    返回参数:
        推后得到的日期。

    使用示例:
        ``shift_years(date(2026, 2, 29 - 1), 18)``

    备注信息:
        只在目标年没有 2 月 29 日时走 ``ValueError`` 分支退化为 28 日;
        用于把年龄区间换算成生日区间(见 ``birthday_bounds``)。
    """
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def birthday_bounds(age_min, age_max, today=None):
    """把年龄区间换算成生日区间:birthday <= upper 且 birthday > lower。

    推导:age >= age_min ⇔ 生日不晚于"今天减 age_min 年";
         age <= age_max ⇔ 生日晚于"今天减 (age_max+1) 年"。

    参数说明:
        age_min: 年龄下限(含)。
        age_max: 年龄上限(含)。
        today: 参照日期;``None`` 表示取本地时区的今天。

    返回参数:
        ``(upper, lower)`` 二元组,对应上面两个比较边界。

    使用示例:
        ``upper, lower = birthday_bounds(18, 30)``

    备注信息:
        下界是**开区间**(``birthday__gt=lower``),上界是闭区间(``birthday__lte=upper``);
        两块区间都按周岁口径换算,闰年边界由 ``shift_years`` 处理。
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
    """兴趣标签(标签池由数据迁移写入,共 12 个)。

    参数说明:
        按字段关键字传参,常用 ``name``(名称,唯一)与 ``icon``(图标,可空);
        字段含义见各行内注释。

    返回参数:
        构造出的 ``Tag`` 实例。

    使用示例:
        ``Tag(name="露营", icon="camping")``

    备注信息:
        标签池只由数据迁移写入,运行时不新增;``name`` 有唯一约束,
        重复创建会抛 ``IntegrityError``。
    """

    name = models.CharField("名称", max_length=20, unique=True)
    icon = models.CharField("图标", max_length=50, blank=True)

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            标签名称。

        使用示例:
            ``str(tag)``

        备注信息:
            只返回 ``name``,不含图标与主键。
        """
        return self.name


class Profile(models.Model):
    """用户对外展示的资料。

    Attributes:
        status: 完善度与封禁共用;封禁取值见 ``BANNED_STATUSES``。
        ban_reason: 封禁原因,由审核台写入并在封禁提示中展示。

    参数说明:
        按字段关键字传参,常用 ``user``(一对一账号)与 ``nickname``;
        其余字段(性别、生日、城市、简介、标签、状态、随机键、隐身开关)含义见行内注释。

    返回参数:
        构造出的 ``Profile`` 实例。

    使用示例:
        ``Profile.objects.get_or_create(user=user)``

    备注信息:
        正常路径**不要**直接 ``Profile.objects.create`` —— 资料是懒创建的,
        统一走 ``services.get_profile``(它还会补建 ``Preference`` 并做请求内记忆)。
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
    # 隐身浏览:开启后自己的访问不写进任何人的访客列表(见 services.record_profile_view)
    visits_hidden = models.BooleanField("隐身浏览", default=False)

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``昵称(账号 id)``;昵称为空时用 ``?`` 占位。

        使用示例:
            ``str(profile)``

        备注信息:
            括号里是**账号**主键 ``user_id``,不是资料主键 ``pk``。
        """
        return f"{self.nickname or '?'}({self.user_id})"

    @property
    def age(self):
        """由生日换算出的周岁。

        参数说明:
            无。

        返回参数:
            周岁;未填生日时返回 ``None``。

        使用示例:
            ``profile.age``

        备注信息:
            每次访问都现场计算,不落库;序列化器直接读这个属性。
        """
        return calculate_age(self.birthday) if self.birthday else None

    def missing_fields(self):
        """列出「资料完善」还缺哪些项。

        参数说明:
            无。

        返回参数:
            缺失字段名列表(``nickname`` / ``gender`` / ``birthday`` / ``city`` /
            ``bio`` / ``photos``);空列表表示资料已完善。

        使用示例:
            ``profile.missing_fields()``

        备注信息:
            ``photos`` 这一项要查一次 ``user.photos``(已过审照片是否存在),
            批量场景不要逐条调用。
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

        参数说明:
            无。

        返回参数:
            轻封禁或重封禁时为 ``True``。

        使用示例:
            ``profile.is_banned``

        备注信息:
            只读属性,判断依据是 ``status`` 是否落在 ``BANNED_STATUSES`` 内。
        """
        return self.status in self.BANNED_STATUSES

    def refresh_status(self):
        """在 未完善/已完善 之间流转;封禁状态不被覆盖(M1b/M3 靠它兜底)。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``profile.refresh_status()``

        备注信息:
            状态真变化时才 ``save(update_fields=["status"])``;调用点在照片上传/删除与
            ``services.review_photos``,资料语音刻意不参与该判定。
        """
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

    参数说明:
        按字段关键字传参,常用 ``user``、``file``(图片)与 ``bytes``(重编码后字节数);
        其余字段(排序、审核状态、审核人、审核时间、创建时间)含义见行内注释。

    返回参数:
        构造出的 ``Photo`` 实例。

    使用示例:
        ``Photo.objects.create(user=user, file=ContentFile(data, name=name))``

    备注信息:
        上传必须走 ``users.views.upload_photo``:配额校验、EXIF 剥离与重编码都在那里,
        直接建行会绕过存储配额与图片安全处理。
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
        indexes = [
            # 「有已过审照片的人」子查询:Photo.objects.filter(status=APPROVED).values("user_id")。
            # 候选池 / 喜欢我的人 / 访客三处共用它,缺索引时每次都是全表扫(审查 N-4)。
            models.Index(fields=["status", "user_id"], name="idx_photo_status_user"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``photo#主键(账号 id)``。

        使用示例:
            ``str(photo)``

        备注信息:
            括号里是账号主键 ``user_id``,与本行主键 ``pk`` 不同。
        """
        return f"photo#{self.pk}({self.user_id})"


class Preference(models.Model):
    """择偶偏好(「想找的人」),与资料一对一。

    参数说明:
        按字段关键字传参,``profile`` 为关联资料;年龄区间与目标性别的含义见行内注释。

    返回参数:
        构造出的 ``Preference`` 实例。

    使用示例:
        ``Preference.objects.get_or_create(profile=profile)``

    备注信息:
        由 ``services.get_profile`` 与资料一起懒创建,并挂到 ``profile.preference``
        反向缓存上,避免序列化时多打一条 SQL。
    """

    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="preference")
    target_gender = models.CharField("想找的性别", max_length=10, choices=Gender.choices,
                                     null=True, blank=True)   # 空 = 不限
    age_min = models.PositiveSmallIntegerField("最小年龄", default=18)
    age_max = models.PositiveSmallIntegerField("最大年龄", default=99)
    city = models.CharField("城市", max_length=50, blank=True)

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``preference(资料 id)``。

        使用示例:
            ``str(preference)``

        备注信息:
            括号里是 ``profile_id``(资料主键),不是账号 id。
        """
        return f"preference({self.profile_id})"

class ProfileVoice(models.Model):
    """资料语音自我介绍:一人一条,重复上传即覆盖(批次 R)。

    设计要点:
        1. **不进「资料完善」判定**:``Profile.missing_fields`` 不看它,老用户不会因为
           没录语音就掉回 ``incomplete``;
        2. 时长上限由视图保证(≤30 秒),这里只存 ``ffprobe`` 实测值,不信客户端声明;
        3. 文件与聊天语音同源:``im.voice.normalize`` 统一转成 m4a/AAC,播放兼容性由
           转码层负责,本表不关心原始格式;
        4. ``bytes`` 计入账号存储配额的第五类(见 ``config.storage.usage_bytes``);
        5. **对外地址不签名**:语音与照片同口径是**公开**媒体(``/media/voices/`` 由 nginx
           裸静态直出),所以序列化器直接用 DRF 的绝对 URL,不做「签了名却没人验」的样子货。

    Attributes:
        duration_ms: ``ffprobe`` 实测时长(毫秒),对外原样返回。
        bytes: 转码后文件字节数,配额按它求和。

    参数说明:
        按字段关键字传参,常用 ``profile``、``file``、``duration_ms`` 与 ``bytes``;
        时间戳字段由 ``auto_now_add`` / ``auto_now`` 自动维护。

    返回参数:
        构造出的 ``ProfileVoice`` 实例。

    使用示例:
        ``ProfileVoice(profile=profile)``

    备注信息:
        写入路径只有 ``users.views.my_voice``:先转码、再校验时长、最后查配额,
        顺序调换会留下没有数据库行的孤儿文件。
    """

    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="voice")
    file = models.FileField("语音", upload_to="voices/%Y/%m/")
    duration_ms = models.PositiveIntegerField("时长(毫秒)")
    bytes = models.PositiveIntegerField("字节数")
    created_at = models.DateTimeField("首次上传", auto_now_add=True)
    updated_at = models.DateTimeField("最近更新", auto_now=True)

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``profile_voice#主键(资料 id)``。

        使用示例:
            ``str(record)``

        备注信息:
            括号里是 ``profile_id``(资料主键),不是账号 id。
        """
        return f"profile_voice#{self.pk}(profile={self.profile_id})"


class ProfileVisit(models.Model):
    """一次「谁看过我」的访问记录。

    设计要点:
        1. **每人一行**:``(viewer, owner)`` 唯一,重复访问只刷新 ``last_at``,
           列表因此天然不会出现同一个人的多行;
        2. 写入按 30 分钟窗口节流(见 ``services.record_profile_view``),所以
           ``last_at`` 的精度是 30 分钟,不是「最后一次点击」的精确时刻;
        3. 保留期 90 天,由 ``manage.py purge_profile_visits`` 清理。

    Attributes:
        last_at: 最近一次访问时间;列表按它倒序。

    参数说明:
        按字段关键字传参,``viewer`` 为浏览者账号、``owner`` 为被访问者账号;
        ``first_at`` 自动写入,``last_at`` 由写入方显式赋值。

    返回参数:
        构造出的 ``ProfileVisit`` 实例。

    使用示例:
        ``ProfileVisit.objects.update_or_create(viewer_id=1, owner_id=2, defaults={"last_at": now})``

    备注信息:
        写入只走 ``services._record_visit``:它负责隐身、资料完善度、30 分钟节流与
        每个 owner 的条数上限四道闸,直接建行会绕过这些限制。
    """

    viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="visits_made")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="visits_received")
    first_at = models.DateTimeField("首次访问", auto_now_add=True)
    last_at = models.DateTimeField("最近访问", db_index=True)

    class Meta:
        ordering = ["-last_at"]
        constraints = [
            models.UniqueConstraint(fields=["viewer", "owner"], name="uniq_visit_viewer_owner"),
        ]
        indexes = [
            models.Index(fields=["owner", "-last_at"], name="idx_visit_owner_last"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``visit(浏览者 id -> 被访问者 id)``。

        使用示例:
            ``str(visit)``

        备注信息:
            两个 id 都是账号主键。
        """
        return f"visit({self.viewer_id}->{self.owner_id})"