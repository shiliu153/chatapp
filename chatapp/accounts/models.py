"""账号模型:以手机号为登录标识的自定义用户,以及准入名单。

设计要点:
    1. 继承 ``AbstractUser`` 但把 ``username`` 置空、``USERNAME_FIELD`` 改为 ``phone``,
       因此必须自带 ``UserManager``(默认管理器按 username 建号会失败);
    2. ``session_version`` 支撑单设备登录:每次登录 +1 并写进 JWT,鉴权时比对;
    3. ``im_user_id`` 是全项目唯一的 IM 账号拼装点(``u{user_id}``),别处一律用它;
    4. ``PhoneAllowlist`` 是封闭测试的准入名单(B-1c):本项目不接短信商,固定验证码
       ``123456`` + 名单 = 长期准入机制,因此**这张表本身就是安全边界**;
    5. ``PhoneAllowlistEvent`` 是这份边界的**操作流水**(R4-B2):加号、启停、种子导入
       各留一条(谁、何时、对哪个号做了什么)。``PhoneAllowlist`` 自己只有
       ``created_by`` 与 ``updated_at``,回答不了「谁把谁拿掉、谁又放回来」。

注意事项:
    登录一律走短信验证码,普通用户的密码是不可用的(``set_unusable_password``);
    只有 ``create_superuser`` 会设置真实密码,供 Django admin 使用。
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager as BaseUserManager
from django.db import models

from .validators import mask_phone


class UserManager(BaseUserManager):
    """手机号建号管理器,替代按 username 建号的默认实现。"""

    use_in_migrations = True

    def create_user(self, phone, password=None, **extra_fields):
        """创建一个使用不可用密码的普通用户。

        Args:
            phone: 手机号,同时作为登录标识。
            password: 忽略;普通用户一律使用不可用密码,登录走短信验证码。
            **extra_fields: 其余用户字段。

        Returns:
            新建的用户实例。

        Raises:
            ValueError: 未提供手机号。
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

        Args:
            phone: 手机号。
            password: admin 登录密码,是全项目唯一会设置真实密码的路径。
            **extra_fields: 其余用户字段。

        Returns:
            新建的超级用户实例。
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


SESSION_VERSION_DEFAULT = 1   # 单设备登录:登录时 version+1,>1 说明已有过会话


class User(AbstractUser):
    """以手机号为登录标识的用户。

    Attributes:
        phone: 手机号,全局唯一,同时是 ``USERNAME_FIELD``。
        session_version: 会话版本;JWT 里带签发时的值,与数据库当前值不一致即作废。
        totp_secret: 运营账号的 TOTP 密钥(base32);普通用户为空。
    """

    username = None
    phone = models.CharField("手机号", max_length=20, unique=True)
    # 单设备登录:每次登录 +1;JWT 里带签发时的版本,鉴权时对不上 = 已在别处登录
    session_version = models.PositiveIntegerField("会话版本", default=SESSION_VERSION_DEFAULT)
    # 运营后台的第二因子;空串表示尚未绑定,首次登录后台时引导绑定
    totp_secret = models.CharField("TOTP 密钥", max_length=64, blank=True, default="")

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    objects = UserManager()

    @property
    def im_user_id(self):
        """IM 账号标识(``u{user_id}``);全项目只在这里拼,别处一律用这个属性。"""
        return f"u{self.id}"

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            用户手机号。
        """
        return self.phone


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

        Returns:
            形如 ``139****9000(启用)`` 的脱敏摘要。
        """
        return f"{mask_phone(self.phone)}({'启用' if self.is_active else '停用'})"


class PhoneAllowlistAction(models.TextChoices):
    """准入名单的操作类型:一条流水记录「这是哪一种改动」。

    分四种而不是只有「改」:事后追查时「新放进来一个人」与「把一个人拿掉」的
    严重程度完全不同,不能混成一条流水。
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

        Returns:
            形如 ``139****9000 加入名单`` 的脱敏摘要。
        """
        return f"{mask_phone(self.phone)} {self.get_action_display()}"
