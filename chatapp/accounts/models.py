from django.contrib.auth.models import AbstractUser, UserManager as BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError("phone is required")
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self.model(phone=phone, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


SESSION_VERSION_DEFAULT = 1   # 单设备登录:登录时 version+1,>1 说明已有过会话


class User(AbstractUser):
    username = None
    phone = models.CharField("手机号", max_length=20, unique=True)
    # 单设备登录:每次登录 +1;JWT 里带签发时的版本,鉴权时对不上 = 已在别处登录
    session_version = models.PositiveIntegerField("会话版本", default=SESSION_VERSION_DEFAULT)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    objects = UserManager()

    @property
    def im_user_id(self):
        """腾讯云 IM 的账号标识;全项目只在这里拼,别处一律用这个属性。"""
        return f"u{self.id}"

    def __str__(self):
        return self.phone
