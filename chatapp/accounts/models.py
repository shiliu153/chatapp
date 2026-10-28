"""账号模型:以手机号为登录标识的自定义用户。

设计要点:
    1. 继承 ``AbstractUser`` 但把 ``username`` 置空、``USERNAME_FIELD`` 改为 ``phone``,
       因此必须自带 ``UserManager``(默认管理器按 username 建号会失败);
    2. ``session_version`` 支撑单设备登录:每次登录 +1 并写进 JWT,鉴权时比对;
    3. ``im_user_id`` 是全项目唯一的 IM 账号拼装点(``u{user_id}``),别处一律用它。

注意事项:
    登录一律走短信验证码,普通用户的密码是不可用的(``set_unusable_password``);
    只有 ``create_superuser`` 会设置真实密码,供 Django admin 使用。
"""

from django.contrib.auth.models import AbstractUser, UserManager as BaseUserManager
from django.db import models


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
        """腾讯云 IM 的账号标识;全项目只在这里拼,别处一律用这个属性。"""
        return f"u{self.id}"

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            用户手机号。
        """
        return self.phone
