"""账号模型:以手机号为登录标识的自定义用户、端会话表,以及准入名单。

设计要点:
    1. 继承 ``AbstractUser`` 但把 ``username`` 置空、``USERNAME_FIELD`` 改为 ``phone``,
       因此必须自带 ``UserManager``(默认管理器按 username 建号会失败);
    2. ``DeviceSession`` 支撑**多端在线**(批次 K):会话版本按 ``(user, client_type)``
       各存一行,一个 App + 一个网页可同时在线,同类互顶;``User.session_version``
       已弃用,只作为迁移桥接的历史值保留;
    3. ``im_user_id`` 是全项目唯一的 IM 账号拼装点(``u{user_id}``),别处一律用它;
    4. ``PhoneAllowlist`` 是封闭测试的准入名单(B-1c):本项目不接短信商,固定验证码
       ``123456`` + 名单 = 长期准入机制,因此**这张表本身就是安全边界**;
    5. ``PhoneAllowlistEvent`` 是这份边界的**操作流水**(R4-B2):加号、启停、种子导入
       各留一条(谁、何时、对哪个号做了什么)。``PhoneAllowlist`` 自己只有
       ``created_by`` 与 ``updated_at``,回答不了「谁把谁拿掉、谁又放回来」。

注意事项:
    登录一律走短信验证码,普通用户的密码是不可用的(``set_unusable_password``);
    只有 ``create_superuser`` 会设置真实密码,供 Django admin 使用。

文件信息:
    文件名称          accounts/models.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager as BaseUserManager
from django.db import models

from .validators import mask_phone


class UserManager(BaseUserManager):
    """手机号建号管理器,替代按 username 建号的默认实现。

    参数说明:
        无构造参数;由 ``User.objects`` 直接使用。

    返回参数:
        管理器实例;``create_user`` / ``create_superuser`` 返回 ``User`` 实例。

    使用示例:
        ``User.objects.create_user("13900009000")``

    备注信息:
        默认管理器按 ``username`` 建号,而 ``User`` 已移除该字段,因此必须用本类。
    """

    use_in_migrations = True

    def create_user(self, phone, password=None, **extra_fields):
        """创建一个使用不可用密码的普通用户。

        参数说明:
            phone: 手机号,同时作为登录标识。
            password: 忽略;普通用户一律使用不可用密码,登录走短信验证码。
            **extra_fields: 其余用户字段。

        返回参数:
            新建的用户实例。

        使用示例:
            ``User.objects.create_user("13900009000")``

        备注信息:
            未提供手机号时抛 ``ValueError``;``is_staff`` / ``is_superuser`` 默认置假。
        """
        if not phone:
            raise ValueError("phone is required")
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self.model(phone=phone, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password, **extra_fields):
        """创建一个可登录 Django admin 的超级用户。

        参数说明:
            phone: 手机号。
            password: admin 登录密码,是全项目唯一会设置真实密码的路径。
            **extra_fields: 其余用户字段。

        返回参数:
            新建的超级用户实例。

        使用示例:
            ``User.objects.create_superuser("13900009000", "S3cret!")``

        备注信息:
            ``is_staff`` / ``is_superuser`` 默认置真;``password`` 必填,不能为 ``None``。
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


SESSION_VERSION_DEFAULT = 1   # 会话版本初值;登录时该端 version+1,>1 说明已有过会话


class User(AbstractUser):
    """以手机号为登录标识的用户。

    Attributes:
        phone: 手机号,全局唯一,同时是 ``USERNAME_FIELD``。
        session_version: **已弃用**(批次 K)。多端在线后鉴权改看
            ``accounts.DeviceSession.version``(按端各一行);本列只作为迁移桥接的
            历史值保留,新代码不写它。删除是独立清理项。
        totp_secret: 运营账号的 TOTP 密钥(base32);普通用户为空。

    参数说明:
        **kwargs: 模型字段初始值,按字段名传(``phone``、``totp_secret`` 等);
            建号请走 ``User.objects.create_user()``。

    返回参数:
        实例化后得到 ``User`` 实例;``id`` 由数据库在 ``save()`` 后分配。

    使用示例:
        ``User.objects.create_user("13900009000")``

    备注信息:
        ``username`` 已置空,``USERNAME_FIELD`` 是 ``phone``;普通用户密码不可用,
        只有 ``create_superuser`` 会设置真实密码。
    """

    username = None
    phone = models.CharField("手机号", max_length=20, unique=True)
    # DEPRECATED(批次 K):多端在线后鉴权改看 accounts.DeviceSession.version;
    # 本列只作为迁移桥接的历史值保留,不再读写。删除是独立清理项。
    session_version = models.PositiveIntegerField("会话版本(已弃用)",
                                                 default=SESSION_VERSION_DEFAULT)
    # 运营后台的第二因子;空串表示尚未绑定,首次登录后台时引导绑定
    totp_secret = models.CharField("TOTP 密钥", max_length=64, blank=True, default="")

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    objects = UserManager()

    @property
    def im_user_id(self):
        """IM 账号标识(``u{user_id}``);全项目只在这里拼,别处一律用这个属性。

        参数说明:
            无。

        返回参数:
            形如 ``u42`` 的 IM 账号字符串。

        使用示例:
            ``user.im_user_id``

        备注信息:
            依赖 ``self.id``,未落库时拼出来是 ``uNone``,因此只能在 ``save()`` 之后取。
        """
        return f"u{self.id}"

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            用户手机号。

        使用示例:
            ``str(user)``

        备注信息:
            返回完整手机号,脱敏只出现在页面与日志输出侧(``accounts.validators``)。
        """
        return self.phone


CLIENT_TYPE_CHOICES = [("app", "App"), ("web", "网页端")]


class DeviceSession(models.Model):
    """一个账号在某一类端上的会话(多端在线,批次 K)。

    设计要点:
        ``unique(user, client_type)`` 就是「同类互顶」的全部实现 —— 同端第二次
        登录把该行 ``version + 1``,旧令牌随即对不上;一个 App + 一个网页各一行,
        互不影响。读写的唯一入口是 ``accounts.device_session``,别在别处直接改本表。

    Attributes:
        user: 所属账号。
        client_type: ``app`` 或 ``web``。
        version: 该端的会话版本;JWT 与 IM token 都带这个值。
        created_at: 首次在该端登录的时间。
        last_active_at: 最近一次在该端登录或刷新令牌的时间(批次 M)。只用于
            「登录设备」列表展示,**不参与鉴权** —— 「在线」仍是账号级 presence。
        logged_out_at: 该端被「下线」的时间;``None`` = 在用(批次 M 补丁)。**下线
            是打标记,不是删行** —— 行留着版本号才能保持单调递增,旧令牌才不会因为
            「行被删了、版本回到默认值」重新变有效。登录设备列表只列
            ``logged_out_at IS NULL`` 的端(唯一读写入口 ``accounts.device_session``)。

    参数说明:
        **kwargs: 模型字段初始值,按字段名传(``user``、``client_type`` 等)。

    返回参数:
        实例化后得到 ``DeviceSession`` 实例;``version`` 默认取
        ``SESSION_VERSION_DEFAULT``。

    使用示例:
        ``DeviceSession.objects.filter(user=user, client_type="web").first()``

    备注信息:
        ``unique(user, client_type)`` 就是「同类互顶」的全部实现,别在
        ``accounts.device_session`` 之外直接改本表。
    """

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE,
                             related_name="device_sessions", verbose_name="账号")
    client_type = models.CharField("端类型", max_length=8, choices=CLIENT_TYPE_CHOICES)
    version = models.PositiveIntegerField("会话版本", default=SESSION_VERSION_DEFAULT)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    # 可空:批次 K 之前建的行没有这个值,不给历史数据补写(补写等于谎报活跃时间)
    last_active_at = models.DateTimeField("最后活跃时间", null=True, blank=True)
    # 可空:None = 该端在用;有值 = 该端已被下线(不再出现在登录设备列表里)
    logged_out_at = models.DateTimeField("下线时间", null=True, blank=True)

    class Meta:
        """约束:一个账号每类端只有一行(同类互顶的数据基础)。"""

        constraints = [
            models.UniqueConstraint(fields=["user", "client_type"],
                                    name="uniq_device_session_user_client"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``<账号 id>:<端类型>@v<版本>``。

        使用示例:
            ``str(session)``

        备注信息:
            只用于展示,鉴权判定一律读 ``version`` 字段本身。
        """
        return f"{self.user_id}:{self.client_type}@v{self.version}"


class PhoneAllowlist(models.Model):
    """封闭测试准入名单(B-1 / B-1c):有资格收发短信验证码的手机号。

    为什么是「表」而不是 ``.env`` 里一行逗号分隔的字符串:
        本项目 2026-11-03 起确定**不接入短信商**,固定验证码 ``123456`` + 名单就是
        **长期准入机制**。名单里的人彼此之间用固定码可以互相登录,所以「谁在名单里」
        等于「谁算自己人」—— 这份名单要能随时加、随时停用、留得住是谁加的,
        改 ``.env`` 再重启 web 做不到这三点(还会因为一个逗号打错把所有人挡在外面)。

    与 ``Settings`` 的关系:
        ``settings.SMS_PHONE_WHITELIST`` 降级为「兜底种子」:库里没有这条记录时仍按它
        放行(冷启动、首次导入前的过渡);但**库里显式停用的号码优先被拒**,否则
        「停用」就停不掉那些还留在 ``.env`` 里的号码。判定逻辑唯一入口是
        ``accounts.services.ensure_phone_allowed()``,不要在别处另写一份。

    Attributes:
        phone: 手机号;全局唯一,与 ``User.phone`` 同一口径(11 位,1 开头)。
        note: 备注(谁在用、为什么加),方便以后清理名单时判断。
        is_active: 是否启用;停用 = 该号码立刻 ``403 + 40301``,记录保留可追溯。
        created_by: 加号的操作账号;运营账号被删除时置空,不连带删名单。
        created_at: 加入时间。
        updated_at: 最后一次改动(启停/改备注)时间。

    参数说明:
        **kwargs: 模型字段初始值,按字段名传(``phone``、``note``、``is_active`` 等)。

    返回参数:
        实例化后得到 ``PhoneAllowlist`` 实例;``is_active`` 默认 ``True``。

    使用示例:
        ``PhoneAllowlist.objects.create(phone="13900009000", note="内测")``

    备注信息:
        判定逻辑唯一入口是 ``accounts.services.ensure_phone_allowed()``,
        不要在别处另写一份。
    """

    phone = models.CharField("手机号", max_length=20, unique=True)
    note = models.CharField("备注", max_length=100, blank=True, default="")
    is_active = models.BooleanField("启用", default=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="加入人",
                                  null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="+")
    created_at = models.DateTimeField("加入时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        """新加的号排最前;启用中的排在停用前,便于一眼看到当前准入面。"""

        verbose_name = "手机号准入名单"
        verbose_name_plural = verbose_name
        ordering = ["-is_active", "-created_at"]

    def __str__(self):
        """后台列表里的可读标识。

        参数说明:
            无。

        返回参数:
            形如 ``139****9000(启用)`` 的脱敏摘要。

        使用示例:
            ``str(entry)``

        备注信息:
            号码一律经 ``accounts.validators.mask_phone`` 脱敏,不在这里直接拼原号。
        """
        return f"{mask_phone(self.phone)}({'启用' if self.is_active else '停用'})"


class PhoneAllowlistAction(models.TextChoices):
    """准入名单的操作类型:一条流水记录「这是哪一种改动」。

    分四种而不是只有「改」:事后追查时「新放进来一个人」与「把一个人拿掉」的
    严重程度完全不同,不能混成一条流水。

    参数说明:
        无构造参数;成员以 ``(值, 展示名)`` 二元组声明,由 ``TextChoices`` 展开。

    返回参数:
        成员即 ``str`` 子类实例,可直接落库;``.label`` 是后台展示名。

    使用示例:
        ``PhoneAllowlistAction.ADD.value``

    备注信息:
        取值一旦落库不要改名,历史流水靠它反查动作语义。
    """

    ADD = "add", "加入名单"
    ENABLE = "enable", "重新启用"
    DISABLE = "disable", "停用"
    SEED_IMPORT = "seed_import", "种子导入"


class PhoneAllowlistEvent(models.Model):
    """准入名单的操作流水(append-only):谁、何时、对哪个号码做了什么。

    为什么另起一张表(而不是给 ``PhoneAllowlist`` 加一个 ``updated_by``):
        启停是**反复发生**的动作,单列 ``updated_by`` 只会留下最后一次,把前面
        「谁把谁拿掉」的历史全盖掉;而名单是安全边界,历史不能覆盖,只能追加。

    为什么存完整号码(而不是脱敏串):
        与 ``PhoneAllowlist.phone`` 同口径,审计要能把「这个号」反查到「这个账号」;
        脱敏只出现在页面与日志里(``accounts.validators.mask_phone``)。

    Attributes:
        phone: 被操作的手机号,完整 11 位。
        action: 操作类型,取值见 :class:`PhoneAllowlistAction`。
        operator: 操作账号;运营账号被删除时置空(SET_NULL),流水本身不删。
            种子导入命令没有操作人,落 ``None``。
        note: 操作当时的备注快照,方便回看「加进来时写的是什么」。
        created_at: 发生时间(流水写入时刻)。

    参数说明:
        **kwargs: 模型字段初始值,按字段名传(``phone``、``action``、``operator`` 等)。

    返回参数:
        实例化后得到 ``PhoneAllowlistEvent`` 实例。

    使用示例:
        ``PhoneAllowlistEvent.objects.create(phone="13900009000", action="add")``

    备注信息:
        append-only:流水只增不改不删,名单的历史靠它回答「谁把谁拿掉、谁又放回来」。
    """

    phone = models.CharField("手机号", max_length=20)
    action = models.CharField(
        "动作", max_length=16, choices=PhoneAllowlistAction.choices)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="操作人", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
    note = models.CharField("备注", max_length=100, blank=True, default="")
    created_at = models.DateTimeField("发生时间", auto_now_add=True)

    class Meta:
        """最新的排最前;号码维度上按时间倒序,便于回答「这个号最近怎么被改的」。"""

        verbose_name = "准入名单操作流水"
        verbose_name_plural = verbose_name
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["phone", "-created_at"], name="allow_evt_phone_idx"),
        ]

    def __str__(self):
        """后台与日志里的可读标识。

        参数说明:
            无。

        返回参数:
            形如 ``139****9000 加入名单`` 的脱敏摘要。

        使用示例:
            ``str(event)``

        备注信息:
            动作名取 ``get_action_display()``,与后台展示口径一致。
        """
        return f"{mask_phone(self.phone)} {self.get_action_display()}"
